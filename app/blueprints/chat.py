"""
app/blueprints/chat.py — واجهة الشات (/c/<slug>)
يشمل: تسجيل دخول الزائر بالاسم والبريد + كود تحقق بالإيميل.
"""
import json
import random
import string
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, jsonify, session, g, redirect, url_for, flash, current_app

from app.extensions import db, limiter, csrf
from sqlalchemy.exc import SQLAlchemyError
from app.models.tenant import Tenant
from app.models.chat_visitor import ChatVisitor
from app.models.conversation import Conversation, Message
from app.services.email_service import EmailService
from app.utils.slug import generate_visitor_id

bp = Blueprint('chat', __name__, template_folder='../../templates/chat')


def _get_tenant(slug):
    return Tenant.query.filter_by(slug=slug, status='active').first_or_404()


def _get_visitor(tenant_id):
    """جلب الزائر المسجّل من session."""
    token = session.get('chat_visitor_token')
    if not token:
        return None
    return ChatVisitor.query.filter_by(tenant_id=tenant_id, visitor_token=token, is_verified=True).first()


# ==================== صفحة تسجيل الزائر ====================
@bp.route('/<slug>', methods=['GET'])
def interface(slug):
    tenant = _get_tenant(slug)

    # التحقق من الاشتراك
    sub = tenant.subscription
    if not sub or not sub.is_active:
        return render_template('chat/unavailable.html', tenant=tenant), 503

    # هل الزائر مسجّل ومتحقق؟
    visitor = _get_visitor(tenant.id)
    if not visitor:
        return render_template('chat/visitor_login.html', tenant=tenant, slug=slug)

    return render_template('chat/interface.html', tenant=tenant, visitor=visitor)


@bp.route('/<slug>/register', methods=['POST'])
@csrf.exempt
@limiter.limit('10 per hour')
def visitor_register(slug):
    """تسجيل الزائر + إرسال كود تحقق بالبريد."""
    tenant = _get_tenant(slug)
    data = request.get_json(silent=True) or request.form

    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    phone = (data.get('phone') or '').strip()

    if not name or not email or '@' not in email:
        return jsonify({'error': 'الاسم والبريد مطلوبين'}), 400

    # البحث عن زائر موجود أو إنشاء جديد
    visitor = ChatVisitor.query.filter_by(tenant_id=tenant.id, email=email).first()
    if not visitor:
        visitor = ChatVisitor(
            tenant_id=tenant.id,
            name=name,
            email=email,
            phone=phone,
            visitor_token=generate_visitor_id(32),
        )
        db.session.add(visitor)
    else:
        visitor.name = name
        if phone:
            visitor.phone = phone

    # توليد كود تحقق (6 أرقام) — مشفّر
    code = ''.join(random.choices(string.digits, k=6))
    visitor.set_verification_code(code)  # ✅ يحفظ hash + salt
    visitor.verification_expires = datetime.utcnow() + timedelta(minutes=10)
    visitor.is_verified = False
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('visitor_register: DB commit failed')
        return jsonify({
            'error': (
                'تعذر حفظ بياناتك. إن لم تكن قد حدّثت الجداول، شغّل من مجلد المشروع: '
                'flask init-db ثم أعد المحاولة.'
            ),
        }), 500

    # إرسال الكود بالإيميل
    EmailService._send(
        to=email,
        subject=f"رمز التحقق — {tenant.business_name}",
        body_html=f"""
        <div dir="rtl" style="font-family:Tahoma,Arial;padding:20px;text-align:center;">
            <h2>رمز التحقق الخاص بك</h2>
            <p>مرحباً {name}،</p>
            <div style="font-size:32px;font-weight:bold;letter-spacing:8px;
                padding:20px;background:#f3f4f6;border-radius:12px;margin:20px auto;width:200px;">
                {code}
            </div>
            <p style="color:#6b7280;">صالح لمدة 10 دقائق</p>
            <p style="color:#9ca3af;font-size:12px;">{tenant.business_name}</p>
        </div>
        """
    )

    return jsonify({'success': True, 'message': 'تم إرسال رمز التحقق إلى بريدك'})


@bp.route('/<slug>/verify', methods=['POST'])
@csrf.exempt
@limiter.limit('20 per hour')
def visitor_verify(slug):
    """التحقق من الكود."""
    tenant = _get_tenant(slug)
    data = request.get_json(silent=True) or request.form

    email = (data.get('email') or '').strip().lower()
    code = (data.get('code') or '').strip()

    if not email or not code:
        return jsonify({'error': 'البريد والرمز مطلوبين'}), 400

    visitor = ChatVisitor.query.filter_by(tenant_id=tenant.id, email=email).first()
    if not visitor:
        return jsonify({'error': 'البريد غير مسجّل'}), 404

    # ✅ تحقق آمن: hash + حد محاولات + قفل
    success, message = visitor.check_verification_code(code)
    if not success:
        try:
            db.session.commit()  # حفظ عداد المحاولات
        except Exception:
            db.session.rollback()
        return jsonify({'error': message}), 400

    visitor.last_seen = datetime.utcnow()
    db.session.commit()

    session['chat_visitor_token'] = visitor.visitor_token

    return jsonify({'success': True, 'redirect': url_for('chat.interface', slug=slug)})


# ==================== API الرسائل ====================
@bp.route('/<slug>/message', methods=['POST'])
@csrf.exempt
@limiter.limit('30 per minute')
def send_message(slug):
    """
    معالجة رسالة الزائر — مغلّفة بحماية كاملة لمنع علقان الشات.
    أي خطأ يُسجَّل ويُرجَع رد افتراضي بدلاً من تعليق الواجهة.
    """
    try:
        current_app.logger.info('[Chat/message] start slug=%s', slug)
        tenant = _get_tenant(slug)
        visitor = _get_visitor(tenant.id)
        if not visitor:
            return jsonify({'success': False, 'error': 'يجب تسجيل الدخول'}), 401

        sub = tenant.subscription
        if not sub or not sub.is_active:
            return jsonify({
                'success': False,
                'error': 'الخدمة غير مفعّلة حالياً، يرجى المحاولة لاحقاً',
            }), 503

        data = request.get_json(silent=True) or {}
        user_message = (data.get('message') or '').strip()
        conversation_id = data.get('conversation_id')

        if not user_message:
            return jsonify({'success': False, 'error': 'الرسالة فارغة'}), 400

        if len(user_message) > 2000:
            return jsonify({'success': False, 'error': 'الرسالة طويلة جداً'}), 400

        current_app.logger.info(
            '[Chat/message] tenant_id=%s conv_param=%s msg_len=%s',
            tenant.id, conversation_id, len(user_message),
        )

        # إيجاد/إنشاء محادثة
        conversation = None
        if conversation_id:
            conversation = Conversation.query.filter_by(
                id=conversation_id, tenant_id=tenant.id,
            ).first()
        if not conversation:
            conversation = Conversation(
                tenant_id=tenant.id,
                visitor_id=visitor.visitor_token,
                visitor_name=visitor.name,
                visitor_email=visitor.email,
                visitor_phone=visitor.phone,
                channel='web',
            )
            db.session.add(conversation)
            try:
                db.session.flush()
            except SQLAlchemyError as e:
                db.session.rollback()
                current_app.logger.error(f'[Chat] DB flush error creating conversation: {e}')
                return jsonify({
                    'success': False,
                    'error': 'حدث خطأ مؤقت، يرجى المحاولة مرة أخرى',
                }), 500

        # حفظ رسالة الزائر
        try:
            db.session.add(Message(
                conversation_id=conversation.id, tenant_id=tenant.id,
                sender_type='visitor', content=user_message,
            ))
            db.session.flush()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.error(f'[Chat] DB error saving visitor message: {e}')
            return jsonify({
                'success': False,
                'error': 'حدث خطأ مؤقت في حفظ الرسالة',
            }), 500

        # توليد الرد — محاط بحماية كاملة
        ai_response = None
        delivery = {'text': '', 'images': [], 'extra_data': {}}
        
        if not sub.can_send_chat():
            phone_msg = f" عبر الرقم {tenant.owner_phone}" if tenant.owner_phone else ""
            ai_response = f"عذراً، نواجه ضغطاً في الرسائل حالياً. يرجى التواصل مع إدارة {tenant.business_name}{phone_msg} لخدمتك بشكل أسرع."
        else:
            try:
                current_app.logger.info(
                    '[Chat/message] before generate_reply conv_id=%s', conversation.id,
                )
                from app.services.chat_service import ChatService
                ai_response = ChatService.generate_reply(tenant, conversation, user_message)
                current_app.logger.info(
                    '[Chat/message] after generate_reply conv_id=%s reply_len=%s',
                    conversation.id,
                    len(ai_response or ''),
                )
            except Exception as e:
                current_app.logger.exception(f'[Chat] generate_reply failed: {e}')
                ai_response = (
                    "آسف، حدث خطأ مؤقت في معالجة رسالتك. تم تسجيل المشكلة وسنرد عليك قريباً."
                )

        # تقسيم الرد إلى عدة فقاعات لو كان الـ IntentEngine طلب ذلك
        from app.services.chat_service import REPLY_SPLIT
        raw_full = ai_response or ''
        reply_parts = [p for p in raw_full.split(REPLY_SPLIT) if p is not None]
        if not reply_parts:
            reply_parts = ['']
        primary_text = reply_parts[0]
        extra_texts = reply_parts[1:]

        try:
            current_app.logger.info('[Chat/message] before prepare_bot_reply_delivery')
            from app.services.unit_images_helper import prepare_bot_reply_delivery
            delivery = prepare_bot_reply_delivery(tenant.id, primary_text, conversation)
            current_app.logger.info(
                '[Chat/message] after prepare_bot_reply_delivery images=%s',
                len(delivery.get('images') or []),
            )
        except Exception as e:
            current_app.logger.warning(f'[Chat] prepare_bot_reply_delivery failed: {e}')
            delivery = {
                'text': primary_text or '',
                'images': [],
                'extra_data': {},
            }

        # حفظ رد البوت (+ الفقاعات الإضافية) + commit
        try:
            bot_msg = Message(
                conversation_id=conversation.id, tenant_id=tenant.id,
                sender_type='bot', content=delivery.get('text') or '',
                extra_data=delivery.get('extra_data') or {},
            )
            db.session.add(bot_msg)
            db.session.flush()  # للحصول على bot_msg.id قبل إضافة الإضافيات

            # احفظ كل فقاعة إضافية كرسالة منفصلة (تظهر في السجل)
            extra_msgs = []
            for et in extra_texts:
                txt = (et or '').strip()
                if not txt:
                    continue
                em = Message(
                    conversation_id=conversation.id, tenant_id=tenant.id,
                    sender_type='bot', content=txt,
                    extra_data={'is_followup': True},
                )
                db.session.add(em)
                extra_msgs.append(em)

            try:
                # خصم رسالة واحدة فقط رغم تعدد الفقاعات
                if sub.can_send_chat():
                    sub.increment_chat_usage(1)
            except Exception as e:
                current_app.logger.warning(f'[Chat] increment_chat_usage failed: {e}')

            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.error(f'[Chat] commit error: {e}')
            return jsonify({
                'success': True,
                'conversation_id': conversation.id if conversation else None,
                'reply': {
                    'id': None,
                    'content': delivery.get('text') or 'حصل خطأ في الحفظ',
                    'sender_type': 'bot',
                    'images': [],
                },
            })

        reply_payload = {
            'id': bot_msg.id,
            'content': delivery.get('text') or '',
            'sender_type': 'bot',
            'images': delivery.get('images') or [],
        }
        extras_payload = []
        for em in extra_msgs:
            extras_payload.append({
                'id': em.id,
                'content': em.content,
                'sender_type': 'bot',
                'images': [],
            })
        current_app.logger.info('[Chat/message] done OK conv_id=%s extras=%s', conversation.id, len(extras_payload))
        return jsonify({
            'success': True,
            'conversation_id': conversation.id,
            'reply': reply_payload,
            'extra_replies': extras_payload,
        })

    except Exception as e:
        # حماية شاملة من أي خطأ غير متوقع
        try:
            db.session.rollback()
        except Exception:
            pass
        current_app.logger.exception(f'[Chat] unhandled error in send_message: {e}')
        return jsonify({
            'success': False,
            'error': 'حدث خطأ غير متوقع. يرجى المحاولة مرة أخرى.',
        }), 500


@bp.route('/<slug>/history')
def history(slug):
    """يرجع آخر محادثة افتراضياً، أو all=1 لقائمة كل المحادثات."""
    tenant = _get_tenant(slug)
    visitor = _get_visitor(tenant.id)
    if not visitor:
        return jsonify({'messages': []})

    want_all = request.args.get('all') == '1'
    conv_id = request.args.get('conversation_id')

    if want_all and not conv_id:
        convs = (
            Conversation.query
            .filter_by(tenant_id=tenant.id, visitor_id=visitor.visitor_token)
            .order_by(Conversation.started_at.desc())
            .limit(50)
            .all()
        )
        return jsonify({
            'conversations': [
                {
                    'id': c.id,
                    'started_at': c.started_at.isoformat() if c.started_at else None,
                    'updated_at': c.updated_at.isoformat() if c.updated_at else None,
                    'last_message': (c.messages.order_by(Message.created_at.desc()).first().content[:100]
                                     if c.messages.first() else ''),
                    'count': c.messages.count(),
                }
                for c in convs
            ],
        })

    if conv_id:
        try:
            cid = int(conv_id)
        except (TypeError, ValueError):
            return jsonify({'messages': []})
        conv = Conversation.query.filter_by(
            id=cid, tenant_id=tenant.id, visitor_id=visitor.visitor_token,
        ).first()
    else:
        conv = (
            Conversation.query
            .filter_by(tenant_id=tenant.id, visitor_id=visitor.visitor_token)
            .order_by(Conversation.started_at.desc())
            .first()
        )

    if not conv:
        return jsonify({'messages': []})
    msgs = [m.to_dict() for m in conv.messages.order_by(Message.created_at).all()]
    return jsonify({'conversation_id': conv.id, 'messages': msgs})


# ==================== تسجيل الخروج / حذف البيانات ====================
@bp.route('/<slug>/logout', methods=['POST'])
@csrf.exempt
def visitor_logout(slug):
    """تسجيل خروج الزائر — لا يحذف بياناته، فقط ينهي الجلسة."""
    tenant = _get_tenant(slug)
    session.pop('chat_visitor_token', None)
    return jsonify({'success': True, 'redirect': url_for('chat.interface', slug=slug)})


@bp.route('/<slug>/conversations/<int:conv_id>/delete', methods=['POST'])
@csrf.exempt
@limiter.limit('20 per hour')
def delete_conversation(slug, conv_id):
    """حذف محادثة معيّنة (للزائر صاحبها فقط)."""
    tenant = _get_tenant(slug)
    visitor = _get_visitor(tenant.id)
    if not visitor:
        return jsonify({'success': False, 'error': 'يجب تسجيل الدخول'}), 401

    conv = Conversation.query.filter_by(
        id=conv_id,
        tenant_id=tenant.id,
        visitor_id=visitor.visitor_token,
    ).first()
    if not conv:
        return jsonify({'success': False, 'error': 'المحادثة غير موجودة'}), 404

    try:
        # تفصيل أي استفسارات/عقود مرتبطة بدلاً من كسر FK
        from app.models.inquiry import Inquiry
        Inquiry.query.filter_by(
            conversation_id=conv.id,
            tenant_id=tenant.id,
        ).update({'conversation_id': None}, synchronize_session=False)

        # حذف الرسائل التابعة عبر cascade (Conversation → Message)
        db.session.delete(conv)
        db.session.commit()
        return jsonify({'success': True})
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f'[Chat] delete_conversation error: {e}')
        return jsonify({'success': False, 'error': 'تعذّر الحذف'}), 500


@bp.route('/<slug>/me/delete', methods=['POST'])
@csrf.exempt
@limiter.limit('5 per hour')
def delete_visitor_data(slug):
    """حذف نهائي لبيانات الزائر + كل محادثاته (Right to be forgotten)."""
    tenant = _get_tenant(slug)
    visitor = _get_visitor(tenant.id)
    if not visitor:
        return jsonify({'success': False, 'error': 'يجب تسجيل الدخول'}), 401

    try:
        from app.models.inquiry import Inquiry

        conv_ids = [c.id for c in Conversation.query.filter_by(
            tenant_id=tenant.id,
            visitor_id=visitor.visitor_token,
        ).all()]

        if conv_ids:
            Inquiry.query.filter(
                Inquiry.tenant_id == tenant.id,
                Inquiry.conversation_id.in_(conv_ids),
            ).update({'conversation_id': None}, synchronize_session=False)

            for c in Conversation.query.filter(
                Conversation.tenant_id == tenant.id,
                Conversation.id.in_(conv_ids),
            ).all():
                db.session.delete(c)

        db.session.delete(visitor)
        db.session.commit()
        session.pop('chat_visitor_token', None)
        return jsonify({
            'success': True,
            'redirect': url_for('chat.interface', slug=slug),
        })
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f'[Chat] delete_visitor_data error: {e}')
        return jsonify({'success': False, 'error': 'تعذّر الحذف، حاول لاحقاً'}), 500


@bp.route('/<slug>/conversations/new', methods=['POST'])
@csrf.exempt
@limiter.limit('30 per hour')
def start_new_conversation(slug):
    """يفتح محادثة جديدة دون مساس بالقديمة."""
    tenant = _get_tenant(slug)
    visitor = _get_visitor(tenant.id)
    if not visitor:
        return jsonify({'success': False, 'error': 'يجب تسجيل الدخول'}), 401

    try:
        conv = Conversation(
            tenant_id=tenant.id,
            visitor_id=visitor.visitor_token,
            visitor_name=visitor.name,
            visitor_email=visitor.email,
            visitor_phone=visitor.phone,
            channel='web',
        )
        db.session.add(conv)
        db.session.commit()
        return jsonify({'success': True, 'conversation_id': conv.id})
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f'[Chat] start_new_conversation error: {e}')
        return jsonify({'success': False, 'error': 'تعذّر إنشاء محادثة'}), 500

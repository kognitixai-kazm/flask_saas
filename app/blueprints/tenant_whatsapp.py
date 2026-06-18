"""
لوحة التاجر — واتساب: محادثات القناة، رد يدوي، تشغيل/إيقاف الرد التلقائي.
(ربط Meta والتوكن يبقى عند إدارة المنصة /sa/integrations)
"""
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, g

from app.extensions import db
from app.decorators import tenant_required, plan_feature_required
from app.models.bot_config import BotConfig
from app.models.integration import Integration
from app.models.conversation import Conversation, Message
from app.services.whatsapp_service import WhatsAppService

bp = Blueprint(
    'tenant_whatsapp',
    __name__,
    template_folder='../../templates/tenant/whatsapp',
)


def _ensure_bot_config(tenant_id: int) -> BotConfig:
    bc = BotConfig.query.filter_by(tenant_id=tenant_id).first()
    if not bc:
        bc = BotConfig(tenant_id=tenant_id)
        db.session.add(bc)
        db.session.commit()
    return bc


def _wa_phone(conv: Conversation) -> str:
    p = (conv.visitor_phone or '').strip()
    if p:
        return p
    vid = (conv.visitor_id or '').strip()
    if vid.startswith('wa_'):
        return vid[3:]
    return ''


@bp.route('/')
@tenant_required
@plan_feature_required('whatsapp')
def index():
    tid = g.current_tenant.id
    bc = _ensure_bot_config(tid)
    convs = (
        Conversation.query.filter_by(tenant_id=tid, channel='whatsapp')
        .order_by(Conversation.updated_at.desc())
        .all()
    )
    has_integration = bool(
        Integration.query.filter_by(
            tenant_id=tid, service_type='whatsapp', is_active=True
        ).first()
    )
    return render_template(
        'tenant/whatsapp/index.html',
        auto_reply=bc.whatsapp_auto_reply_enabled,
        conversations=convs,
        has_integration=has_integration,
    )


@bp.route('/toggle-auto-reply', methods=['POST'])
@tenant_required
@plan_feature_required('whatsapp')
def toggle_auto_reply():
    bc = _ensure_bot_config(g.current_tenant.id)
    want_on = request.form.get('enable', '1') == '1'
    bc.whatsapp_auto_reply_enabled = want_on
    db.session.commit()
    flash(
        'تم تشغيل الرد التلقائي على واتساب.' if want_on else 'تم إيقاف الرد التلقائي على واتساب.',
        'success',
    )
    return redirect(url_for('tenant_whatsapp.index'))


@bp.route('/conversation/<int:conv_id>')
@tenant_required
@plan_feature_required('whatsapp')
def conversation(conv_id: int):
    conv = Conversation.query.filter_by(
        id=conv_id,
        tenant_id=g.current_tenant.id,
        channel='whatsapp',
    ).first_or_404()
    messages = (
        Message.query.filter_by(conversation_id=conv.id)
        .order_by(Message.created_at.asc())
        .all()
    )
    has_integration = bool(
        Integration.query.filter_by(
            tenant_id=g.current_tenant.id, service_type='whatsapp', is_active=True
        ).first()
    )
    phone = _wa_phone(conv)
    return render_template(
        'tenant/whatsapp/conversation.html',
        conversation=conv,
        messages=messages,
        has_integration=has_integration,
        wa_phone=phone,
    )


@bp.route('/conversation/<int:conv_id>/reply', methods=['POST'])
@tenant_required
@plan_feature_required('whatsapp')
def reply(conv_id: int):
    conv = Conversation.query.filter_by(
        id=conv_id,
        tenant_id=g.current_tenant.id,
        channel='whatsapp',
    ).first_or_404()
    text = (request.form.get('message') or '').strip()
    if not text:
        flash('اكتب نص الرسالة.', 'warning')
        return redirect(url_for('tenant_whatsapp.conversation', conv_id=conv.id))

    phone = _wa_phone(conv)
    if not phone:
        flash('لا يوجد رقم واتساب مرتبط بهذه المحادثة.', 'danger')
        return redirect(url_for('tenant_whatsapp.conversation', conv_id=conv.id))

    result = WhatsAppService.send_text(g.current_tenant.id, phone, text)
    if result.get('error'):
        flash(f'تعذّر الإرسال عبر واتساب: {result.get("error")}', 'danger')
        return redirect(url_for('tenant_whatsapp.conversation', conv_id=conv.id))

    agent_label = g.current_user.full_name or g.current_user.username or 'موظف'
    db.session.add(
        Message(
            conversation_id=conv.id,
            tenant_id=g.current_tenant.id,
            sender_type='agent',
            content=text,
            extra_data={'sent_by': agent_label},
        )
    )
    conv.updated_at = datetime.utcnow()
    db.session.commit()
    flash('تم إرسال الرسالة.', 'success')
    return redirect(url_for('tenant_whatsapp.conversation', conv_id=conv.id))

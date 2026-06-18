"""
app/blueprints/tenant_inquiries.py — إدارة الاستفسارات (/app/inquiries/*)
صاحب النشاط يرى الاستفسارات ويرد عليها من هنا.
+ التعلم التلقائي: عند الرد → يُحفظ كرد مخصص.
"""
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, g

from app.extensions import db
from app.decorators import tenant_required
from app.models.inquiry import Inquiry
from app.models.conversation import Conversation
from app.services.chat_service import ChatService

bp = Blueprint('tenant_inquiries', __name__, template_folder='../../templates/tenant/inquiries')


@bp.route('/')
@tenant_required
def list_inquiries():
    """قائمة الاستفسارات."""
    status_filter = request.args.get('status', '')
    kind_filter = (request.args.get('kind') or '').strip()
    q = Inquiry.query.filter_by(tenant_id=g.current_tenant.id)
    if status_filter:
        q = q.filter_by(status=status_filter)
    if kind_filter in ('general', 'complaint'):
        q = q.filter_by(inquiry_kind=kind_filter)
    items = q.order_by(Inquiry.created_at.desc()).all()

    tid = g.current_tenant.id
    counts = {
        'new': Inquiry.query.filter_by(tenant_id=tid, status='new').count(),
        'pending': Inquiry.query.filter_by(tenant_id=tid, status='pending').count(),
        'answered': Inquiry.query.filter_by(tenant_id=tid, status='answered').count(),
        'complaints': Inquiry.query.filter_by(tenant_id=tid, inquiry_kind='complaint').count(),
    }

    return render_template('tenant/inquiries/list.html',
        inquiries=items, counts=counts, status_filter=status_filter,
        kind_filter=kind_filter)


@bp.route('/<int:id>', methods=['GET', 'POST'])
@tenant_required
def detail(id):
    """تفاصيل الاستفسار + الرد عليه."""
    inquiry = Inquiry.query.filter_by(id=id, tenant_id=g.current_tenant.id).first_or_404()

    if request.method == 'POST':
        answer = request.form.get('answer', '').strip()
        if answer:
            inquiry.answer = answer
            inquiry.answered_by = g.current_user.full_name or g.current_user.username
            inquiry.answered_at = datetime.utcnow()
            inquiry.status = 'answered'

            # ==========================================
            # 🧠 التعلم التلقائي
            # ==========================================
            try:
                from app.models.bot_config import BotConfig
                bot_config = BotConfig.query.filter_by(tenant_id=g.current_tenant.id).first()

                if bot_config and bot_config.auto_learn_enabled:
                    from app.models.custom_reply import CustomReply
                    learned = CustomReply.learn_from_inquiry(
                        tenant_id=g.current_tenant.id,
                        question=inquiry.question,
                        answer=answer,
                        inquiry_id=inquiry.id,
                    )
                    if learned:
                        bot_config.learned_replies_count = CustomReply.query.filter_by(
                            tenant_id=g.current_tenant.id, source='learned'
                        ).count()

                    flash('تم إرسال الرد + 🧠 تم حفظه كرد مخصص تلقائياً', 'success')
                else:
                    flash('تم إرسال الرد', 'success')
            except Exception as e:
                flash('تم إرسال الرد', 'success')
                from flask import current_app
                current_app.logger.warning(f'Auto-learn error: {e}')

            db.session.commit()
            try:
                ChatService.deliver_inquiry_agent_response(g.current_tenant, inquiry, answer)
                db.session.commit()
            except Exception as e:
                from flask import current_app
                current_app.logger.warning(f'Inquiry deliver to visitor failed: {e}')
                db.session.rollback()
        return redirect(url_for('tenant_inquiries.detail', id=id))

    conversation = None
    if inquiry.conversation_id:
        conversation = Conversation.query.filter_by(
            id=inquiry.conversation_id,
            tenant_id=g.current_tenant.id,
        ).first()

    return render_template(
        'tenant/inquiries/detail.html',
        inquiry=inquiry,
        conversation=conversation,
    )


@bp.route('/<int:id>/close', methods=['POST'])
@tenant_required
def close(id):
    inquiry = Inquiry.query.filter_by(id=id, tenant_id=g.current_tenant.id).first_or_404()
    inquiry.status = 'closed'
    db.session.commit()
    flash('تم إغلاق الاستفسار', 'success')
    return redirect(url_for('tenant_inquiries.list_inquiries'))

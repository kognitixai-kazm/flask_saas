"""
app/blueprints/admin_pricing.py — إدارة الأسعار من /sa/ai-pricing/

المؤسس يحدد:
- أسعار النماذج (Claude/GPT/Gemini/MiniMax)
- أسعار الخدمات (نصية/صورة/صوت/معالجة)
- يشاهد الإيرادات من كل تاجر
- يشاهد ربحية كل نموذج
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app

from app.extensions import db
from app.decorators import super_admin_required
from app.models.ai_model import AIModel
from app.models.service_pricing import ServicePricing
from app.models.message_usage import MessageUsage

bp = Blueprint('admin_pricing', __name__, template_folder='../../templates/super_admin')


@bp.route('/')
@super_admin_required
def index():
    """الصفحة الرئيسية لإدارة الأسعار."""
    ai_models = AIModel.query.order_by(AIModel.sort_order).all()
    services = ServicePricing.query.order_by(ServicePricing.sort_order).all()

    # نظرة عامة على الإيرادات
    overview = MessageUsage.admin_overview(days=30)
    total_revenue = sum(item['revenue'] for item in overview)
    total_cost = sum(item['cost'] for item in overview)
    total_profit = total_revenue - total_cost

    return render_template(
        'super_admin/ai_pricing.html',
        ai_models=ai_models,
        services=services,
        overview=overview,
        total_revenue=total_revenue,
        total_cost=total_cost,
        total_profit=total_profit,
    )


# ============== AI Models ==============
@bp.route('/ai/<int:model_id>/update', methods=['POST'])
@super_admin_required
def update_ai_model(model_id):
    model = AIModel.query.get_or_404(model_id)

    try:
        model.price_per_message = float(request.form.get('price_per_message', 0))
        model.cost_per_message = float(request.form.get('cost_per_message', 0))
        model.is_active = 'is_active' in request.form
        model.quality_tier = int(request.form.get('quality_tier', 2))
        model.description = request.form.get('description', '')
        db.session.commit()
        flash(f'✅ تم تحديث {model.display_name}', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'[admin_pricing] update_ai error: {e}')
        flash('حدث خطأ في الحفظ', 'danger')

    return redirect(url_for('admin_pricing.index'))


@bp.route('/ai/<int:model_id>/toggle', methods=['POST'])
@super_admin_required
def toggle_ai_model(model_id):
    model = AIModel.query.get_or_404(model_id)
    model.is_active = not model.is_active
    db.session.commit()
    flash(f'{"✅ تم تفعيل" if model.is_active else "⏸ تم تعطيل"} {model.display_name}', 'info')
    return redirect(url_for('admin_pricing.index'))


@bp.route('/ai/<int:model_id>/set-default', methods=['POST'])
@super_admin_required
def set_default_ai(model_id):
    """تحديد النموذج الافتراضي للتجار."""
    AIModel.query.update({AIModel.is_default: False})
    model = AIModel.query.get_or_404(model_id)
    model.is_default = True
    db.session.commit()
    flash(f'✅ {model.display_name} هو النموذج الافتراضي الآن', 'success')
    return redirect(url_for('admin_pricing.index'))


# ============== Services Pricing ==============
@bp.route('/service/<int:service_id>/update', methods=['POST'])
@super_admin_required
def update_service(service_id):
    service = ServicePricing.query.get_or_404(service_id)

    try:
        service.price = float(request.form.get('price', 0))
        service.cost = float(request.form.get('cost', 0))
        service.is_active = 'is_active' in request.form
        service.description = request.form.get('description', '')
        db.session.commit()
        flash(f'✅ تم تحديث {service.display_name}', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'[admin_pricing] update_service error: {e}')
        flash('حدث خطأ في الحفظ', 'danger')

    return redirect(url_for('admin_pricing.index'))


# ============== Tenant Usage Detail ==============
@bp.route('/tenant/<int:tenant_id>/usage')
@super_admin_required
def tenant_usage(tenant_id):
    """تفاصيل استهلاك تاجر معين."""
    from app.models.tenant import Tenant
    from app.models.tenant_wallet import TenantWallet, WalletTopUp

    tenant = Tenant.query.get_or_404(tenant_id)
    summary = MessageUsage.tenant_summary(tenant_id, days=30)
    wallet = TenantWallet.get_or_create(tenant_id)
    topups = WalletTopUp.query.filter_by(tenant_id=tenant_id).order_by(WalletTopUp.created_at.desc()).limit(20).all()

    # آخر 50 استخدام
    recent = (MessageUsage.query
              .filter_by(tenant_id=tenant_id)
              .order_by(MessageUsage.created_at.desc())
              .limit(50).all())

    return render_template(
        'super_admin/tenant_usage.html',
        tenant=tenant,
        summary=summary,
        wallet=wallet,
        topups=topups,
        recent=recent,
    )


# ============== Manual Top-up (للمؤسس) ==============
@bp.route('/tenant/<int:tenant_id>/manual-topup', methods=['POST'])
@super_admin_required
def manual_topup(tenant_id):
    """شحن يدوي لمحفظة تاجر (تجريبي/هدية)."""
    from app.models.tenant_wallet import TenantWallet

    try:
        amount = float(request.form.get('amount', 0))
        if amount <= 0:
            flash('المبلغ يجب أن يكون أكبر من 0', 'danger')
            return redirect(url_for('admin_pricing.tenant_usage', tenant_id=tenant_id))

        wallet = TenantWallet.get_or_create(tenant_id)
        wallet.topup(amount, payment_ref=f'manual_by_admin_{request.form.get("notes", "")}')
        db.session.commit()
        flash(f'✅ تم شحن {amount} ر.س لمحفظة التاجر', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'[admin_pricing] manual_topup error: {e}')
        flash('حدث خطأ', 'danger')

    return redirect(url_for('admin_pricing.tenant_usage', tenant_id=tenant_id))

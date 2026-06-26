"""
app/blueprints/tenant_usage.py — عرض الاستهلاك للتاجر (/app/usage)

التاجر يشاهد:
- رصيده الحالي
- استهلاكه الشهري مفصّل (نص/AI/صور/صوت)
- اختيار النموذج (من المتاحة فقط)
- شحن المحفظة
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, current_app

from app.extensions import db
from app.decorators import tenant_required, tenant_owner_required
from app.models.message_usage import MessageUsage
from app.models.tenant_wallet import TenantWallet, WalletTopUp
from app.models.ai_model import AIModel
from app.models.bot_config import BotConfig

bp = Blueprint('tenant_usage', __name__, template_folder='../../templates/tenant')


@bp.route('/')
@tenant_required
def index():
    """صفحة الاستهلاك والرصيد."""
    tenant = g.current_tenant
    wallet = TenantWallet.get_or_create(tenant.id)
    summary = MessageUsage.tenant_summary(tenant.id, days=30)
    summary_7 = MessageUsage.tenant_summary(tenant.id, days=7)

    # عمليات الشحن الأخيرة
    topups = (WalletTopUp.query
              .filter_by(tenant_id=tenant.id)
              .order_by(WalletTopUp.created_at.desc())
              .limit(10).all())

    # النماذج المتاحة (المفعّلة فقط)
    available_models = AIModel.query.filter_by(is_active=True).order_by(AIModel.sort_order).all()

    # النموذج الافتراضي
    current_model_id = None
    default_model = AIModel.query.filter_by(is_default=True).first()
    if default_model:
        current_model_id = default_model.id

    # الإحصائيات الأساسية
    total_30 = sum(item['total_spent'] for item in summary)
    total_7 = sum(item['total_spent'] for item in summary_7)
    total_count_30 = sum(item['count'] for item in summary)

    return render_template(
        'tenant/usage.html',
        tenant=tenant,
        wallet=wallet,
        summary=summary,
        topups=topups,
        available_models=available_models,
        current_model_id=current_model_id,
        total_30=total_30,
        total_7=total_7,
        total_count_30=total_count_30,
    )


@bp.route('/topup-request', methods=['GET', 'POST'])
@tenant_owner_required
def topup_request():
    """طلب شحن المحفظة."""
    if request.method == 'GET':
        wallet = TenantWallet.get_or_create(g.current_tenant.id)
        return render_template('tenant/topup.html', wallet=wallet, tenant=g.current_tenant)

    # POST: إنشاء طلب شحن (يربط مع بوابة الدفع لاحقاً)
    try:
        amount = float(request.form.get('amount', 0))
        if amount < 10:
            flash('الحد الأدنى للشحن: 10 ر.س', 'danger')
            return redirect(url_for('tenant_usage.topup_request'))

        # إنشاء topup بحالة pending
        wallet = TenantWallet.get_or_create(g.current_tenant.id)
        topup = WalletTopUp(
            tenant_id=g.current_tenant.id,
            amount=amount,
            balance_after=float(wallet.balance),
            status='pending',
            payment_method='moyasar',  # افتراضي
        )
        db.session.add(topup)
        db.session.commit()

        # هنا يتم تحويل التاجر لصفحة الدفع — لاحقاً
        flash(f'تم إنشاء طلب شحن {amount} ر.س. سيتم إضافة الرصيد بعد الدفع.', 'info')

        # مؤقتاً: نحوّله لصفحة الاستهلاك
        return redirect(url_for('tenant_usage.index'))
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'[tenant_usage] topup_request error: {e}')
        flash('حدث خطأ', 'danger')
        return redirect(url_for('tenant_usage.index'))


@bp.route('/api/balance')
@tenant_required
def api_balance():
    """API لجلب الرصيد (للعرض في sidebar)."""
    from flask import jsonify
    wallet = TenantWallet.get_or_create(g.current_tenant.id)
    return jsonify({
        'balance': float(wallet.balance),
        'is_low': wallet.is_low,
        'can_use': wallet.can_use_service,
    })

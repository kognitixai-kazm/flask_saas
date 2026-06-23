"""
app/blueprints/admin_integrations.py — إدارة التكاملات من لوحتك (/sa/integrations/*)
أنت تدخل المفاتيح لكل تاجر — التاجر يشوف الحالة فقط.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, current_app

from app.extensions import db
from app.decorators import super_admin_required
from app.models.tenant import Tenant
from app.models.integration import Integration

bp = Blueprint('admin_integrations', __name__, template_folder='../../templates/super_admin')


@bp.route('/')
@super_admin_required
def list_all():
    """قائمة كل التكاملات لكل التجار."""
    tenants = Tenant.query.filter_by(status='active').order_by(Tenant.business_name).all()

    integrations_map = {}
    for t in tenants:
        integrations_map[t.id] = {
            'tenant': t,
            'whatsapp': Integration.query.filter_by(tenant_id=t.id, service_type='whatsapp').first(),
            'payment': Integration.query.filter_by(tenant_id=t.id, service_type='payment').first(),
            'accounting': Integration.query.filter_by(tenant_id=t.id, service_type='accounting').first(),
            'contracts': Integration.query.filter_by(tenant_id=t.id, service_type='contracts').first(),
            'srm': Integration.query.filter_by(tenant_id=t.id, service_type='srm').first(),
            'booking_com': Integration.query.filter_by(tenant_id=t.id, service_type='booking_com').first(),
        }

    return render_template('super_admin/integrations.html',
        tenants=tenants, integrations_map=integrations_map)


@bp.route('/whatsapp/<int:tenant_id>', methods=['GET', 'POST'])
@super_admin_required
def whatsapp_setup(tenant_id):
    """إعداد واتساب لتاجر معيّن."""
    tenant = Tenant.query.get_or_404(tenant_id)
    config = Integration.query.filter_by(tenant_id=tenant_id, service_type='whatsapp').first()

    if request.method == 'POST':
        phone_number = (request.form.get('phone_number') or '').strip()
        phone_number_id = (request.form.get('phone_number_id') or '').strip()
        waba_id = (request.form.get('waba_id') or '').strip()
        access_token = (request.form.get('access_token') or '').strip()
        webhook_verify_token = (request.form.get('webhook_verify_token') or '').strip()
        is_active = 'is_active' in request.form

        if phone_number_id:
            dup = Integration.query.filter(
                Integration.service_type == 'whatsapp',
                Integration.phone_number_id == phone_number_id,
                Integration.tenant_id != tenant_id,
            ).first()
            if dup:
                flash(
                    'Phone Number ID هذا مسجّل لنشاط/تاجر آخر. رقم ميتا الواحد يُربط بنشاط واحد فقط.',
                    'danger',
                )
                return redirect(url_for('admin_integrations.whatsapp_setup', tenant_id=tenant_id))

        if webhook_verify_token:
            dup_tok = Integration.query.filter(
                Integration.service_type == 'whatsapp',
                Integration.webhook_verify_token == webhook_verify_token,
                Integration.tenant_id != tenant_id,
            ).first()
            if dup_tok:
                flash(
                    'Webhook Verify Token مستخدم لنشاط آخر. اختر توكن مختلف لكل نشاط.',
                    'danger',
                )
                return redirect(url_for('admin_integrations.whatsapp_setup', tenant_id=tenant_id))

        if not config:
            config = Integration(tenant_id=tenant_id, service_type='whatsapp', provider='meta_cloud')
            db.session.add(config)

        config.phone_number = phone_number
        config.phone_number_id = phone_number_id
        config.waba_id = waba_id
        config.access_token_decrypted = access_token
        config.webhook_verify_token_decrypted = webhook_verify_token
        config.is_active = is_active

        db.session.commit()

        # التحقق من المفتاح
        if config.is_active and config.access_token:
            from app.services.whatsapp_service import WhatsAppService
            result = WhatsAppService.verify_token(tenant_id)
            if result['valid']:
                flash('✅ تم التحقق — واتساب جاهز!', 'success')
            else:
                flash(f'⚠️ تم الحفظ لكن التحقق فشل: {result["error"]}', 'warning')
        else:
            flash('تم حفظ الإعدادات', 'success')

        return redirect(url_for('admin_integrations.whatsapp_setup', tenant_id=tenant_id))

    # رابط الـ Webhook لإعطائه لـ Meta
    webhook_url = f"{request.host_url.rstrip('/')}/api/v1/webhooks/whatsapp"

    return render_template('super_admin/integration_whatsapp.html',
        tenant=tenant, config=config, webhook_url=webhook_url)


@bp.route('/payment/<int:tenant_id>', methods=['GET', 'POST'])
@super_admin_required
def payment_setup(tenant_id):
    """إعداد بوابة الدفع لتاجر."""
    tenant = Tenant.query.get_or_404(tenant_id)
    config = Integration.query.filter_by(tenant_id=tenant_id, service_type='payment').first()

    if request.method == 'POST':
        if not config:
            config = Integration(tenant_id=tenant_id, service_type='payment')
            db.session.add(config)

        config.provider = request.form.get('provider', 'moyasar')
        config.api_key_decrypted = request.form.get('api_key', '')
        config.api_secret_decrypted = request.form.get('api_secret', '')
        config.payment_mode = request.form.get('payment_mode', 'test')
        config.payment_currency = request.form.get('payment_currency', 'SAR')
        config.is_active = 'is_active' in request.form

        db.session.commit()

        if config.is_active and config.api_key:
            from app.services.payment_service import PaymentService
            result = PaymentService.verify_keys(tenant_id)
            if result['valid']:
                flash('✅ تم التحقق — بوابة الدفع جاهزة!', 'success')
            else:
                flash(f'⚠️ تم الحفظ لكن التحقق فشل: {result["error"]}', 'warning')
        else:
            flash('تم حفظ الإعدادات', 'success')

        return redirect(url_for('admin_integrations.payment_setup', tenant_id=tenant_id))

    return render_template('super_admin/integration_payment.html',
        tenant=tenant, config=config)


@bp.route('/accounting/<int:tenant_id>', methods=['GET', 'POST'])
@super_admin_required
def accounting_setup(tenant_id):
    """إعداد نظام محاسبي."""
    tenant = Tenant.query.get_or_404(tenant_id)
    config = Integration.query.filter_by(tenant_id=tenant_id, service_type='accounting').first()

    if request.method == 'POST':
        if not config:
            config = Integration(tenant_id=tenant_id, service_type='accounting')
            db.session.add(config)

        config.provider = request.form.get('provider', 'qoyod')
        config.api_key_decrypted = request.form.get('api_key', '')
        config.api_secret_decrypted = request.form.get('api_secret', '')
        config.is_active = 'is_active' in request.form
        prev = dict(config.extra_config or {})
        prev['webhook_url'] = request.form.get('webhook_url', '')
        prev['auto_send_invoice'] = 'auto_send_invoice' in request.form
        ing = (request.form.get('ingest_secret') or '').strip()
        if ing:
            prev['ingest_secret'] = ing
        config.extra_config = prev

        db.session.commit()
        flash('تم حفظ إعدادات النظام المحاسبي', 'success')
        return redirect(url_for('admin_integrations.accounting_setup', tenant_id=tenant_id))

    inbound_url = f"{(current_app.config.get('SITE_URL') or '').rstrip('/')}/api/v1/webhooks/accounting"
    return render_template(
        'super_admin/integration_accounting.html',
        tenant=tenant,
        config=config,
        inbound_accounting_url=inbound_url,
    )


@bp.route('/contracts/<int:tenant_id>', methods=['GET', 'POST'])
@super_admin_required
def contracts_setup(tenant_id):
    """إعداد العقود الإلكترونية."""
    tenant = Tenant.query.get_or_404(tenant_id)
    config = Integration.query.filter_by(tenant_id=tenant_id, service_type='contracts').first()

    if request.method == 'POST':
        if not config:
            config = Integration(tenant_id=tenant_id, service_type='contracts')
            db.session.add(config)

        config.provider = request.form.get('provider', 'custom')
        config.api_key_decrypted = request.form.get('api_key', '')
        config.is_active = 'is_active' in request.form
        config.extra_config = {
            'template_url': request.form.get('template_url', ''),
            'auto_send_whatsapp': 'auto_send_whatsapp' in request.form,
        }

        db.session.commit()
        flash('تم حفظ إعدادات العقود', 'success')
        return redirect(url_for('admin_integrations.contracts_setup', tenant_id=tenant_id))

    return render_template('super_admin/integration_contracts.html',
        tenant=tenant, config=config)


@bp.route('/test-whatsapp/<int:tenant_id>', methods=['POST'])
@super_admin_required
def test_whatsapp(tenant_id):
    """إرسال رسالة تجريبية."""
    test_phone = request.form.get('test_phone', '')
    if not test_phone:
        flash('أدخل رقم للاختبار', 'danger')
        return redirect(url_for('admin_integrations.whatsapp_setup', tenant_id=tenant_id))

    from app.services.whatsapp_service import WhatsAppService
    result = WhatsAppService.send_text(
        tenant_id, test_phone,
        '✅ رسالة تجريبية من المنصة — واتساب يعمل بنجاح!'
    )

    if result.get('success'):
        flash('✅ تم إرسال الرسالة التجريبية!', 'success')
    else:
        flash(f'❌ فشل الإرسال: {result.get("error")}', 'danger')

    return redirect(url_for('admin_integrations.whatsapp_setup', tenant_id=tenant_id))

@bp.route('/srm/<int:tenant_id>', methods=['GET', 'POST'])
@super_admin_required
def srm_setup(tenant_id):
    """إعداد نظام علاقات الموردين (SRM)."""
    tenant = Tenant.query.get_or_404(tenant_id)
    config = Integration.query.filter_by(tenant_id=tenant_id, service_type='srm').first()

    if request.method == 'POST':
        if not config:
            config = Integration(tenant_id=tenant_id, service_type='srm')
            db.session.add(config)

        config.provider = request.form.get('provider', 'custom_srm')
        config.api_key_decrypted = request.form.get('api_key', '')
        config.api_secret_decrypted = request.form.get('api_secret', '')
        config.is_active = 'is_active' in request.form
        
        # حفظ أي إعدادات إضافية
        config.extra_config = {
            'webhook_url': request.form.get('webhook_url', ''),
        }

        db.session.commit()
        flash('تم حفظ إعدادات نظام الموردين (SRM)', 'success')
        return redirect(url_for('admin_integrations.srm_setup', tenant_id=tenant_id))

    return render_template('super_admin/integration_srm.html',
        tenant=tenant, config=config)


@bp.route('/booking-com/<int:tenant_id>', methods=['GET', 'POST'])
@super_admin_required
def booking_com_setup(tenant_id):
    """إعداد الربط مع Booking.com"""
    tenant = Tenant.query.get_or_404(tenant_id)
    config = Integration.query.filter_by(tenant_id=tenant_id, service_type='booking_com').first()

    if request.method == 'POST':
        if not config:
            config = Integration(tenant_id=tenant_id, service_type='booking_com')
            db.session.add(config)

        config.provider = request.form.get('provider', 'booking_api')
        config.api_key_decrypted = request.form.get('api_key', '')
        config.api_secret_decrypted = request.form.get('api_secret', '')
        config.is_active = 'is_active' in request.form
        
        config.extra_config = {
            'hotel_id': request.form.get('hotel_id', ''),
        }

        db.session.commit()
        flash('تم حفظ إعدادات الربط مع Booking.com', 'success')
        return redirect(url_for('admin_integrations.booking_com_setup', tenant_id=tenant_id))

    return render_template('super_admin/integration_booking.html',
        tenant=tenant, config=config)


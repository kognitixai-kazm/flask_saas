"""
app/blueprints/tenant_integrations.py — تكاملات لوحة التاجر (/app/integrations).

يديرها التاجر بنفسه لخدمته فقط:
- واتساب (Meta Cloud)
- بوابة الدفع (Moyasar/Tap/Stripe)
- النظام المحاسبي (قيود/دفترة/Xero)
- العقود الإلكترونية (مخصص/DocuSign)

كل تاجر يرى تكامله فقط — ولا يطّلع على غيره.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, current_app

from app.extensions import db
from app.decorators import tenant_required, tenant_owner_required
from app.models.integration import Integration

bp = Blueprint('tenant_integrations', __name__, template_folder='../../templates/tenant')


def _get_integration(service_type: str) -> Integration | None:
    return Integration.query.filter_by(
        tenant_id=g.current_tenant.id,
        service_type=service_type,
    ).first()


# ----------------------------------------------------------------------------
# لوحة التكاملات الرئيسية
# ----------------------------------------------------------------------------
@bp.route('/')
@tenant_required
def index():
    items = {
        'whatsapp':   _get_integration('whatsapp'),
        'payment':    _get_integration('payment'),
        'accounting': _get_integration('accounting'),
        'contracts':  _get_integration('contracts'),
        'srm':        _get_integration('srm'),
        'booking_com':_get_integration('booking_com'),
    }
    return render_template('tenant/integrations/index.html', items=items)


# ----------------------------------------------------------------------------
# واتساب (Meta Cloud)
# ----------------------------------------------------------------------------
@bp.route('/whatsapp', methods=['GET', 'POST'])
@tenant_owner_required
def whatsapp():
    tenant = g.current_tenant
    config = _get_integration('whatsapp')

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
                Integration.tenant_id != tenant.id,
            ).first()
            if dup:
                flash('Phone Number ID مستخدم لنشاط آخر — يجب أن يكون فريداً.', 'danger')
                return redirect(url_for('tenant_integrations.whatsapp'))

        if webhook_verify_token:
            dup_tok = Integration.query.filter(
                Integration.service_type == 'whatsapp',
                Integration.webhook_verify_token == webhook_verify_token,
                Integration.tenant_id != tenant.id,
            ).first()
            if dup_tok:
                flash('Verify Token مستخدم لنشاط آخر — اختر توكن مختلفاً.', 'danger')
                return redirect(url_for('tenant_integrations.whatsapp'))

        if not config:
            config = Integration(tenant_id=tenant.id, service_type='whatsapp', provider='meta_cloud')
            db.session.add(config)

        config.phone_number = phone_number
        config.phone_number_id = phone_number_id
        config.waba_id = waba_id
        config.access_token = access_token
        config.webhook_verify_token = webhook_verify_token
        config.is_active = is_active

        db.session.commit()

        # تحقق من المفتاح
        if config.is_active and config.access_token:
            try:
                from app.services.whatsapp_service import WhatsAppService
                result = WhatsAppService.verify_token(tenant.id)
                if result.get('valid'):
                    flash('✅ تم التحقق — واتساب جاهز للعمل!', 'success')
                else:
                    flash(f'تم الحفظ. ملاحظة: {result.get("error", "فشل التحقق")}', 'warning')
            except Exception as e:
                current_app.logger.warning(f'[tenant_integrations] WA verify error: {e}')
                flash('تم الحفظ — تعذّر التحقق الآن، حاول لاحقاً.', 'warning')
        else:
            flash('تم حفظ الإعدادات.', 'success')

        return redirect(url_for('tenant_integrations.whatsapp'))

    webhook_url = f"{request.host_url.rstrip('/')}/api/v1/webhooks/whatsapp"
    return render_template('tenant/integrations/whatsapp.html',
                           tenant=tenant, config=config, webhook_url=webhook_url)


@bp.route('/whatsapp/test', methods=['POST'])
@tenant_owner_required
def whatsapp_test():
    test_phone = (request.form.get('test_phone') or '').strip()
    if not test_phone:
        flash('أدخل رقماً للاختبار.', 'danger')
        return redirect(url_for('tenant_integrations.whatsapp'))

    try:
        from app.services.whatsapp_service import WhatsAppService
        result = WhatsAppService.send_text(
            g.current_tenant.id, test_phone,
            '✅ رسالة تجريبية من KOGNITIX — واتساب يعمل بنجاح!'
        )
        if result.get('success'):
            flash('✅ تم إرسال الرسالة التجريبية!', 'success')
        else:
            flash(f'تعذّر الإرسال: {result.get("error", "خطأ غير معروف")}', 'danger')
    except Exception as e:
        current_app.logger.warning(f'[tenant_integrations] WA test error: {e}')
        flash('تعذّر إرسال الرسالة التجريبية الآن.', 'danger')

    return redirect(url_for('tenant_integrations.whatsapp'))


# ----------------------------------------------------------------------------
# بوابة الدفع
# ----------------------------------------------------------------------------
@bp.route('/payment', methods=['GET', 'POST'])
@tenant_owner_required
def payment():
    tenant = g.current_tenant
    config = _get_integration('payment')

    if request.method == 'POST':
        if not config:
            config = Integration(tenant_id=tenant.id, service_type='payment')
            db.session.add(config)

        config.provider = (request.form.get('provider') or 'moyasar').strip()
        config.api_key = (request.form.get('api_key') or '').strip()
        config.api_secret = (request.form.get('api_secret') or '').strip()
        config.payment_mode = (request.form.get('payment_mode') or 'test').strip()
        config.payment_currency = (request.form.get('payment_currency') or 'SAR').strip()
        config.is_active = 'is_active' in request.form
        db.session.commit()

        if config.is_active and config.api_key:
            try:
                from app.services.payment_service import PaymentService
                result = PaymentService.verify_keys(tenant.id)
                if result.get('valid'):
                    flash('✅ تم التحقق — بوابة الدفع جاهزة!', 'success')
                else:
                    flash(f'تم الحفظ. ملاحظة: {result.get("error", "فشل التحقق")}', 'warning')
            except Exception as e:
                current_app.logger.warning(f'[tenant_integrations] Pay verify error: {e}')
                flash('تم الحفظ — تعذّر التحقق الآن.', 'warning')
        else:
            flash('تم حفظ الإعدادات.', 'success')

        return redirect(url_for('tenant_integrations.payment'))

    return render_template('tenant/integrations/payment.html',
                           tenant=tenant, config=config)


# ----------------------------------------------------------------------------
# النظام المحاسبي
# ----------------------------------------------------------------------------
@bp.route('/accounting', methods=['GET', 'POST'])
@tenant_owner_required
def accounting():
    tenant = g.current_tenant
    config = _get_integration('accounting')

    if request.method == 'POST':
        if not config:
            config = Integration(tenant_id=tenant.id, service_type='accounting')
            db.session.add(config)

        config.provider = (request.form.get('provider') or 'qoyod').strip()
        config.api_key = (request.form.get('api_key') or '').strip()
        config.api_secret = (request.form.get('api_secret') or '').strip()
        config.is_active = 'is_active' in request.form

        prev = dict(config.extra_config or {})
        prev['webhook_url'] = (request.form.get('webhook_url') or '').strip()
        prev['auto_send_invoice'] = 'auto_send_invoice' in request.form
        ing = (request.form.get('ingest_secret') or '').strip()
        if ing:
            prev['ingest_secret'] = ing
        config.extra_config = prev

        db.session.commit()
        flash('تم حفظ إعدادات النظام المحاسبي.', 'success')
        return redirect(url_for('tenant_integrations.accounting'))

    inbound_url = f"{(current_app.config.get('SITE_URL') or '').rstrip('/')}/api/v1/webhooks/accounting"
    return render_template('tenant/integrations/accounting.html',
                           tenant=tenant, config=config,
                           inbound_accounting_url=inbound_url)


# ----------------------------------------------------------------------------
# العقود الإلكترونية
# ----------------------------------------------------------------------------
@bp.route('/contracts', methods=['GET', 'POST'])
@tenant_owner_required
def contracts():
    tenant = g.current_tenant
    config = _get_integration('contracts')

    if request.method == 'POST':
        if not config:
            config = Integration(tenant_id=tenant.id, service_type='contracts')
            db.session.add(config)

        config.provider = (request.form.get('provider') or 'custom').strip()
        config.api_key = (request.form.get('api_key') or '').strip()
        config.is_active = 'is_active' in request.form
        config.extra_config = {
            'template_url': (request.form.get('template_url') or '').strip(),
            'auto_send_whatsapp': 'auto_send_whatsapp' in request.form,
        }
        db.session.commit()
        flash('تم حفظ إعدادات العقود.', 'success')
        return redirect(url_for('tenant_integrations.contracts'))

    return render_template('tenant/integrations/contracts.html',
                           tenant=tenant, config=config)


# ----------------------------------------------------------------------------
# الرسائل النصية (SMS)
# ----------------------------------------------------------------------------
@bp.route('/sms', methods=['GET', 'POST'])
@tenant_owner_required
def sms_settings():
    from app.services.sms_service import SMSService
    from app.models.tenant_integrations import TenantIntegration
    
    tenant = g.current_tenant
    config = TenantIntegration.query.filter_by(tenant_id=tenant.id).first()
    
    if request.method == 'POST':
        provider_name = (request.form.get('provider_name') or '').strip()
        api_key = (request.form.get('api_key') or '').strip()
        sender_id = (request.form.get('sender_id') or '').strip()
        is_active = 'is_active' in request.form
        
        config_data = {
            'provider_name': provider_name,
            'api_key': api_key,
            'sender_id': sender_id,
            'is_active': is_active
        }
        
        SMSService.save_config(tenant.id, config_data)
        flash('تم حفظ إعدادات SMS بنجاح.', 'success')
        return redirect(url_for('tenant_integrations.sms_settings'))
        
    return render_template('tenant/integrations/sms_settings.html', tenant=tenant, config=config)

# ----------------------------------------------------------------------------
# إدارة الموردين (SRM)
# ----------------------------------------------------------------------------
@bp.route('/srm', methods=['GET', 'POST'])
@tenant_owner_required
def srm():
    tenant = g.current_tenant
    config = _get_integration('srm')

    if request.method == 'POST':
        if not config:
            config = Integration(tenant_id=tenant.id, service_type='srm')
            db.session.add(config)

        config.provider = (request.form.get('provider') or 'custom_srm').strip()
        config.api_key = (request.form.get('api_key') or '').strip()
        config.api_secret = (request.form.get('api_secret') or '').strip()
        config.is_active = 'is_active' in request.form
        
        config.extra_config = {
            'webhook_url': (request.form.get('webhook_url') or '').strip(),
        }

        db.session.commit()
        flash('تم حفظ إعدادات نظام الموردين (SRM).', 'success')
        return redirect(url_for('tenant_integrations.srm'))

    return render_template('tenant/integrations/srm.html',
                           tenant=tenant, config=config)

# ----------------------------------------------------------------------------
# Booking.com
# ----------------------------------------------------------------------------
@bp.route('/booking-com', methods=['GET', 'POST'])
@tenant_owner_required
def booking_com():
    tenant = g.current_tenant
    config = _get_integration('booking_com')

    if request.method == 'POST':
        if not config:
            config = Integration(tenant_id=tenant.id, service_type='booking_com')
            db.session.add(config)

        config.provider = (request.form.get('provider') or 'booking_api').strip()
        config.api_key = (request.form.get('api_key') or '').strip()
        config.api_secret = (request.form.get('api_secret') or '').strip()
        config.is_active = 'is_active' in request.form
        
        config.extra_config = {
            'hotel_id': (request.form.get('hotel_id') or '').strip(),
        }

        db.session.commit()
        flash('تم حفظ إعدادات الربط مع Booking.com.', 'success')
        return redirect(url_for('tenant_integrations.booking_com'))

    return render_template('tenant/integrations/booking_com.html',
                           tenant=tenant, config=config)

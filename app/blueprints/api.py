"""
app/blueprints/api.py — REST API (/api/v1)
health check + WhatsApp webhook + Payment webhook + Accounting webhook

✅ تحديثات الأمان (المرحلة 1.5):
- WhatsApp POST: التحقق من X-Hub-Signature-256
- Payment POST: التحقق من توقيع Moyasar/Tap
- Accounting POST: ingest_secret إجباري (رفض 401 لو فاضي)
- WhatsApp verify_token: تحذير عند التكرار
"""
from flask import Blueprint, jsonify, request, current_app, Response

from app.extensions import csrf, limiter
from app.models.integration import Integration
from app.utils.security import (
    verify_meta_signature,
    verify_moyasar_signature,
    verify_tap_signature,
)

bp = Blueprint('api', __name__)


@bp.route('/health')
def health_check():
    return jsonify({
        'status': 'ok',
        'service': 'saas-platform',
        'version': '2.0.0',
    })


# ========================================
# WhatsApp Webhook — مع التحقق الأمني
# ========================================
@bp.route('/webhooks/whatsapp', methods=['GET', 'POST'])
@csrf.exempt
def whatsapp_webhook():
    """Webhook لاستقبال رسائل WhatsApp من Meta."""

    if request.method == 'GET':
        # Verification challenge من Meta
        mode = request.args.get('hub.mode')
        token = request.args.get('hub.verify_token')
        challenge = request.args.get('hub.challenge')

        if mode == 'subscribe' and token:
            # البحث عن أي tenant عنده هذا الـ verify token
            vrows = []
            active_whatsapp = Integration.query.filter_by(
                service_type='whatsapp',
                is_active=True,
            ).order_by(Integration.id).all()
            
            for integ in active_whatsapp:
                if integ.webhook_verify_token_decrypted == token:
                    vrows.append(integ)

            if len(vrows) > 1:
                # ⚠️ ثغرة #6: تحذير عند التعارض
                current_app.logger.error(
                    '[SECURITY] duplicate active webhook_verify_token tenants=%s — '
                    'يجب على كل tenant استخدام verify_token فريد',
                    [r.tenant_id for r in vrows],
                )
            config = vrows[0] if vrows else None

            if config:
                current_app.logger.info(f'WhatsApp webhook verified for tenant={config.tenant_id}')
                return challenge, 200

            # fallback للـ verify token العام في .env
            general_token = current_app.config.get('WHATSAPP_VERIFY_TOKEN', '')
            if general_token and token == general_token:
                return challenge, 200

        return 'Forbidden', 403

    # ============================================================
    # POST: استقبال رسالة — ✅ التحقق من توقيع Meta أولاً (ثغرة #1)
    # ============================================================
    request_body = request.get_data()
    received_signature = request.headers.get('X-Hub-Signature-256', '')

    # محاولة العثور على App Secret من أي tenant فيه واتساب مفعّل
    # (Meta يستخدم app secret واحد لكل التطبيق، مش per-tenant)
    app_secret = current_app.config.get('WHATSAPP_APP_SECRET', '')

    # لو ما فيه app_secret في .env، نبحث عنه في إعدادات أي tenant
    if not app_secret:
        any_wa = Integration.query.filter_by(
            service_type='whatsapp', is_active=True,
        ).first()
        if any_wa and any_wa.extra_config:
            app_secret = any_wa.extra_config.get('app_secret', '')

    # في وضع التطوير فقط: نسمح بالطلبات بدون توقيع
    if app_secret:
        if not verify_meta_signature(request_body, received_signature, app_secret):
            current_app.logger.warning(
                '[SECURITY] WhatsApp webhook signature mismatch — رفض الطلب'
            )
            return jsonify({'status': 'unauthorized'}), 401
    else:
        # تحذير صارم: في الإنتاج لازم يكون مضبوط
        if not current_app.config.get('DEBUG'):
            current_app.logger.error(
                '[SECURITY] WHATSAPP_APP_SECRET غير مضبوط في الإنتاج — رفض'
            )
            return jsonify({'status': 'misconfigured'}), 503
        current_app.logger.warning(
            '[SECURITY] WhatsApp webhook بدون app_secret (وضع التطوير فقط)'
        )

    data = request.get_json(silent=True)
    if not data:
        return jsonify({'status': 'no data'}), 200

    try:
        from app.services.whatsapp_service import WhatsAppService
        WhatsAppService.process_webhook(data)
    except Exception as e:
        current_app.logger.error(f'WhatsApp webhook processing error: {e}')

    # Meta يتوقع 200 دائماً وإلا يعيد المحاولة
    return jsonify({'status': 'processed'}), 200


# ========================================
# Twilio — TwiML للاتصال الصوتي (محمي بالتوقيع)
# ========================================
@bp.route('/webhooks/twilio/voice/<int:tenant_id>', methods=['GET', 'POST'])
@csrf.exempt
def twilio_voice_webhook(tenant_id):
    """TwiML لترحيب المكالمة؛ يتحقق من توقيع Twilio."""
    from app.models.bot_config import BotConfig
    from app.services.call_integration_service import twilio_signature_valid, build_twiml_for_tenant

    bot = BotConfig.query.filter_by(tenant_id=tenant_id).first()
    if not bot or not bot.call_is_active or (bot.call_provider or '').strip().lower() != 'twilio':
        return Response(
            '<?xml version="1.0" encoding="UTF-8"?><Response><Reject/></Response>',
            mimetype='text/xml',
        )

    token = (bot.call_api_secret or '').strip()
    if not token:
        current_app.logger.error('[Twilio] Auth Token مفقود — رفض TwiML')
        return 'Forbidden', 403
    if not twilio_signature_valid(request, token):
        return 'Forbidden', 403

    xml = build_twiml_for_tenant(bot)
    return Response(xml, mimetype='text/xml')


# ========================================
# Payment Webhook — ✅ مع تحقق التوقيع (ثغرة #3)
# ========================================
@bp.route('/webhooks/payment', methods=['GET', 'POST'])
@csrf.exempt
@limiter.limit('120 per minute')
def payment_webhook():
    """Webhook لاستقبال إشعارات الدفع (Moyasar/Tap)."""
    if request.method == 'GET':
        # Redirect بعد الدفع
        payment_id = request.args.get('id')
        status = request.args.get('status')
        current_app.logger.info(f'Payment callback: id={payment_id} status={status}')

        if status == 'paid':
            return ('<html><body style="text-align:center;padding:40px;font-family:Tahoma">'
                    '<h1>✅ تم الدفع بنجاح!</h1>'
                    '<p>شكراً لك. يمكنك إغلاق هذه الصفحة.</p></body></html>')
        else:
            return ('<html><body style="text-align:center;padding:40px;font-family:Tahoma">'
                    '<h1>❌ لم يتم الدفع</h1>'
                    '<p>يرجى المحاولة مجدداً.</p></body></html>')

    # ============================================================
    # POST: ✅ التحقق من توقيع البوابة قبل أي معالجة
    # ============================================================
    request_body = request.get_data()

    # تحديد البوابة من الترويسات
    moyasar_sig = request.headers.get('X-Moyasar-Signature', '').strip()
    tap_sig = request.headers.get('X-Tap-Signature', '').strip() or request.headers.get('Hashstring', '').strip()

    tenant_id = request.args.get('tenant_id')
    try:
        tid = int(tenant_id) if tenant_id else None
    except (TypeError, ValueError):
        tid = None

    verified = False
    provider = None

    if tid:
        pay_config = Integration.query.filter_by(
            tenant_id=tid, service_type='payment', is_active=True,
        ).first()

        if pay_config:
            secret = (pay_config.api_secret or '').strip()
            cfg_provider = (pay_config.provider or '').strip().lower()

            if cfg_provider == 'moyasar' and moyasar_sig and secret:
                verified = verify_moyasar_signature(request_body, moyasar_sig, secret)
                provider = 'moyasar'
            elif cfg_provider == 'tap' and tap_sig and secret:
                verified = verify_tap_signature(request_body, tap_sig, secret)
                provider = 'tap'

    if not verified:
        current_app.logger.warning(
            '[SECURITY] Payment webhook signature mismatch tenant=%s provider=%s — رفض',
            tid, provider,
        )
        return jsonify({'status': 'unauthorized'}), 401

    data = request.get_json(silent=True) or {}
    current_app.logger.info(f'Payment webhook verified tenant={tid} provider={provider}')

    # تحديث حالة الدفع — يُمدَّد لاحقاً
    try:
        from app.services.payment_service import PaymentService
        if hasattr(PaymentService, 'handle_webhook'):
            PaymentService.handle_webhook(tid, provider, data)
    except Exception as e:
        current_app.logger.error(f'Payment processing error: {e}')

    return jsonify({'status': 'received'}), 200


# ========================================
# Accounting Webhook — ✅ ingest_secret إجباري (ثغرة #2)
# ========================================
@bp.route('/webhooks/accounting', methods=['POST'])
@csrf.exempt
def accounting_webhook():
    """Webhook لاستقبال فواتير من النظام المحاسبي."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'status': 'no data'}), 200

    tenant_id = data.get('tenant_id')
    tid = None
    try:
        if tenant_id is not None and str(tenant_id).strip() != '':
            tid = int(tenant_id)
    except (TypeError, ValueError):
        tid = None

    if not tid:
        current_app.logger.warning('[Accounting] missing tenant_id')
        return jsonify({'status': 'invalid'}), 400

    acct = Integration.query.filter_by(
        tenant_id=tid,
        service_type='accounting',
        is_active=True,
    ).first()

    if not acct:
        current_app.logger.warning('[Accounting] no active integration tenant=%s', tid)
        return jsonify({'status': 'forbidden'}), 403

    # ============================================================
    # ✅ ingest_secret إجباري — رفض الطلب لو فاضي (ثغرة #2)
    # ============================================================
    expected = (acct.extra_config or {}).get('ingest_secret', '') or ''
    expected = expected.strip()

    if not expected:
        current_app.logger.error(
            '[SECURITY] Accounting webhook without ingest_secret tenant=%s — رفض',
            tid,
        )
        return jsonify({
            'status': 'misconfigured',
            'message': 'ingest_secret غير مضبوط للنشاط',
        }), 401

    received_secret = (data.get('secret') or '').strip()
    if not received_secret:
        current_app.logger.warning('[Accounting] missing secret in payload tenant=%s', tid)
        return jsonify({'status': 'unauthorized'}), 401

    # المقارنة الآمنة
    import hmac
    if not hmac.compare_digest(received_secret, expected):
        current_app.logger.warning(
            '[SECURITY] Accounting ingest_secret mismatch tenant=%s', tid,
        )
        return jsonify({'status': 'forbidden'}), 403

    # ✅ التحقق نجح — نسجل بدون البيانات الحساسة
    current_app.logger.info(f'Accounting webhook verified tenant={tid}')

    customer_phone = data.get('customer_phone')
    invoice_url = data.get('invoice_url')
    invoice_number = data.get('invoice_number', '')
    amount = data.get('amount', 0)

    if customer_phone and invoice_url:
        try:
            from app.services.whatsapp_service import WhatsAppService
            WhatsAppService.send_invoice(
                tenant_id=tid,
                to_phone=customer_phone,
                invoice_url=invoice_url,
                invoice_number=invoice_number,
                amount=float(amount),
            )
        except Exception as e:
            current_app.logger.error(f'Invoice send error: {e}')

    return jsonify({'status': 'processed'}), 200

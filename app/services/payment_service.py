"""
app/services/payment_service.py — توليد روابط دفع.
يدعم: Moyasar + Tap Payments.
الفلوس تروح لحساب التاجر مباشرة (أنت بس تربط المفاتيح).
"""
import requests
import json
from flask import current_app

from app.extensions import db
from app.models.integration import Integration


class PaymentService:
    """توليد روابط دفع + التحقق من حالة الدفع."""

    @staticmethod
    def create_payment_link(tenant_id: int, amount: float, description: str,
                            customer_name: str = '', customer_email: str = '',
                            customer_phone: str = '', callback_url: str = '') -> dict:
        """
        توليد رابط دفع.
        يرجع: {'success': True, 'payment_url': '...', 'payment_id': '...'}
        """
        config = Integration.query.filter_by(
            tenant_id=tenant_id,
            service_type='payment',
            is_active=True,
        ).first()

        if not config:
            return {'error': 'بوابة الدفع غير مفعّلة'}

        if config.provider == 'moyasar':
            return PaymentService._moyasar_create(config, amount, description,
                                                   customer_name, customer_email, callback_url)
        elif config.provider == 'tap':
            return PaymentService._tap_create(config, amount, description,
                                              customer_name, customer_email, customer_phone, callback_url)
        elif config.provider == 'stripe':
            return PaymentService._stripe_create(config, amount, description,
                                                  customer_name, customer_email, callback_url)

        return {'error': f'مزوّد غير مدعوم: {config.provider}'}

    @staticmethod
    def _stripe_create(config, amount, description, name, email, callback_url):
        """Stripe — إنشاء Checkout Session."""
        url = 'https://api.stripe.com/v1/checkout/sessions'
        if not callback_url:
            callback_url = f"{current_app.config['SITE_URL']}/api/v1/webhooks/payment"

        currency = (config.payment_currency or 'SAR').lower()
        data = {
            'mode': 'payment',
            'success_url': callback_url + '?status=success',
            'cancel_url': callback_url + '?status=cancel',
            'line_items[0][price_data][currency]': currency,
            'line_items[0][price_data][product_data][name]': description or 'Payment',
            'line_items[0][price_data][unit_amount]': int(amount * 100),
            'line_items[0][quantity]': 1,
        }
        if email:
            data['customer_email'] = email

        from app.utils.encryption import decrypt_value
        secret = decrypt_value(config.api_secret) if config.api_secret else decrypt_value(config.api_key)
        try:
            resp = requests.post(
                url,
                data=data,
                headers={'Authorization': f'Bearer {secret}'},
                timeout=15,
            )
            payload = resp.json()
            if resp.status_code in (200, 201) and payload.get('url'):
                config.payments_count += 1
                db.session.commit()
                return {
                    'success': True,
                    'payment_url': payload.get('url'),
                    'payment_id': payload.get('id'),
                }
            return {'error': (payload.get('error') or {}).get('message') or 'خطأ في Stripe'}
        except Exception as e:
            return {'error': str(e)}

    @staticmethod
    def _moyasar_create(config, amount, description, name, email, callback_url):
        """Moyasar — إنشاء فاتورة."""
        url = 'https://api.moyasar.com/v1/invoices'
        if not callback_url:
            callback_url = f"{current_app.config['SITE_URL']}/api/v1/webhooks/payment"

        payload = {
            'amount': int(amount * 100),  # بالهللة
            'currency': config.payment_currency or 'SAR',
            'description': description,
            'callback_url': callback_url,
        }

        from app.utils.encryption import decrypt_value
        api_key = decrypt_value(config.api_key)
        try:
            resp = requests.post(url, json=payload, auth=(api_key, ''), timeout=15)
            data = resp.json()

            if resp.status_code in (200, 201):
                config.payments_count += 1
                db.session.commit()
                return {
                    'success': True,
                    'payment_url': data.get('url'),
                    'payment_id': data.get('id'),
                }
            return {'error': data.get('message', 'خطأ في Moyasar')}
        except Exception as e:
            return {'error': str(e)}

    @staticmethod
    def _tap_create(config, amount, description, name, email, phone, callback_url):
        """Tap Payments — إنشاء charge."""
        url = 'https://api.tap.company/v2/charges'
        if not callback_url:
            callback_url = f"{current_app.config['SITE_URL']}/api/v1/webhooks/payment"

        from app.utils.encryption import decrypt_value
        api_key = decrypt_value(config.api_key)
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        }
        payload = {
            'amount': amount,
            'currency': config.payment_currency or 'SAR',
            'description': description,
            'customer': {
                'first_name': name or 'عميل',
                'email': email or '',
                'phone': {'country_code': '966', 'number': phone or ''},
            },
            'source': {'id': 'src_all'},
            'redirect': {'url': callback_url},
        }

        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=15)
            data = resp.json()

            if resp.status_code in (200, 201):
                config.payments_count += 1
                db.session.commit()
                tx_url = data.get('transaction', {}).get('url', '')
                return {
                    'success': True,
                    'payment_url': tx_url,
                    'payment_id': data.get('id'),
                }
            return {'error': data.get('message', 'خطأ في Tap')}
        except Exception as e:
            return {'error': str(e)}

    @staticmethod
    def handle_webhook(tenant_id: int, provider: str, data: dict) -> None:
        """يستقبل إشعار دفع موَثَّق ويُحدِّث العقد المرتبط (إن وُجد)."""
        from datetime import datetime
        from app.models.contract import Contract

        if not isinstance(data, dict):
            return

        # استخراج payment_id والحالة (Moyasar: id+status, Tap: id+status)
        payload = data.get('data') if isinstance(data.get('data'), dict) else data
        payment_id = (
            payload.get('id')
            or payload.get('payment_id')
            or payload.get('charge_id')
            or ''
        )
        status = (payload.get('status') or '').lower()

        if not payment_id or not tenant_id:
            return

        contract = Contract.query.filter_by(
            tenant_id=tenant_id, payment_reference=str(payment_id),
        ).first()
        if not contract:
            return

        paid_states = {'paid', 'captured', 'authorized', 'succeeded'}
        if status not in paid_states:
            current_app.logger.info(
                f'[Payment] webhook tenant={tenant_id} status={status} contract={contract.id}'
            )
            return

        if contract.status in ('paid', 'signed', 'sent'):
            return  # idempotent

        contract.payment_status = 'paid'
        contract.payment_paid = contract.payment_amount
        contract.paid_at = datetime.utcnow()
        contract.status = 'paid'

        # تحديث حالة الوحدة إلى محجوزة إذا كان العقد مرتبطاً بوحدة
        if contract.unit_id:
            from app.models.hotel_models import Unit
            unit = Unit.query.get(contract.unit_id)
            if unit:
                unit.status = 'booked'
                unit.is_available = False

        try:
            from app.services.contract_service import ContractService
            gen = ContractService.generate_contract(contract)
            if gen.get('success'):
                ContractService.send_to_customer(contract)
        except Exception as e:
            current_app.logger.exception(f'[Payment] contract generation failed: {e}')

        db.session.commit()

    @staticmethod
    def verify_keys(tenant_id: int) -> dict:
        """التحقق من صلاحية مفاتيح الدفع."""
        config = Integration.query.filter_by(
            tenant_id=tenant_id,
            service_type='payment',
            is_active=True,
        ).first()

        if not config:
            return {'valid': False, 'error': 'غير مفعّل'}

        try:
            from app.utils.encryption import decrypt_value
            api_key = decrypt_value(config.api_key) if config.api_key else ''
            api_secret = decrypt_value(config.api_secret) if config.api_secret else ''
            
            if config.provider == 'moyasar':
                resp = requests.get('https://api.moyasar.com/v1/invoices?page=1',
                                    auth=(api_key, ''), timeout=10)
            elif config.provider == 'tap':
                resp = requests.get('https://api.tap.company/v2/charges?limit=1',
                                    headers={'Authorization': f'Bearer {api_key}'}, timeout=10)
            elif config.provider == 'stripe':
                resp = requests.get('https://api.stripe.com/v1/balance',
                                    headers={'Authorization': f'Bearer {api_secret or api_key}'},
                                    timeout=10)
            else:
                return {'valid': False, 'error': 'مزوّد غير مدعوم'}

            if resp.status_code == 200:
                config.is_verified = True
                config.last_error = ''
                db.session.commit()
                return {'valid': True}
            else:
                config.is_verified = False
                config.last_error = f'HTTP {resp.status_code}'
                db.session.commit()
                return {'valid': False, 'error': f'HTTP {resp.status_code}'}
        except Exception as e:
            return {'valid': False, 'error': str(e)}

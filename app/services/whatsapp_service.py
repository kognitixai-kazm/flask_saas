"""
app/services/whatsapp_service.py — خدمة واتساب كاملة.

تدعم:
- إرسال نص
- إرسال صور
- إرسال مستندات (PDF)
- إرسال صوت
- استقبال رسائل (Webhook)
- الرد التلقائي عبر intent_engine (قابل للإيقاف من لوحة التاجر عبر BotConfig)
"""
from datetime import datetime

import requests
from flask import current_app

from app.extensions import db
from app.models.integration import Integration
from app.models.tenant import Tenant
from app.models.conversation import Conversation, Message
from app.models.bot_config import BotConfig


GRAPH_API = 'https://graph.facebook.com/v21.0'


class WhatsAppService:
    """خدمة واتساب عبر Meta Cloud API."""

    # ========================================
    # إرسال رسائل
    # ========================================
    @staticmethod
    def _record_usage(tenant_id: int, kind: str, conversation_id: int = None):
        """يسجّل رسالة WhatsApp مرسَلة في MessageUsage + يخصم السعر من رصيد التاجر."""
        try:
            from app.models.message_usage import MessageUsage
            from app.models.service_pricing import ServicePricing
            from app.models.tenant import Tenant

            price_row = ServicePricing.query.filter_by(service_key='whatsapp_message').first()
            price = float(price_row.price_charged) if price_row else 0.0
            cost = float(price_row.cost_actual) if price_row else 0.0

            tenant = Tenant.query.get(tenant_id)
            if tenant and tenant.subscription:
                if (tenant.subscription.balance or 0) >= price:
                    tenant.subscription.balance = float(tenant.subscription.balance or 0) - price

            MessageUsage.record(
                tenant_id=tenant_id,
                service_type='whatsapp_message',
                price=price,
                cost=cost,
                conversation_id=conversation_id,
                extra={'kind': kind},
            )
        except Exception as e:
            current_app.logger.warning(f'[WA] usage record failed: {e}')

    @staticmethod
    def send_text(tenant_id: int, to_phone: str, text: str, conversation_id: int = None) -> dict:
        """إرسال رسالة نصية."""
        config = WhatsAppService._get_config(tenant_id)
        if not config:
            return {'error': 'واتساب غير مفعّل لهذا النشاط'}

        url = f"{GRAPH_API}/{config.phone_number_id}/messages"
        headers = {
            'Authorization': f'Bearer {config.access_token}',
            'Content-Type': 'application/json',
        }
        payload = {
            'messaging_product': 'whatsapp',
            'to': WhatsAppService._clean_phone(to_phone),
            'type': 'text',
            'text': {'body': text},
        }

        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=15)
            result = resp.json()

            if resp.status_code == 200:
                config.messages_sent += 1
                WhatsAppService._record_usage(tenant_id, 'text', conversation_id)
                db.session.commit()
                return {'success': True, 'message_id': result.get('messages', [{}])[0].get('id')}
            else:
                error = result.get('error', {}).get('message', str(result))
                config.last_error = error
                db.session.commit()
                current_app.logger.error(f'WhatsApp send error: {error}')
                return {'error': error}
        except Exception as e:
            current_app.logger.error(f'WhatsApp send exception: {e}')
            return {'error': str(e)}

    @staticmethod
    def send_image(tenant_id: int, to_phone: str, image_url: str, caption: str = '') -> dict:
        """إرسال صورة."""
        config = WhatsAppService._get_config(tenant_id)
        if not config:
            return {'error': 'واتساب غير مفعّل'}

        url = f"{GRAPH_API}/{config.phone_number_id}/messages"
        headers = {
            'Authorization': f'Bearer {config.access_token}',
            'Content-Type': 'application/json',
        }
        payload = {
            'messaging_product': 'whatsapp',
            'to': WhatsAppService._clean_phone(to_phone),
            'type': 'image',
            'image': {'link': image_url},
        }
        if caption:
            payload['image']['caption'] = caption

        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=15)
            if resp.status_code == 200:
                config.messages_sent += 1
                WhatsAppService._record_usage(tenant_id, 'image')
                db.session.commit()
                return {'success': True}
            return {'error': resp.json().get('error', {}).get('message', 'فشل الإرسال')}
        except Exception as e:
            return {'error': str(e)}

    @staticmethod
    def send_document(tenant_id: int, to_phone: str, doc_url: str,
                      filename: str = 'document.pdf', caption: str = '') -> dict:
        """إرسال مستند (PDF, فاتورة, عقد)."""
        config = WhatsAppService._get_config(tenant_id)
        if not config:
            return {'error': 'واتساب غير مفعّل'}

        url = f"{GRAPH_API}/{config.phone_number_id}/messages"
        headers = {
            'Authorization': f'Bearer {config.access_token}',
            'Content-Type': 'application/json',
        }
        payload = {
            'messaging_product': 'whatsapp',
            'to': WhatsAppService._clean_phone(to_phone),
            'type': 'document',
            'document': {
                'link': doc_url,
                'filename': filename,
            },
        }
        if caption:
            payload['document']['caption'] = caption

        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=15)
            if resp.status_code == 200:
                config.messages_sent += 1
                WhatsAppService._record_usage(tenant_id, 'document')
                db.session.commit()
                return {'success': True}
            return {'error': resp.json().get('error', {}).get('message', 'فشل الإرسال')}
        except Exception as e:
            return {'error': str(e)}

    @staticmethod
    def send_audio(tenant_id: int, to_phone: str, audio_url: str) -> dict:
        """إرسال رسالة صوتية."""
        config = WhatsAppService._get_config(tenant_id)
        if not config:
            return {'error': 'واتساب غير مفعّل'}

        url = f"{GRAPH_API}/{config.phone_number_id}/messages"
        headers = {
            'Authorization': f'Bearer {config.access_token}',
            'Content-Type': 'application/json',
        }
        payload = {
            'messaging_product': 'whatsapp',
            'to': WhatsAppService._clean_phone(to_phone),
            'type': 'audio',
            'audio': {'link': audio_url},
        }

        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=15)
            if resp.status_code == 200:
                config.messages_sent += 1
                WhatsAppService._record_usage(tenant_id, 'audio')
                db.session.commit()
                return {'success': True}
            return {'error': resp.json().get('error', {}).get('message', 'فشل الإرسال')}
        except Exception as e:
            return {'error': str(e)}

    @staticmethod
    def send_payment_link(tenant_id: int, to_phone: str, amount: float,
                          description: str, payment_url: str) -> dict:
        """إرسال رابط دفع عبر واتساب."""
        text = (
            f"💳 فاتورة من {{business_name}}\n\n"
            f"المبلغ: {amount} ريال\n"
            f"الوصف: {description}\n\n"
            f"اضغط للدفع 👇\n{payment_url}"
        )
        tenant = Tenant.query.get(tenant_id)
        if tenant:
            text = text.replace('{business_name}', tenant.business_name)

        return WhatsAppService.send_text(tenant_id, to_phone, text)

    @staticmethod
    def send_invoice(tenant_id: int, to_phone: str, invoice_url: str,
                     invoice_number: str, amount: float) -> dict:
        """إرسال فاتورة PDF عبر واتساب."""
        tenant = Tenant.query.get(tenant_id)
        name = tenant.business_name if tenant else ''

        # إرسال نص أولاً
        WhatsAppService.send_text(
            tenant_id, to_phone,
            f"🧾 فاتورتك من {name}\n"
            f"رقم الفاتورة: #{invoice_number}\n"
            f"المبلغ: {amount} ريال\n"
            f"الفاتورة مرفقة 👇"
        )

        # ثم إرسال الـ PDF
        return WhatsAppService.send_document(
            tenant_id, to_phone,
            doc_url=invoice_url,
            filename=f'invoice_{invoice_number}.pdf',
            caption=f'فاتورة #{invoice_number} — {amount} ريال'
        )

    @staticmethod
    def send_contract(tenant_id: int, to_phone: str, contract_url: str,
                      contract_title: str) -> dict:
        """إرسال عقد إلكتروني عبر واتساب."""
        tenant = Tenant.query.get(tenant_id)
        name = tenant.business_name if tenant else ''

        WhatsAppService.send_text(
            tenant_id, to_phone,
            f"📄 عقد إلكتروني من {name}\n\n"
            f"العنوان: {contract_title}\n\n"
            f"يرجى مراجعة العقد المرفق والتوقيع 👇"
        )

        return WhatsAppService.send_document(
            tenant_id, to_phone,
            doc_url=contract_url,
            filename=f'contract.pdf',
            caption=f'عقد — {contract_title}'
        )

    # ========================================
    # استقبال الرسائل (Webhook)
    # ========================================
    @staticmethod
    def process_webhook(data: dict):
        """
        معالجة Webhook من Meta.
        يُستدعى من api.py عند استقبال POST على /api/v1/webhooks/whatsapp.
        """
        try:
            entries = data.get('entry', [])
            for entry in entries:
                changes = entry.get('changes', [])
                for change in changes:
                    value = change.get('value', {})
                    messages = value.get('messages', [])
                    metadata = value.get('metadata', {})
                    phone_number_id = metadata.get('phone_number_id', '')
                    value_contacts = value.get('contacts') or []

                    for msg in messages:
                        WhatsAppService._handle_incoming_message(
                            phone_number_id=phone_number_id,
                            msg=msg,
                            value_contacts=value_contacts,
                        )
        except Exception as e:
            current_app.logger.error(f'WhatsApp webhook error: {e}')

    @staticmethod
    def _wa_profile_name(msg: dict, value_contacts) -> str:
        for block in (msg.get('contacts') or [], value_contacts or ()):
            if not block:
                continue
            first = block[0] if isinstance(block, list) else None
            if not isinstance(first, dict):
                continue
            profile = first.get('profile') or {}
            name = (profile.get('name') or '').strip()
            if name:
                return name
        return ''

    @staticmethod
    def _handle_incoming_message(phone_number_id: str, msg: dict,
                                  value_contacts=None):
        """معالجة رسالة واردة واحدة."""
        from app.services.chat_service import ChatService

        # تحديد أي tenant مرتبط بهذا الرقم (ترتيب ثابت؛ تسجيل تحذير إن وُجد تكرار قديم)
        rows = (
            Integration.query.filter_by(
                service_type='whatsapp',
                phone_number_id=phone_number_id,
                is_active=True,
            )
            .order_by(Integration.id)
            .all()
        )
        if len(rows) > 1:
            current_app.logger.error(
                '[WhatsApp] duplicate active phone_number_id=%s tenants=%s — fix in admin',
                phone_number_id,
                [r.tenant_id for r in rows],
            )
        config = rows[0] if rows else None

        if not config:
            current_app.logger.warning(f'No tenant for phone_id: {phone_number_id}')
            return

        tenant = Tenant.query.get(config.tenant_id)
        if not tenant or tenant.status != 'active':
            return

        # بيانات الرسالة
        sender_phone = msg.get('from', '')
        msg_type = msg.get('type', 'text')
        msg_id = msg.get('id', '')

        # استخراج النص (نص مباشر أو تحليل صوت/صورة عبر BotConfig + Graph)
        try:
            from app.services.bot_media_service import enrich_whatsapp_incoming_text

            text = enrich_whatsapp_incoming_text(
                tenant.id,
                msg_type,
                msg,
                config.access_token or '',
            )
        except Exception as e:
            current_app.logger.warning('[WhatsApp] media enrich fallback: %s', e)
            text = ''
            if msg_type == 'text':
                text = msg.get('text', {}).get('body', '')
            elif msg_type == 'image':
                text = msg.get('image', {}).get('caption', '') or 'أرسل صورة'
            elif msg_type == 'document':
                text = msg.get('document', {}).get('caption', '') or 'أرسل مستند'
            elif msg_type == 'audio':
                text = 'أرسل رسالة صوتية'
            elif msg_type == 'location':
                text = 'أرسل موقع'
            else:
                text = f'رسالة ({msg_type})'

        if not text:
            return

        # إيجاد/إنشاء محادثة
        conversation = Conversation.query.filter_by(
            tenant_id=tenant.id,
            visitor_id=f'wa_{sender_phone}',
        ).order_by(Conversation.started_at.desc()).first()

        wa_name = WhatsAppService._wa_profile_name(msg, value_contacts)

        if not conversation:
            conversation = Conversation(
                tenant_id=tenant.id,
                visitor_id=f'wa_{sender_phone}',
                visitor_name=wa_name,
                visitor_phone=sender_phone,
                channel='whatsapp',
            )
            db.session.add(conversation)
            db.session.flush()
        elif wa_name:
            conversation.visitor_name = wa_name

        # حفظ رسالة الزائر
        db.session.add(Message(
            conversation_id=conversation.id,
            tenant_id=tenant.id,
            sender_type='visitor',
            content=text,
            extra_data={'wa_msg_id': msg_id, 'type': msg_type},
        ))
        db.session.flush()

        # تحديث عدّاد
        config.messages_received += 1

        # إيقاف الرد التلقائي من لوحة التاجر (يُحفظ السطر الوارد فقط)
        bot_cfg = BotConfig.query.filter_by(tenant_id=tenant.id).first()
        if bot_cfg is not None and bot_cfg.whatsapp_auto_reply_enabled is False:
            conversation.updated_at = datetime.utcnow()
            db.session.commit()
            current_app.logger.info(
                f'[WhatsApp] auto-reply off tenant={tenant.slug} from={sender_phone}'
            )
            return

        # توليد الرد (نفس intent engine الشات)
        reply_text = ChatService.generate_reply(tenant, conversation, text)

        # في الواتساب نُرسل كل فقاعة كرسالة مستقلة لاحقاً
        from app.services.chat_service import REPLY_SPLIT
        if reply_text and REPLY_SPLIT in reply_text:
            wa_parts = [p for p in reply_text.split(REPLY_SPLIT) if p and p.strip()]
            primary_for_delivery = wa_parts[0] if wa_parts else ''
            extra_for_delivery = wa_parts[1:]
        else:
            primary_for_delivery = reply_text or ''
            extra_for_delivery = []

        from app.services.unit_images_helper import prepare_bot_reply_delivery

        delivery = prepare_bot_reply_delivery(tenant.id, primary_for_delivery, conversation)

        # حفظ رد البوت (الرسالة الأساسية + كل فقاعة إضافية تُحفظ كرسالة مستقلة)
        db.session.add(Message(
            conversation_id=conversation.id,
            tenant_id=tenant.id,
            sender_type='bot',
            content=delivery['text'],
            extra_data=delivery.get('extra_data') or {},
        ))
        for extra in extra_for_delivery:
            ttx = (extra or '').strip()
            if ttx:
                db.session.add(Message(
                    conversation_id=conversation.id,
                    tenant_id=tenant.id,
                    sender_type='bot',
                    content=ttx,
                    extra_data={'is_followup': True},
                ))

        # تحديث استهلاك الاشتراك
        try:
            if tenant.subscription:
                tenant.subscription.increment_chat_usage(1)
        except Exception:
            pass

        db.session.commit()

        # إرسال النص أولاً ثم الصور (روابط عامة لميتا) ثم الفقاعات الإضافية
        out_text = (delivery.get('text') or '').strip()
        if out_text:
            WhatsAppService.send_text(tenant.id, sender_phone, delivery['text'])
        if delivery.get('images'):
            WhatsAppService._send_unit_image_urls(
                tenant.id, sender_phone, delivery['images']
            )
        for extra in extra_for_delivery:
            ttx = (extra or '').strip()
            if ttx:
                WhatsAppService.send_text(tenant.id, sender_phone, ttx)

        current_app.logger.info(
            f'[WhatsApp] {sender_phone} → tenant={tenant.slug}: "{text[:50]}" → replied'
        )

    @staticmethod
    def _send_unit_image_urls(tenant_id: int, to_phone: str, image_urls: list):
        """إرسال صور الوحدات بعد النص (روابط مطلقة يجلبها Graph API)."""
        try:
            for url in image_urls:
                if not url:
                    continue
                WhatsAppService.send_image(tenant_id, to_phone, url, caption='')
        except Exception as e:
            current_app.logger.warning(f'Send unit images error: {e}')

    # ========================================
    # أدوات
    # ========================================
    @staticmethod
    def _get_config(tenant_id: int) -> Integration:
        """جلب إعدادات واتساب لـ tenant معيّن."""
        return Integration.query.filter_by(
            tenant_id=tenant_id,
            service_type='whatsapp',
            is_active=True,
        ).first()

    @staticmethod
    def _clean_phone(phone: str) -> str:
        """تنظيف رقم الهاتف."""
        phone = phone.replace('+', '').replace(' ', '').replace('-', '')
        if phone.startswith('0'):
            phone = '966' + phone[1:]
        return phone

    @staticmethod
    def verify_token(tenant_id: int) -> dict:
        """التحقق من صلاحية الـ token."""
        config = WhatsAppService._get_config(tenant_id)
        if not config:
            return {'valid': False, 'error': 'لا يوجد إعدادات'}

        url = f"{GRAPH_API}/{config.phone_number_id}"
        headers = {'Authorization': f'Bearer {config.access_token}'}

        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                config.is_verified = True
                config.last_error = ''
                db.session.commit()
                return {'valid': True, 'data': resp.json()}
            else:
                error = resp.json().get('error', {}).get('message', 'خطأ غير معروف')
                config.is_verified = False
                config.last_error = error
                db.session.commit()
                return {'valid': False, 'error': error}
        except Exception as e:
            return {'valid': False, 'error': str(e)}

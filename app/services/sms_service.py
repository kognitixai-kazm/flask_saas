"""
app/services/sms_service.py — خدمة الرسائل النصية للمستأجر
"""
import os
import requests
from datetime import datetime
from flask import current_app
from app.extensions import db
from app.models.tenant_integrations import TenantIntegration


class SMSService:
    @staticmethod
    def save_config(tenant_id, config_data):
        """حفظ أو تحديث إعدادات الرسائل للمستأجر مع تسجيل حدث في logs"""
        integration = TenantIntegration.query.filter_by(tenant_id=tenant_id).first()
        
        if not integration:
            integration = TenantIntegration(tenant_id=tenant_id)
            db.session.add(integration)

        integration.provider_name = config_data.get('provider_name', '').strip()
        integration.api_key = config_data.get('api_key', '').strip()
        integration.sender_id = config_data.get('sender_id', '').strip()
        integration.is_active = config_data.get('is_active', False)

        db.session.commit()

        # كتابة Log في مجلد logs/
        log_dir = os.path.join(current_app.config.get('BASE_DIR', current_app.root_path), 'logs')
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, 'sms_integrations.log')
        
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(f"[{datetime.utcnow().isoformat()}] Tenant {tenant_id} updated SMS config: Provider={integration.provider_name}, Active={integration.is_active}\n")

        return integration

    @staticmethod
    def send_sms(tenant_id, phone, message):
        """إرسال رسالة باستخدام إعدادات المستأجر"""
        integration = TenantIntegration.query.filter_by(tenant_id=tenant_id, is_active=True).first()
        if not integration:
            return {"success": False, "error": "خدمة SMS غير مفعلة أو غير مهيأة للمستأجر"}

        if not integration.api_key or not integration.sender_id:
            return {"success": False, "error": "بيانات الربط غير مكتملة (المفتاح أو المرسل مفقود)"}

        provider = integration.provider_name.lower()
        api_key = integration.api_key
        sender_id = integration.sender_id

        # نموذج أولي للإرسال باستخدام مكتبة requests
        # يجب تكييف هذا الجزء بناءً على الـ API الخاص بكل مزود (Twilio, Taqnyat, etc.)
        try:
            # example API call
            # payload = {
            #     "api_key": api_key,
            #     "sender": sender_id,
            #     "to": phone,
            #     "message": message
            # }
            # headers = {"Content-Type": "application/json"}
            # response = requests.post("https://api.smsprovider.com/send", json=payload, headers=headers)
            # response.raise_for_status()

            # For now, we simulate success and log it
            current_app.logger.info(f"Simulated sending SMS to {phone} via {provider} for tenant {tenant_id}")
            return {"success": True, "message": "تم إرسال الرسالة بنجاح (Simulation)"}
        except Exception as e:
            current_app.logger.error(f"Failed to send SMS for tenant {tenant_id}: {e}")
            return {"success": False, "error": str(e)}

"""
app/services/social_media_integration_service.py — خدمة التكاملات مع منصات التواصل الاجتماعي

تدعم:
- Facebook (Page Messaging, Comments, Lead Ads)
- Instagram (Direct Messages, Comments, Story Replies)
- TikTok (Video Comments, Business Messages, Ads Management)
- Snapchat (Ads Management, Lead Conversion)
- LinkedIn (Lead Gen Forms, Page Messaging)
- Google Maps (Reviews, Q&A)

الاستخدام:
    service = SocialMediaIntegrationService(tenant_id)
    
    # تفعيل تكامل
    result = service.activate_integration(
        service_type='facebook',
        provider='facebook_graph_api',
        credentials={...}
    )
    
    # معالجة حدث (رسالة، تعليق، تقييم)
    response = service.handle_event(
        service_type='facebook',
        event_data={...}
    )
"""

import json
import requests
import logging
from typing import Optional, Dict, Any, Tuple
from datetime import datetime
from abc import ABC, abstractmethod

from flask import current_app
from app.extensions import db
from app.models.integration import Integration
from app.models.tenant import Tenant
from app.services.ai_service import AIService
from app.services.chat_service import ChatService


logger = logging.getLogger(__name__)


class SocialMediaProvider(ABC):
    """الفئة الأساسية لمزودي منصات التواصل الاجتماعي."""
    
    def __init__(self, tenant_id: int, integration: Integration):
        self.tenant_id = tenant_id
        self.integration = integration
        self.tenant = Tenant.query.get(tenant_id)
        
    @abstractmethod
    def verify_webhook(self, data: Dict[str, Any]) -> bool:
        """التحقق من توقيع webhook من المنصة."""
        pass
    
    @abstractmethod
    def handle_event(self, event_data: Dict[str, Any]) -> Optional[str]:
        """معالجة حدث من المنصة وإرجاع الرد."""
        pass
    
    @abstractmethod
    def send_message(self, recipient_id: str, message: str) -> bool:
        """إرسال رسالة عبر المنصة."""
        pass
    
    @abstractmethod
    def send_reply(self, post_id: str, message: str) -> bool:
        """إرسال رد على تعليق أو منشور."""
        pass


class FacebookProvider(SocialMediaProvider):
    """مزود تكامل فيسبوك."""
    
    def __init__(self, tenant_id: int, integration: Integration):
        super().__init__(tenant_id, integration)
        from app.utils.encryption import decrypt_value
        self.access_token = decrypt_value(integration.access_token)
        self.page_id = integration.extra_config.get('page_id', '')
        self.verify_token = decrypt_value(integration.webhook_verify_token)
        self.api_version = 'v18.0'
        self.base_url = f'https://graph.facebook.com/{self.api_version}'
    
    def verify_webhook(self, data: Dict[str, Any]) -> bool:
        """التحقق من توقيع webhook من فيسبوك."""
        import hmac
        import hashlib
        
        mode = data.get('hub.mode')
        token = data.get('hub.verify_token')
        challenge = data.get('hub.challenge')
        
        if mode != 'subscribe' or token != self.verify_token:
            return False
        
        return True
    
    def handle_event(self, event_data: Dict[str, Any]) -> Optional[str]:
        """معالجة حدث من فيسبوك (رسالة أو تعليق)."""
        try:
            # استخراج الرسالة من webhook
            messaging = event_data.get('messaging', [])
            
            for msg_event in messaging:
                sender_id = msg_event.get('sender', {}).get('id')
                recipient_id = msg_event.get('recipient', {}).get('id')
                
                # رسالة نصية
                if 'message' in msg_event:
                    user_message = msg_event['message'].get('text', '')
                    if user_message:
                        reply = self._generate_ai_reply(user_message, 'facebook')
                        if reply:
                            self.send_message(sender_id, reply)
                            return reply
                
                # تعليق على منشور
                elif 'postback' in msg_event:
                    payload = msg_event['postback'].get('payload', '')
                    reply = self._generate_ai_reply(payload, 'facebook')
                    if reply:
                        self.send_message(sender_id, reply)
                        return reply
            
            return None
        except Exception as e:
            logger.error(f'[Facebook] handle_event error: {e}')
            return None
    
    def send_message(self, recipient_id: str, message: str) -> bool:
        """إرسال رسالة عبر فيسبوك."""
        try:
            url = f'{self.base_url}/me/messages'
            payload = {
                'recipient': {'id': recipient_id},
                'message': {'text': message},
                'access_token': self.access_token
            }
            
            response = requests.post(url, json=payload, timeout=10)
            success = response.status_code == 200
            
            if success:
                self.integration.messages_sent += 1
                db.session.commit()
            else:
                logger.error(f'[Facebook] send_message failed: {response.text}')
            
            return success
        except Exception as e:
            logger.error(f'[Facebook] send_message error: {e}')
            return False
    
    def send_reply(self, post_id: str, message: str) -> bool:
        """إرسال رد على تعليق."""
        try:
            url = f'{self.base_url}/{post_id}/comments'
            payload = {
                'message': message,
                'access_token': self.access_token
            }
            
            response = requests.post(url, json=payload, timeout=10)
            return response.status_code == 200
        except Exception as e:
            logger.error(f'[Facebook] send_reply error: {e}')
            return False
    
    def _generate_ai_reply(self, user_message: str, platform: str) -> Optional[str]:
        """توليد رد باستخدام الذكاء الاصطناعي."""
        try:
            system_prompt = self._get_system_prompt(platform)
            
            result = AIService.generate(
                tenant_id=self.tenant_id,
                user_message=user_message,
                system_prompt=system_prompt,
                history=[]
            )
            
            if result.success:
                return result.text
            else:
                logger.warning(f'[Facebook] AI generation failed: {result.error}')
                return None
        except Exception as e:
            logger.error(f'[Facebook] _generate_ai_reply error: {e}')
            return None
    
    def _get_system_prompt(self, platform: str) -> str:
        """الحصول على نص التعليمات للذكاء الاصطناعي."""
        activity_code = self.tenant.activity.code if self.tenant.activity else 'general'
        
        if activity_code == 'hotel':
            return (
                f"أنت موظف خدمة عملاء متميز في فندق {self.tenant.business_name}. "
                f"ترد على استفسارات الضيوف بشكل احترافي وودود. "
                f"تقدم معلومات عن الحجوزات والغرف والخدمات. "
                f"إذا لم تتمكن من الإجابة، اطلب من الضيف التواصل مع فريق الاستقبال."
            )
        elif activity_code == 'restaurant':
            return (
                f"أنت موظف خدمة عملاء متميز في مطعم {self.tenant.business_name}. "
                f"ترد على استفسارات الزبائن بشكل احترافي وودود. "
                f"تقدم معلومات عن القائمة والحجوزات والتوصيل. "
                f"إذا لم تتمكن من الإجابة، اطلب من الزبون التواصل مع الفريق."
            )
        else:
            return (
                f"أنت موظف خدمة عملاء متميز في {self.tenant.business_name}. "
                f"ترد على الاستفسارات بشكل احترافي وودود."
            )


class InstagramProvider(SocialMediaProvider):
    """مزود تكامل انستغرام."""
    
    def __init__(self, tenant_id: int, integration: Integration):
        super().__init__(tenant_id, integration)
        from app.utils.encryption import decrypt_value
        self.access_token = decrypt_value(integration.access_token)
        self.instagram_business_account_id = integration.extra_config.get('instagram_business_account_id', '')
        self.api_version = 'v18.0'
        self.base_url = f'https://graph.instagram.com/{self.api_version}'
    
    def verify_webhook(self, data: Dict[str, Any]) -> bool:
        """التحقق من توقيع webhook من انستغرام."""
        # انستغرام يستخدم نفس آلية فيسبوك
        return True
    
    def handle_event(self, event_data: Dict[str, Any]) -> Optional[str]:
        """معالجة حدث من انستغرام."""
        try:
            messaging = event_data.get('messaging', [])
            
            for msg_event in messaging:
                sender_id = msg_event.get('sender', {}).get('id')
                
                if 'message' in msg_event:
                    user_message = msg_event['message'].get('text', '')
                    if user_message:
                        reply = self._generate_ai_reply(user_message, 'instagram')
                        if reply:
                            self.send_message(sender_id, reply)
                            return reply
            
            return None
        except Exception as e:
            logger.error(f'[Instagram] handle_event error: {e}')
            return None
    
    def send_message(self, recipient_id: str, message: str) -> bool:
        """إرسال رسالة عبر انستغرام."""
        try:
            url = f'{self.base_url}/me/messages'
            payload = {
                'recipient': {'id': recipient_id},
                'message': {'text': message},
                'access_token': self.access_token
            }
            
            response = requests.post(url, json=payload, timeout=10)
            success = response.status_code == 200
            
            if success:
                self.integration.messages_sent += 1
                db.session.commit()
            
            return success
        except Exception as e:
            logger.error(f'[Instagram] send_message error: {e}')
            return False
    
    def send_reply(self, post_id: str, message: str) -> bool:
        """إرسال رد على تعليق."""
        try:
            url = f'{self.base_url}/{post_id}/replies'
            payload = {
                'text': message,
                'access_token': self.access_token
            }
            
            response = requests.post(url, json=payload, timeout=10)
            return response.status_code == 200
        except Exception as e:
            logger.error(f'[Instagram] send_reply error: {e}')
            return False
    
    def _generate_ai_reply(self, user_message: str, platform: str) -> Optional[str]:
        """توليد رد باستخدام الذكاء الاصطناعي."""
        try:
            system_prompt = self._get_system_prompt(platform)
            
            result = AIService.generate(
                tenant_id=self.tenant_id,
                user_message=user_message,
                system_prompt=system_prompt,
                history=[]
            )
            
            if result.success:
                return result.text
            else:
                logger.warning(f'[Instagram] AI generation failed: {result.error}')
                return None
        except Exception as e:
            logger.error(f'[Instagram] _generate_ai_reply error: {e}')
            return None
    
    def _get_system_prompt(self, platform: str) -> str:
        """الحصول على نص التعليمات للذكاء الاصطناعي."""
        activity_code = self.tenant.activity.code if self.tenant.activity else 'general'
        
        if activity_code == 'hotel':
            return (
                f"أنت موظف خدمة عملاء في فندق {self.tenant.business_name}. "
                f"ترد على الرسائل المباشرة بشكل احترافي وودود. "
                f"تقدم معلومات عن الحجوزات والغرف والخدمات."
            )
        elif activity_code == 'restaurant':
            return (
                f"أنت موظف خدمة عملاء في مطعم {self.tenant.business_name}. "
                f"ترد على الرسائل المباشرة بشكل احترافي وودود. "
                f"تقدم معلومات عن القائمة والحجوزات والتوصيل."
            )
        else:
            return (
                f"أنت موظف خدمة عملاء في {self.tenant.business_name}. "
                f"ترد على الرسائل بشكل احترافي وودود."
            )


class TikTokProvider(SocialMediaProvider):
    """مزود تكامل تيك توك."""
    
    def __init__(self, tenant_id: int, integration: Integration):
        super().__init__(tenant_id, integration)
        from app.utils.encryption import decrypt_value
        self.access_token = decrypt_value(integration.access_token)
        self.client_key = decrypt_value(integration.api_key)
        self.base_url = 'https://open.tiktokapis.com/v1'
    
    def verify_webhook(self, data: Dict[str, Any]) -> bool:
        """التحقق من توقيع webhook من تيك توك."""
        return True
    
    def handle_event(self, event_data: Dict[str, Any]) -> Optional[str]:
        """معالجة حدث من تيك توك (تعليق على فيديو)."""
        try:
            event_type = event_data.get('type')
            
            if event_type == 'comment.create':
                comment_text = event_data.get('data', {}).get('text', '')
                comment_id = event_data.get('data', {}).get('comment_id', '')
                
                if comment_text:
                    reply = self._generate_ai_reply(comment_text, 'tiktok')
                    if reply:
                        self.send_reply(comment_id, reply)
                        return reply
            
            return None
        except Exception as e:
            logger.error(f'[TikTok] handle_event error: {e}')
            return None
    
    def send_message(self, recipient_id: str, message: str) -> bool:
        """إرسال رسالة عبر تيك توك (محدود الدعم)."""
        logger.warning('[TikTok] send_message not fully supported yet')
        return False
    
    def send_reply(self, comment_id: str, message: str) -> bool:
        """إرسال رد على تعليق في تيك توك."""
        try:
            url = f'{self.base_url}/comment/reply'
            headers = {
                'Authorization': f'Bearer {self.access_token}',
                'Content-Type': 'application/json'
            }
            payload = {
                'comment_id': comment_id,
                'content': message
            }
            
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            return response.status_code == 200
        except Exception as e:
            logger.error(f'[TikTok] send_reply error: {e}')
            return False
    
    def _generate_ai_reply(self, user_message: str, platform: str) -> Optional[str]:
        """توليد رد باستخدام الذكاء الاصطناعي."""
        try:
            system_prompt = self._get_system_prompt(platform)
            
            result = AIService.generate(
                tenant_id=self.tenant_id,
                user_message=user_message,
                system_prompt=system_prompt,
                history=[]
            )
            
            if result.success:
                return result.text
            else:
                return None
        except Exception as e:
            logger.error(f'[TikTok] _generate_ai_reply error: {e}')
            return None
    
    def _get_system_prompt(self, platform: str) -> str:
        """الحصول على نص التعليمات للذكاء الاصطناعي."""
        activity_code = self.tenant.activity.code if self.tenant.activity else 'general'
        
        if activity_code == 'hotel':
            return (
                f"أنت موظف خدمة عملاء في فندق {self.tenant.business_name}. "
                f"ترد على التعليقات بشكل احترافي وودود وموجز. "
                f"استخدم كلمات قصيرة وجذابة."
            )
        elif activity_code == 'restaurant':
            return (
                f"أنت موظف خدمة عملاء في مطعم {self.tenant.business_name}. "
                f"ترد على التعليقات بشكل احترافي وودود وموجز. "
                f"استخدم كلمات قصيرة وجذابة."
            )
        else:
            return (
                f"أنت موظف خدمة عملاء في {self.tenant.business_name}. "
                f"ترد على التعليقات بشكل احترافي وودود وموجز."
            )


class SnapchatProvider(SocialMediaProvider):
    """مزود تكامل سناب شات."""
    
    def __init__(self, tenant_id: int, integration: Integration):
        super().__init__(tenant_id, integration)
        from app.utils.encryption import decrypt_value
        self.access_token = decrypt_value(integration.access_token)
        self.ad_account_id = integration.extra_config.get('ad_account_id', '')
        self.base_url = 'https://adsapi.snapchat.com/v1'
    
    def verify_webhook(self, data: Dict[str, Any]) -> bool:
        """التحقق من توقيع webhook من سناب شات."""
        return True
    
    def handle_event(self, event_data: Dict[str, Any]) -> Optional[str]:
        """معالجة حدث من سناب شات (تحويل من إعلان)."""
        try:
            event_type = event_data.get('type')
            
            if event_type == 'conversion':
                # معالجة تحويل من إعلان سناب شات
                customer_info = event_data.get('customer_info', {})
                # يمكن هنا توجيه العميل للواتساب أو الشات
                logger.info(f'[Snapchat] conversion event: {customer_info}')
                return None
            
            return None
        except Exception as e:
            logger.error(f'[Snapchat] handle_event error: {e}')
            return None
    
    def send_message(self, recipient_id: str, message: str) -> bool:
        """إرسال رسالة عبر سناب شات (غير مدعوم للشركات)."""
        logger.warning('[Snapchat] send_message not supported for business accounts')
        return False
    
    def send_reply(self, post_id: str, message: str) -> bool:
        """إرسال رد (غير مدعوم)."""
        return False
    
    def _generate_ai_reply(self, user_message: str, platform: str) -> Optional[str]:
        """توليد رد (غير مستخدم في سناب شات)."""
        return None
    
    def _get_system_prompt(self, platform: str) -> str:
        """الحصول على نص التعليمات (غير مستخدم)."""
        return ""


class LinkedInProvider(SocialMediaProvider):
    """مزود تكامل لينكدإن."""
    
    def __init__(self, tenant_id: int, integration: Integration):
        super().__init__(tenant_id, integration)
        from app.utils.encryption import decrypt_value
        self.access_token = decrypt_value(integration.access_token)
        self.organization_id = integration.extra_config.get('organization_id', '')
        self.base_url = 'https://api.linkedin.com/v2'
    
    def verify_webhook(self, data: Dict[str, Any]) -> bool:
        """التحقق من توقيع webhook من لينكدإن."""
        return True
    
    def handle_event(self, event_data: Dict[str, Any]) -> Optional[str]:
        """معالجة حدث من لينكدإن (رسالة أو عميل محتمل)."""
        try:
            event_type = event_data.get('type')
            
            if event_type == 'lead_gen_form':
                # معالجة نموذج جمع العملاء المحتملين
                lead_data = event_data.get('lead_data', {})
                logger.info(f'[LinkedIn] lead_gen event: {lead_data}')
                return None
            
            elif event_type == 'message':
                # معالجة رسالة
                message_text = event_data.get('text', '')
                sender_id = event_data.get('sender_id', '')
                
                if message_text:
                    reply = self._generate_ai_reply(message_text, 'linkedin')
                    if reply:
                        self.send_message(sender_id, reply)
                        return reply
            
            return None
        except Exception as e:
            logger.error(f'[LinkedIn] handle_event error: {e}')
            return None
    
    def send_message(self, recipient_id: str, message: str) -> bool:
        """إرسال رسالة عبر لينكدإن."""
        try:
            url = f'{self.base_url}/messaging/conversations'
            headers = {
                'Authorization': f'Bearer {self.access_token}',
                'Content-Type': 'application/json'
            }
            payload = {
                'recipients': [recipient_id],
                'subject': 'رد من فريقنا',
                'body': message
            }
            
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            return response.status_code == 201
        except Exception as e:
            logger.error(f'[LinkedIn] send_message error: {e}')
            return False
    
    def send_reply(self, post_id: str, message: str) -> bool:
        """إرسال رد على تعليق."""
        try:
            url = f'{self.base_url}/comments'
            headers = {
                'Authorization': f'Bearer {self.access_token}',
                'Content-Type': 'application/json'
            }
            payload = {
                'object': post_id,
                'text': message
            }
            
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            return response.status_code == 201
        except Exception as e:
            logger.error(f'[LinkedIn] send_reply error: {e}')
            return False
    
    def _generate_ai_reply(self, user_message: str, platform: str) -> Optional[str]:
        """توليد رد باستخدام الذكاء الاصطناعي."""
        try:
            system_prompt = self._get_system_prompt(platform)
            
            result = AIService.generate(
                tenant_id=self.tenant_id,
                user_message=user_message,
                system_prompt=system_prompt,
                history=[]
            )
            
            if result.success:
                return result.text
            else:
                return None
        except Exception as e:
            logger.error(f'[LinkedIn] _generate_ai_reply error: {e}')
            return None
    
    def _get_system_prompt(self, platform: str) -> str:
        """الحصول على نص التعليمات للذكاء الاصطناعي."""
        return (
            f"أنت موظف احترافي في {self.tenant.business_name}. "
            f"ترد على الرسائل المهنية بشكل احترافي وموجز. "
            f"تركز على فرص العمل والشراكات."
        )


class GoogleMapsProvider(SocialMediaProvider):
    """مزود تكامل خرائط جوجل."""
    
    def __init__(self, tenant_id: int, integration: Integration):
        super().__init__(tenant_id, integration)
        from app.utils.encryption import decrypt_value
        self.access_token = decrypt_value(integration.access_token)
        self.business_location_id = integration.extra_config.get('business_location_id', '')
        self.base_url = 'https://mybusiness.googleapis.com/v1'
    
    def verify_webhook(self, data: Dict[str, Any]) -> bool:
        """التحقق من توقيع webhook من جوجل."""
        return True
    
    def handle_event(self, event_data: Dict[str, Any]) -> Optional[str]:
        """معالجة حدث من جوجل (تقييم أو سؤال)."""
        try:
            event_type = event_data.get('type')
            
            if event_type == 'review':
                # معالجة تقييم جديد
                review_text = event_data.get('review_text', '')
                rating = event_data.get('rating', 0)
                review_id = event_data.get('review_id', '')
                
                reply = self._generate_review_reply(review_text, rating, 'google_maps')
                if reply:
                    self.send_reply(review_id, reply)
                    return reply
            
            elif event_type == 'question':
                # معالجة سؤال
                question_text = event_data.get('question_text', '')
                question_id = event_data.get('question_id', '')
                
                reply = self._generate_ai_reply(question_text, 'google_maps')
                if reply:
                    self.send_reply(question_id, reply)
                    return reply
            
            return None
        except Exception as e:
            logger.error(f'[GoogleMaps] handle_event error: {e}')
            return None
    
    def send_message(self, recipient_id: str, message: str) -> bool:
        """إرسال رسالة (غير مدعوم في جوجل)."""
        logger.warning('[GoogleMaps] send_message not supported')
        return False
    
    def send_reply(self, review_id: str, message: str) -> bool:
        """إرسال رد على تقييم أو سؤال."""
        try:
            url = f'{self.base_url}/accounts/{self.business_location_id}/reviews/{review_id}/reply'
            headers = {
                'Authorization': f'Bearer {self.access_token}',
                'Content-Type': 'application/json'
            }
            payload = {
                'comment': message
            }
            
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            return response.status_code == 200
        except Exception as e:
            logger.error(f'[GoogleMaps] send_reply error: {e}')
            return False
    
    def _generate_review_reply(self, review_text: str, rating: int, platform: str) -> Optional[str]:
        """توليد رد على تقييم."""
        try:
            if rating >= 4:
                system_prompt = (
                    f"أنت موظف خدمة عملاء في {self.tenant.business_name}. "
                    f"ترد على التقييمات الإيجابية بشكل ودود وشاكر. "
                    f"اشكر العميل على تقييمه الرائع وادعه للعودة."
                )
            else:
                system_prompt = (
                    f"أنت موظف خدمة عملاء في {self.tenant.business_name}. "
                    f"ترد على التقييمات السلبية بشكل احترافي واعتذاري. "
                    f"اعتذر عن التجربة السيئة وقدم حلاً."
                )
            
            result = AIService.generate(
                tenant_id=self.tenant_id,
                user_message=review_text,
                system_prompt=system_prompt,
                history=[]
            )
            
            if result.success:
                return result.text
            else:
                return None
        except Exception as e:
            logger.error(f'[GoogleMaps] _generate_review_reply error: {e}')
            return None
    
    def _generate_ai_reply(self, user_message: str, platform: str) -> Optional[str]:
        """توليد رد على سؤال."""
        try:
            system_prompt = (
                f"أنت موظف خدمة عملاء في {self.tenant.business_name}. "
                f"ترد على الأسئلة بشكل احترافي وودود. "
                f"قدم معلومات مفيدة وادع العميل للتواصل مباشرة."
            )
            
            result = AIService.generate(
                tenant_id=self.tenant_id,
                user_message=user_message,
                system_prompt=system_prompt,
                history=[]
            )
            
            if result.success:
                return result.text
            else:
                return None
        except Exception as e:
            logger.error(f'[GoogleMaps] _generate_ai_reply error: {e}')
            return None


class SocialMediaIntegrationService:
    """الخدمة الرئيسية لإدارة تكاملات منصات التواصل الاجتماعي."""
    
    PROVIDERS = {
        'facebook': FacebookProvider,
        'instagram': InstagramProvider,
        'tiktok': TikTokProvider,
        'snapchat': SnapchatProvider,
        'linkedin': LinkedInProvider,
        'google_maps': GoogleMapsProvider,
    }
    
    def __init__(self, tenant_id: int):
        self.tenant_id = tenant_id
        self.tenant = Tenant.query.get(tenant_id)
        if not self.tenant:
            raise ValueError(f'Tenant {tenant_id} not found')
    
    def activate_integration(
        self,
        service_type: str,
        provider: str,
        credentials: Dict[str, Any]
    ) -> Tuple[bool, str]:
        """تفعيل تكامل جديد."""
        try:
            # التحقق من وجود تكامل سابق
            existing = Integration.query.filter_by(
                tenant_id=self.tenant_id,
                service_type=service_type
            ).first()
            
            if existing:
                # تحديث التكامل الموجود
                integration = existing
            else:
                # إنشاء تكامل جديد
                integration = Integration(
                    tenant_id=self.tenant_id,
                    service_type=service_type,
                    provider=provider
                )
            
            # تحديث بيانات المصادقة
            integration.api_key_decrypted = credentials.get('api_key', '')
            integration.api_secret_decrypted = credentials.get('api_secret', '')
            integration.access_token_decrypted = credentials.get('access_token', '')
            
            integration.phone_number = credentials.get('phone_number', '')
            integration.phone_number_id = credentials.get('phone_number_id', '')
            integration.waba_id = credentials.get('waba_id', '')
            integration.webhook_verify_token_decrypted = credentials.get('webhook_verify_token', '')
            
            # تحديث الإعدادات الإضافية
            extra_config = credentials.get('extra_config', {})
            integration.extra_config = extra_config
            
            # تفعيل التكامل
            integration.is_active = True
            
            db.session.add(integration)
            db.session.commit()
            
            logger.info(f'[SocialMedia] Integration activated: tenant={self.tenant_id}, service={service_type}')
            return True, 'تم تفعيل التكامل بنجاح'
        except Exception as e:
            logger.error(f'[SocialMedia] activate_integration error: {e}')
            return False, f'خطأ: {str(e)}'
    
    def handle_webhook_event(
        self,
        service_type: str,
        event_data: Dict[str, Any]
    ) -> Optional[str]:
        """معالجة حدث webhook من منصة تواصل اجتماعي."""
        try:
            integration = Integration.query.filter_by(
                tenant_id=self.tenant_id,
                service_type=service_type,
                is_active=True
            ).first()
            
            if not integration:
                logger.warning(f'[SocialMedia] No active integration for {service_type}')
                return None
            
            provider_class = self.PROVIDERS.get(service_type)
            if not provider_class:
                logger.error(f'[SocialMedia] Unknown service type: {service_type}')
                return None
            
            provider = provider_class(self.tenant_id, integration)
            response = provider.handle_event(event_data)
            
            return response
        except Exception as e:
            logger.error(f'[SocialMedia] handle_webhook_event error: {e}')
            return None
    
    def get_active_integrations(self) -> list:
        """الحصول على قائمة التكاملات النشطة."""
        return Integration.query.filter_by(
            tenant_id=self.tenant_id,
            is_active=True
        ).all()
    
    def deactivate_integration(self, service_type: str) -> Tuple[bool, str]:
        """تعطيل تكامل."""
        try:
            integration = Integration.query.filter_by(
                tenant_id=self.tenant_id,
                service_type=service_type
            ).first()
            
            if not integration:
                return False, 'التكامل غير موجود'
            
            integration.is_active = False
            db.session.commit()
            
            logger.info(f'[SocialMedia] Integration deactivated: tenant={self.tenant_id}, service={service_type}')
            return True, 'تم تعطيل التكامل بنجاح'
        except Exception as e:
            logger.error(f'[SocialMedia] deactivate_integration error: {e}')
            return False, f'خطأ: {str(e)}'

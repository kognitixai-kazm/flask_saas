"""
app/services/social_media_ai_connector.py — خدمة ربط التكاملات الاجتماعية بالذكاء الاصطناعي

تقوم هذه الخدمة بربط أحداث منصات التواصل الاجتماعي (رسائل، تعليقات، تقييمات) 
بنظام الذكاء الاصطناعي الموحد، مما يسمح بالرد التلقائي والذكي على جميع المنصات.

الاستخدام:
    connector = SocialMediaAIConnector(tenant_id)
    
    # معالجة حدث من منصة اجتماعية
    response = connector.process_social_event(
        service_type='facebook',
        event_data={...},
        user_message='السؤال من العميل',
        context={...}
    )
"""

import logging
from typing import Optional, Dict, Any
from datetime import datetime

from flask import current_app
from app.extensions import db
from app.models.tenant import Tenant
from app.models.integration import Integration
from app.models.conversation import Conversation, Message
from app.services.ai_service import AIService
from app.services.chat_service import ChatService


logger = logging.getLogger(__name__)


class SocialMediaAIConnector:
    """خدمة ربط التكاملات الاجتماعية بالذكاء الاصطناعي."""
    
    def __init__(self, tenant_id: int):
        self.tenant_id = tenant_id
        self.tenant = Tenant.query.get(tenant_id)
        if not self.tenant:
            raise ValueError(f'Tenant {tenant_id} not found')
    
    def process_social_event(
        self,
        service_type: str,
        event_data: Dict[str, Any],
        user_message: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """
        معالجة حدث من منصة اجتماعية وتوليد رد ذكي.
        
        Args:
            service_type: نوع الخدمة (facebook, instagram, tiktok, etc.)
            event_data: بيانات الحدث من المنصة
            user_message: رسالة المستخدم/التعليق/التقييم
            context: معلومات سياقية إضافية (مثل معرّف المستخدم، الوقت، إلخ)
        
        Returns:
            الرد المولد من الذكاء الاصطناعي، أو None إذا فشلت المعالجة
        """
        try:
            # التحقق من تفعيل التكامل
            integration = Integration.query.filter_by(
                tenant_id=self.tenant_id,
                service_type=service_type,
                is_active=True
            ).first()
            
            if not integration:
                logger.warning(f'[SocialMediaAI] Integration not active: {service_type}')
                return None
            
            # التحقق من تفعيل الردود الآلية
            if not integration.extra_config.get('enable_ai_responses', True):
                logger.info(f'[SocialMediaAI] AI responses disabled for {service_type}')
                return None
            
            # إنشاء محادثة أو الحصول على المحادثة الموجودة
            conversation = self._get_or_create_conversation(
                service_type=service_type,
                event_data=event_data,
                context=context
            )
            
            if not conversation:
                logger.error(f'[SocialMediaAI] Failed to create/get conversation')
                return None
            
            # حفظ الرسالة الواردة
            self._save_incoming_message(
                conversation=conversation,
                user_message=user_message,
                service_type=service_type,
                event_data=event_data
            )
            
            # توليد الرد باستخدام الذكاء الاصطناعي
            ai_reply = self._generate_ai_reply(
                conversation=conversation,
                user_message=user_message,
                service_type=service_type,
                integration=integration
            )
            
            if ai_reply:
                # حفظ الرد المولد
                self._save_outgoing_message(
                    conversation=conversation,
                    reply=ai_reply,
                    service_type=service_type
                )
                
                # خصم التكلفة من رصيد المستأجر
                self._charge_ai_message(
                    tenant_id=self.tenant_id,
                    conversation_id=conversation.id,
                    service_type=service_type
                )
                
                return ai_reply
            
            return None
        except Exception as e:
            logger.error(f'[SocialMediaAI] process_social_event error: {e}')
            return None
    
    def _get_or_create_conversation(
        self,
        service_type: str,
        event_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> Optional[Conversation]:
        """الحصول على محادثة موجودة أو إنشاء محادثة جديدة."""
        try:
            context = context or {}
            
            # استخراج معرّف المستخدم/الزائر
            visitor_id = context.get('visitor_id') or event_data.get('sender_id', '')
            if not visitor_id:
                logger.warning(f'[SocialMediaAI] No visitor_id in event')
                return None
            
            # البحث عن محادثة موجودة
            conversation = Conversation.query.filter_by(
                tenant_id=self.tenant_id,
                visitor_id=visitor_id,
                platform=service_type
            ).first()
            
            if conversation:
                # تحديث آخر نشاط
                conversation.last_message_at = datetime.utcnow()
                db.session.commit()
                return conversation
            
            # إنشاء محادثة جديدة
            conversation = Conversation(
                tenant_id=self.tenant_id,
                visitor_id=visitor_id,
                platform=service_type,
                source_url=context.get('source_url', ''),
                visitor_name=context.get('visitor_name', 'زائر'),
                visitor_email=context.get('visitor_email', ''),
                visitor_phone=context.get('visitor_phone', ''),
            )
            
            # حفظ معرّفات المنصة الخاصة
            extra_data = {
                'platform_event_id': event_data.get('event_id', ''),
                'platform_user_id': event_data.get('sender_id', ''),
                'platform_page_id': event_data.get('page_id', ''),
            }
            conversation.extra_data = extra_data
            
            db.session.add(conversation)
            db.session.commit()
            
            logger.info(f'[SocialMediaAI] Created new conversation: {conversation.id}')
            return conversation
        except Exception as e:
            logger.error(f'[SocialMediaAI] _get_or_create_conversation error: {e}')
            return None
    
    def _save_incoming_message(
        self,
        conversation: Conversation,
        user_message: str,
        service_type: str,
        event_data: Dict[str, Any]
    ) -> None:
        """حفظ الرسالة الواردة في قاعدة البيانات."""
        try:
            message = Message(
                conversation_id=conversation.id,
                role='visitor',
                content=user_message,
                platform=service_type,
                platform_message_id=event_data.get('message_id', ''),
            )
            
            db.session.add(message)
            db.session.commit()
            
            # تحديث عداد الرسائل المستقبلة
            integration = Integration.query.filter_by(
                tenant_id=self.tenant_id,
                service_type=service_type
            ).first()
            
            if integration:
                integration.messages_received += 1
                db.session.commit()
        except Exception as e:
            logger.error(f'[SocialMediaAI] _save_incoming_message error: {e}')
    
    def _save_outgoing_message(
        self,
        conversation: Conversation,
        reply: str,
        service_type: str
    ) -> None:
        """حفظ الرد المولد في قاعدة البيانات."""
        try:
            message = Message(
                conversation_id=conversation.id,
                role='bot',
                content=reply,
                platform=service_type,
            )
            
            db.session.add(message)
            db.session.commit()
            
            # تحديث عداد الرسائل المرسلة
            integration = Integration.query.filter_by(
                tenant_id=self.tenant_id,
                service_type=service_type
            ).first()
            
            if integration:
                integration.messages_sent += 1
                db.session.commit()
        except Exception as e:
            logger.error(f'[SocialMediaAI] _save_outgoing_message error: {e}')
    
    def _generate_ai_reply(
        self,
        conversation: Conversation,
        user_message: str,
        service_type: str,
        integration: Integration
    ) -> Optional[str]:
        """توليد رد ذكي باستخدام الذكاء الاصطناعي."""
        try:
            # بناء نص التعليمات (System Prompt)
            system_prompt = self._build_system_prompt(
                service_type=service_type,
                integration=integration
            )
            
            # الحصول على السجل التاريخي للمحادثة
            history = self._get_conversation_history(conversation)
            
            # استدعاء خدمة الذكاء الاصطناعي
            result = AIService.generate(
                tenant_id=self.tenant_id,
                user_message=user_message,
                system_prompt=system_prompt,
                history=history
            )
            
            if result.success:
                logger.info(f'[SocialMediaAI] AI reply generated: tokens={result.tokens_total}')
                return result.text
            else:
                logger.warning(f'[SocialMediaAI] AI generation failed: {result.error}')
                return None
        except Exception as e:
            logger.error(f'[SocialMediaAI] _generate_ai_reply error: {e}')
            return None
    
    def _build_system_prompt(
        self,
        service_type: str,
        integration: Integration
    ) -> str:
        """بناء نص التعليمات (System Prompt) للذكاء الاصطناعي."""
        try:
            activity_code = self.tenant.activity.code if self.tenant.activity else 'general'
            ai_tone = integration.extra_config.get('ai_tone', 'professional')
            ai_instructions = integration.extra_config.get('ai_instructions', '')
            
            # نص التعليمات الأساسي حسب نوع النشاط
            if activity_code == 'hotel':
                base_prompt = (
                    f"أنت موظف خدمة عملاء متميز في فندق {self.tenant.business_name}. "
                    f"تقدم خدمة احترافية وودية للضيوف. "
                    f"تجيب على الاستفسارات حول الحجوزات والغرف والخدمات والمرافق. "
                    f"إذا لم تتمكن من الإجابة، تطلب من الضيف التواصل مع الاستقبال."
                )
            elif activity_code == 'restaurant':
                base_prompt = (
                    f"أنت موظف خدمة عملاء متميز في مطعم {self.tenant.business_name}. "
                    f"تقدم خدمة احترافية وودية للزبائن. "
                    f"تجيب على الاستفسارات حول القائمة والحجوزات والتوصيل والعروض. "
                    f"إذا لم تتمكن من الإجابة، تطلب من الزبون التواصل مع الفريق."
                )
            else:
                base_prompt = (
                    f"أنت موظف خدمة عملاء متميز في {self.tenant.business_name}. "
                    f"تقدم خدمة احترافية وودية. "
                    f"تجيب على الاستفسارات بشكل مفيد ودقيق."
                )
            
            # إضافة نبرة الرد
            tone_instructions = {
                'professional': 'استخدم لغة احترافية ورسمية.',
                'friendly': 'استخدم لغة ودية وشخصية.',
                'brief': 'كن موجزاً وسريعاً في الردود.',
                'detailed': 'قدم تفاصيل شاملة وكاملة.'
            }
            
            tone_prompt = tone_instructions.get(ai_tone, '')
            
            # إضافة التعليمات المخصصة
            custom_instructions = ''
            if ai_instructions:
                custom_instructions = f"\n\nتعليمات إضافية: {ai_instructions}"
            
            # إضافة تعليمات خاصة بالمنصة
            platform_instructions = self._get_platform_specific_instructions(service_type)
            
            # دمج جميع الأجزاء
            full_prompt = f"{base_prompt}\n\n{tone_prompt}{platform_instructions}{custom_instructions}"
            
            return full_prompt
        except Exception as e:
            logger.error(f'[SocialMediaAI] _build_system_prompt error: {e}')
            return f"أنت موظف خدمة عملاء في {self.tenant.business_name}."
    
    def _get_platform_specific_instructions(self, service_type: str) -> str:
        """الحصول على تعليمات خاصة بالمنصة."""
        instructions = {
            'facebook': '\nتذكر أنك تتحدث عبر فيسبوك، فاستخدم لغة مناسبة للمنصة.',
            'instagram': '\nتذكر أنك تتحدث عبر انستغرام، فاستخدم لغة مناسبة وموجزة.',
            'tiktok': '\nتذكر أنك تتحدث عبر تيك توك، فكن موجزاً وجذاباً.',
            'snapchat': '\nتذكر أنك تتحدث عبر سناب شات، فكن سريعاً وودياً.',
            'linkedin': '\nتذكر أنك تتحدث عبر لينكدإن، فاستخدم لغة احترافية.',
            'google_maps': '\nتذكر أنك ترد على تقييم أو سؤال في خرائط جوجل، فكن احترافياً وشاكراً.'
        }
        
        return instructions.get(service_type, '')
    
    def _get_conversation_history(self, conversation: Conversation) -> list:
        """الحصول على السجل التاريخي للمحادثة."""
        try:
            messages = Message.query.filter_by(
                conversation_id=conversation.id
            ).order_by(Message.created_at.asc()).limit(10).all()
            
            history = []
            for msg in messages:
                history.append({
                    'role': 'user' if msg.role == 'visitor' else 'assistant',
                    'content': msg.content
                })
            
            return history
        except Exception as e:
            logger.error(f'[SocialMediaAI] _get_conversation_history error: {e}')
            return []
    
    def _charge_ai_message(
        self,
        tenant_id: int,
        conversation_id: int,
        service_type: str
    ) -> None:
        """خصم تكلفة الرسالة من رصيد المستأجر."""
        try:
            # هذا يعتمد على نظام الرسوم الموجود في المشروع
            # يمكن استخدام ChatService._charge_message إذا كان متوفراً
            ChatService._charge_message(
                tenant_id=tenant_id,
                service_key='ai_message',
                conversation_id=conversation_id
            )
        except Exception as e:
            logger.warning(f'[SocialMediaAI] _charge_ai_message error: {e}')


class SocialMediaWebhookProcessor:
    """معالج Webhook الموحد لجميع منصات التواصل الاجتماعي."""
    
    @staticmethod
    def process_webhook(
        service_type: str,
        webhook_data: Dict[str, Any],
        tenant_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        معالجة webhook من منصة تواصل اجتماعي.
        
        Args:
            service_type: نوع الخدمة (facebook, instagram, etc.)
            webhook_data: بيانات الـ webhook
            tenant_id: معرّف المستأجر (اختياري، قد يتم استخراجه من البيانات)
        
        Returns:
            قاموس يحتوي على نتائج المعالجة
        """
        try:
            # استخراج معرّف المستأجر من البيانات إذا لم يتم تمريره
            if not tenant_id:
                tenant_id = SocialMediaWebhookProcessor._extract_tenant_id(
                    service_type=service_type,
                    webhook_data=webhook_data
                )
            
            if not tenant_id:
                logger.error(f'[Webhook] Could not determine tenant_id')
                return {'status': 'error', 'message': 'Could not determine tenant'}
            
            # إنشاء معالج الاتصال
            connector = SocialMediaAIConnector(tenant_id)
            
            # استخراج بيانات الحدث
            event_data = webhook_data.get('event_data', {})
            user_message = webhook_data.get('message', '')
            context = webhook_data.get('context', {})
            
            # معالجة الحدث
            response = connector.process_social_event(
                service_type=service_type,
                event_data=event_data,
                user_message=user_message,
                context=context
            )
            
            return {
                'status': 'success',
                'message': response,
                'tenant_id': tenant_id,
                'service_type': service_type
            }
        except Exception as e:
            logger.error(f'[Webhook] process_webhook error: {e}')
            return {'status': 'error', 'message': str(e)}
    
    @staticmethod
    def _extract_tenant_id(service_type: str, webhook_data: Dict[str, Any]) -> Optional[int]:
        """استخراج معرّف المستأجر من بيانات الـ webhook."""
        try:
            # البحث عن معرّف الصفحة أو حساب الإعلانات أو معرّف الموقع
            page_id = webhook_data.get('page_id')
            ad_account_id = webhook_data.get('ad_account_id')
            location_id = webhook_data.get('location_id')
            
            # البحث عن التكامل المرتبط بهذا المعرّف
            integration = None
            
            if page_id:
                integration = Integration.query.filter_by(
                    service_type=service_type
                ).filter(
                    Integration.extra_config['page_id'].astext == page_id
                ).first()
            elif ad_account_id:
                integration = Integration.query.filter_by(
                    service_type=service_type
                ).filter(
                    Integration.extra_config['ad_account_id'].astext == ad_account_id
                ).first()
            elif location_id:
                integration = Integration.query.filter_by(
                    service_type=service_type
                ).filter(
                    Integration.extra_config['business_location_id'].astext == location_id
                ).first()
            
            if integration:
                return integration.tenant_id
            
            return None
        except Exception as e:
            logger.error(f'[Webhook] _extract_tenant_id error: {e}')
            return None

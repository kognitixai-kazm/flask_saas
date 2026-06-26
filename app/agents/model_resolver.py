"""
app/agents/model_resolver.py — تحديد نموذج الذكاء الاصطناعي ومفتاح API.

آلية الاختيار:
يتم جلب المزود المتاح من جدول AIProvider حسب الأولوية.
"""
import os
from dataclasses import dataclass
from typing import Optional

from app.models.ai_model import AIModel
from app.models.ai_provider import AIProvider
from app.models.bot_config import BotConfig
from app.models.system_settings import SystemSetting


@dataclass
class ResolvedModel:
    """نتيجة تحديد النموذج — تحتوي على كل ما يحتاجه الوكيل لتشغيل LLM."""
    provider: str           # anthropic | openai | google
    model_id: str           # claude-sonnet-4-6 | gpt-4o | gemini-1.5-pro
    api_key: str            # مفتاح API
    display_name: str       # الاسم المعروض
    ai_model_db_id: Optional[int] = None  # ID في جدول ai_models (للتسعير)
    price_per_message: float = 0.0
    cost_per_message: float = 0.0
    is_tenant_key: bool = False  # دائماً False بعد التحديث
    temperature: float = 0.7


class ModelResolver:
    """محدد النموذج والمفتاح لكل تاجر."""

    @staticmethod
    def resolve(tenant_id: int, agent_type: str = 'general') -> Optional[ResolvedModel]:
        """
        تحديد النموذج والمفتاح المناسب.
        يبحث في جميع المزودين المتاحين مرتبين حسب الأولوية، ويختار أول مزود يمتلك مفتاح API صالح.
        """
        import logging
        from app.services.ai_service import AIService
        logger = logging.getLogger(__name__)

        providers = AIProvider.query.filter_by(is_active=True).order_by(AIProvider.priority.asc()).all()
        
        for provider in providers:
            logger.info(f"Selected Provider: {provider.name}")
            
            # استخدام مفتاح المزود إذا كان موجوداً، أو جلب من الإعدادات
            api_key = getattr(provider, 'api_key_decrypted', None)
            
            # جلب النموذج الافتراضي للمزود
            db_model = AIModel.query.filter_by(provider_id=provider.id, is_active=True).first()
            
            if not db_model:
                logger.info(f"{provider.name} → No active AIModel Found → Trying Next Provider")
                continue
                
            if not api_key:
                api_key = ModelResolver._get_platform_key(provider.slug)
                
            if not api_key:
                logger.info(f"{provider.name} → API Key Missing → Trying Next Provider")
                continue
                
            logger.info(f"Selected Provider: {provider.name}")
            logger.info("API Key Found")
            
            # تحقق من صلاحية المفتاح فعلياً
            is_valid, reason = AIService.validate_api_key(provider.slug, api_key)
            if not is_valid:
                logger.warning(f"{provider.name} → Invalid API Key ({reason}) → Trying Next Provider")
                continue

            logger.info("AI Request Started")

            return ResolvedModel(
                provider=provider.slug,
                model_id=db_model.model_id,
                api_key=api_key,
                display_name=db_model.display_name,
                ai_model_db_id=db_model.id,
                price_per_message=float(db_model.price_per_message),
                cost_per_message=float(db_model.cost_per_message),
                is_tenant_key=False,
            )
            
        logger.warning("No Available AI Provider")
        logger.warning("Falling Back To Local Reply")
        return None

    @staticmethod
    def _get_platform_key(provider: str) -> str:
        """جلب مفتاح API العام للمنصة."""
        key_map = {
            'anthropic': ('AI_ANTHROPIC_KEY', 'ANTHROPIC_API_KEY'),
            'openai': ('AI_OPENAI_KEY', 'OPENAI_API_KEY'),
            'google': ('AI_GOOGLE_KEY', 'GOOGLE_API_KEY'),
        }
        setting_key, env_key = key_map.get(provider.lower(), ('', ''))

        if setting_key:
            v = SystemSetting.get(setting_key, '').strip()
            if v:
                return v

        if env_key:
            v = os.getenv(env_key, '').strip()
            if v:
                return v

        return ''

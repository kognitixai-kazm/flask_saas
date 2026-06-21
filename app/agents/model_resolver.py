"""
app/agents/model_resolver.py — تحديد نموذج الذكاء الاصطناعي ومفتاح API لكل تاجر.

آلية الاختيار:
1. إذا كان التاجر لديه مفتاح API خاص (BotConfig.ai_api_key) → يُستخدم مباشرة
2. إذا لم يكن → يُستخدم النموذج الافتراضي للمنصة (AIModel.is_default)
3. يجلب المفتاح من: BotConfig → SystemSetting → متغيرات البيئة

يستخدمه جميع الوكلاء عند الحاجة لتحديد النموذج المناسب.
"""
import os
from dataclasses import dataclass
from typing import Optional

from app.models.ai_model import AIModel
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
    is_tenant_key: bool = False  # هل المفتاح خاص بالتاجر أم عام؟
    temperature: float = 0.7


class ModelResolver:
    """محدد النموذج والمفتاح لكل تاجر."""

    @staticmethod
    def resolve(tenant_id: int, agent_type: str = 'general') -> Optional[ResolvedModel]:
        """
        تحديد النموذج والمفتاح المناسب لتاجر معين.

        Args:
            tenant_id: معرف التاجر
            agent_type: نوع الوكيل (front_desk, collection, manager) — للتخصيص المستقبلي

        Returns:
            ResolvedModel أو None إذا لم يتوفر نموذج
        """
        bot_config = BotConfig.query.filter_by(tenant_id=tenant_id).first()

        # ========== 1. محاولة استخدام إعدادات التاجر المخصصة ==========
        if bot_config and bot_config.ai_provider and bot_config.ai_api_key:
            # التاجر لديه مفتاح خاص
            model_id = bot_config.ai_model or ModelResolver._default_model_for_provider(
                bot_config.ai_provider
            )

            # البحث عن النموذج في الجدول لمعرفة السعر
            db_model = AIModel.query.filter_by(
                provider=bot_config.ai_provider,
                model_id=model_id,
                is_active=True,
            ).first()

            from app.utils.encryption import decrypt_value
            decrypted_key = decrypt_value(bot_config.ai_api_key)

            return ResolvedModel(
                provider=bot_config.ai_provider,
                model_id=model_id,
                api_key=decrypted_key.strip(),
                display_name=db_model.display_name if db_model else model_id,
                ai_model_db_id=db_model.id if db_model else None,
                price_per_message=float(db_model.price_per_message) if db_model else 0.0,
                cost_per_message=float(db_model.cost_per_message) if db_model else 0.0,
                is_tenant_key=True,
            )

        # ========== 2. النموذج الافتراضي للمنصة ==========
        db_model = None
        if bot_config and bot_config.ai_provider and bot_config.ai_model:
            # التاجر اختار نموذجاً لكن بدون مفتاح خاص → نستخدم مفتاح المنصة
            db_model = AIModel.query.filter_by(
                provider=bot_config.ai_provider,
                model_id=bot_config.ai_model,
                is_active=True,
            ).first()

        if not db_model:
            # الرجوع للنموذج الافتراضي
            db_model = AIModel.query.filter_by(is_default=True, is_active=True).first()

        if not db_model:
            # لا يوجد أي نموذج متاح
            return None

        # جلب مفتاح المنصة
        api_key = ModelResolver._get_platform_key(db_model.provider)
        if not api_key:
            return None

        return ResolvedModel(
            provider=db_model.provider,
            model_id=db_model.model_id,
            api_key=api_key,
            display_name=db_model.display_name,
            ai_model_db_id=db_model.id,
            price_per_message=float(db_model.price_per_message),
            cost_per_message=float(db_model.cost_per_message),
            is_tenant_key=False,
        )

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

    @staticmethod
    def _default_model_for_provider(provider: str) -> str:
        """النموذج الافتراضي لكل مزوّد."""
        defaults = {
            'openai': 'gpt-4o',
            'anthropic': 'claude-sonnet-4-6',
            'google': 'gemini-1.5-pro',
        }
        return defaults.get(provider.lower(), 'gpt-4o')

import logging
from typing import List, Dict, Optional, Any

from flask import current_app
from app.models.ai_provider import AIProvider
from app.models.ai_model import AIModel
from app.services.ai_service import AIService, AIResult
from app.models.bot_config import BotConfig

logger = logging.getLogger(__name__)

class AIRouter:
    @staticmethod
    def route_task(
        task_type: str,
        user_message: str,
        history: List[Dict[str, str]],
        tenant_id: int
    ) -> AIResult:
        \"\"\"
        Routes an AI task based on task_type using available AIProviders and a fallback mechanism.
        task_type: 'simple', 'sensitive', 'complex', 'fallback'
        \"\"\"
        try:
            if hasattr(AIProvider, 'priority'):
                providers = AIProvider.query.filter_by(is_active=True).order_by(AIProvider.priority.asc()).all()
            else:
                providers = AIProvider.query.filter_by(is_active=True).order_by(AIProvider.id.asc()).all()
        except Exception as e:
            logger.error(f"Error fetching AIProviders: {e}")
            return AIResult(success=False, error="Database error fetching providers")

        if not providers:
            return AIResult(success=False, error="No active AI providers available.")

        task_mapping = {
            'simple': ['google', 'gemini'],
            'sensitive': ['anthropic', 'claude'],
            'complex': ['openai', 'gpt'],
            'fallback': ['google', 'gemini']
        }
        
        preferred_slugs = task_mapping.get(task_type.lower(), [])
        
        preferred_providers = []
        other_providers = []
        
        for p in providers:
            if any(slug in p.slug.lower() for slug in preferred_slugs):
                preferred_providers.append(p)
            else:
                other_providers.append(p)
                
        ordered_providers = preferred_providers + other_providers
        
        system_prompt = "You are a helpful assistant."
        try:
            bot_config = BotConfig.query.filter_by(tenant_id=tenant_id).first()
            if bot_config and bot_config.system_prompt:
                system_prompt = bot_config.system_prompt
        except Exception as e:
            logger.warning(f"Could not load bot config for tenant {tenant_id}: {e}")

        last_error = "Unknown error"
        
        for provider in ordered_providers:
            try:
                api_key = getattr(provider, 'api_key_decrypted', None)
                if not api_key:
                    logger.warning(f"Provider {provider.slug} has no api_key_decrypted. Trying next.")
                    continue
                    
                model = AIModel.query.filter_by(provider_id=provider.id, is_active=True).first()
                if not model:
                    logger.warning(f"No active AIModel found for provider {provider.slug}. Trying next.")
                    continue
                    
                result = None
                provider_slug = provider.slug.lower()
                
                if 'anthropic' in provider_slug or 'claude' in provider_slug:
                    result = AIService._call_anthropic(
                        api_key=api_key,
                        model_id=model.model_id,
                        system_prompt=system_prompt,
                        history=history,
                        user_message=user_message
                    )
                elif 'openai' in provider_slug or 'gpt' in provider_slug:
                    result = AIService._call_openai(
                        api_key=api_key,
                        model_id=model.model_id,
                        system_prompt=system_prompt,
                        history=history,
                        user_message=user_message
                    )
                elif 'google' in provider_slug or 'gemini' in provider_slug:
                    result = AIService._call_gemini(
                        api_key=api_key,
                        model_id=model.model_id,
                        system_prompt=system_prompt,
                        history=history,
                        user_message=user_message
                    )
                else:
                    logger.warning(f"Unsupported provider {provider.slug}")
                    continue
                    
                if result and result.success:
                    result.provider = provider.slug
                    result.model_id = model.id
                    result.model_name = model.display_name
                    return result
                else:
                    last_error = result.error if result else "Unknown failure"
                    logger.warning(f"Provider {provider.slug} failed: {last_error}")
                    
            except Exception as e:
                last_error = str(e)
                logger.error(f"Error calling provider {provider.slug}: {e}")
                
        return AIResult(
            success=False,
            error=f"All providers failed. Last error: {last_error}"
        )

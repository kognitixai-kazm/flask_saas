"""
app/services/ai_service.py — خدمة AI الموحدة لكل المزوّدين.

يدعم: Anthropic (Claude), OpenAI (GPT), Google (Gemini)

الاستخدام:
    result = AIService.generate(
        tenant_id=tenant.id,
        user_message="سؤال العميل",
        system_prompt="أنت موظف فندق...",
        history=[...],
    )
    if result.success:
        reply = result.text
        tokens_used = result.tokens_total
"""
import json
import os
import time
import threading
import requests
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple
from flask import current_app

from app.models.ai_model import AIModel
from app.models.bot_config import BotConfig
from app.models.system_settings import SystemSetting

_KEY_VALIDATION_CACHE: Dict[Tuple[str, str], Tuple[bool, float]] = {}
_KEY_VALIDATION_LOCK = threading.Lock()
_KEY_VALIDATION_TTL_OK = 60 * 60  # ساعة
_KEY_VALIDATION_TTL_BAD = 5 * 60  # 5 دقائق


@dataclass
class AIResult:
    """نتيجة استدعاء AI."""
    success: bool = False
    text: str = ''
    error: str = ''
    model_id: Optional[int] = None
    provider: str = ''
    model_name: str = ''
    tokens_in: int = 0
    tokens_out: int = 0

    @property
    def tokens_total(self):
        return (self.tokens_in or 0) + (self.tokens_out or 0)


class AIService:
    """خدمة استدعاء نماذج AI."""

    # مهلة (اتصال، قراءة) بالثواني — تُضبط من البيئة لتفادي تعليق طلب الشات
    # مثال: AI_HTTP_CONNECT_TIMEOUT=10 و AI_HTTP_READ_TIMEOUT=25
    @staticmethod
    def http_timeout():
        try:
            c = int(os.getenv('AI_HTTP_CONNECT_TIMEOUT', '10'))
        except ValueError:
            c = 10
        try:
            r = int(os.getenv('AI_HTTP_READ_TIMEOUT', '25'))
        except ValueError:
            r = 25
        c = max(3, min(c, 60))
        r = max(5, min(r, 120))
        return (c, r)

    @staticmethod
    def validate_api_key(provider: str, api_key: str, force: bool = False) -> Tuple[bool, str]:
        """فحص صلاحية المفتاح بطلب خفيف جدًا (قائمة نماذج/استدعاء بـ token واحد).

        يُخزَّن في كاش بالذاكرة لـ TTL محدد لتجنّب الفحص المتكرر.
        يرجع: (ok, reason). reason للأدمن فقط — لا يُعرض للزائر.
        """
        prov = (provider or '').strip().lower()
        if prov == 'google_gemini':
            prov = 'google'
        key = (api_key or '').strip()
        if not prov or not key:
            return False, 'مفتاح غير مضبوط'
        cache_key = (prov, key[-8:])
        now = time.time()
        if not force:
            with _KEY_VALIDATION_LOCK:
                hit = _KEY_VALIDATION_CACHE.get(cache_key)
                if hit and hit[1] > now:
                    return hit[0], 'cached'
        try:
            timeout = (5, 8)
            if prov == 'openai':
                r = requests.get(
                    'https://api.openai.com/v1/models',
                    headers={'Authorization': f'Bearer {key}'},
                    timeout=timeout,
                )
                ok = r.status_code == 200
                if ok:
                    reason = ''
                else:
                    try:
                        err = r.json().get('error', {})
                        reason = err.get('message') or err.get('code') or f'HTTP {r.status_code}'
                    except:
                        reason = f'HTTP {r.status_code}'
            elif prov == 'anthropic':
                r = requests.get(
                    'https://api.anthropic.com/v1/models',
                    headers={
                        'x-api-key': key,
                        'anthropic-version': '2023-06-01',
                    },
                    timeout=timeout,
                )
                ok = r.status_code == 200
                if ok:
                    reason = ''
                else:
                    try:
                        err = r.json().get('error', {})
                        reason = err.get('message') or err.get('type') or f'HTTP {r.status_code}'
                    except:
                        reason = f'HTTP {r.status_code}'
            elif prov == 'google':
                r = requests.get(
                    f'https://generativelanguage.googleapis.com/v1beta/models?key={key}',
                    timeout=timeout,
                )
                ok = r.status_code == 200
                if ok:
                    reason = ''
                else:
                    try:
                        err = r.json().get('error', {})
                        reason = err.get('message') or err.get('status') or f'HTTP {r.status_code}'
                    except:
                        reason = f'HTTP {r.status_code}'
            else:
                return False, f'مزوّد غير مدعوم: {prov}'
        except requests.exceptions.Timeout:
            ok, reason = False, 'مهلة الاتصال انتهت'
        except Exception as e:
            ok, reason = False, f'خطأ اتصال: {str(e)[:80]}'
        ttl = _KEY_VALIDATION_TTL_OK if ok else _KEY_VALIDATION_TTL_BAD
        with _KEY_VALIDATION_LOCK:
            _KEY_VALIDATION_CACHE[cache_key] = (ok, now + ttl)
        return ok, reason

    @staticmethod
    def invalidate_key_cache(provider: str = '', api_key: str = ''):
        """تفريغ كاش الفحص — كليًا أو لمفتاح واحد."""
        with _KEY_VALIDATION_LOCK:
            if not provider and not api_key:
                _KEY_VALIDATION_CACHE.clear()
                return
            key_tail = (api_key or '').strip()[-8:]
            prov = (provider or '').strip().lower()
            if prov == 'google_gemini':
                prov = 'google'
            _KEY_VALIDATION_CACHE.pop((prov, key_tail), None)

    @staticmethod
    def get_tenant_model(tenant_id: int) -> Optional[AIModel]:
        """جلب النموذج المختار للتاجر، أو الافتراضي."""
        from app.models.ai_provider import AIProvider
        provider = AIProvider.query.filter_by(is_active=True).order_by(AIProvider.priority.asc()).first()
        if provider:
            model = AIModel.query.filter_by(provider_id=provider.id, is_active=True).first()
            if model: return model
        return AIModel.query.filter_by(is_default=True, is_active=True).first()

    @staticmethod
    def _get_api_key(provider: str, tenant_id: int = None) -> str:
        """جلب مفتاح API للمزوّد."""
        if not provider:
            return ''
            
        from app.models.ai_provider import AIProvider
        p = AIProvider.query.filter_by(name=provider, is_active=True).first()
        if p and getattr(p, 'api_key_decrypted', None):
            return getattr(p, 'api_key_decrypted')

        # المفتاح العام من SystemSetting أو متغيرات البيئة
        # يتم استخدامه للـ Admin AI (tenant_id is None) أو للتجار الذين يملكون اشتراكاً ورصيداً
        key_map = {
            'anthropic': 'AI_ANTHROPIC_KEY',
            'openai': 'AI_OPENAI_KEY',
            'google': 'AI_GOOGLE_KEY',
        }
        env_fallback = {
            'openai': 'OPENAI_API_KEY',
            'anthropic': 'ANTHROPIC_API_KEY',
            'google': 'GOOGLE_API_KEY',
        }
        setting_key = key_map.get(provider.lower())
        if setting_key:
            v = SystemSetting.get(setting_key, '').strip()
            if v:
                return v
            env_name = env_fallback.get(provider.lower())
            if env_name:
                ev = (os.getenv(env_name) or '').strip()
                if ev:
                    return ev
                try:
                    from flask import has_request_context, current_app

                    if has_request_context():
                        cv = (current_app.config.get(env_name) or '').strip()
                        if cv:
                            return cv
                except RuntimeError:
                    pass

        return ''

    @staticmethod
    def generate(
        tenant_id: int,
        user_message: str,
        system_prompt: str = '',
        history: List[Dict] = None,
        model_override: Optional[AIModel] = None,
    ) -> AIResult:
        """
        توليد رد من AI للتاجر المحدد مع دعم الانتقال التلقائي (Fallback) لأول مزود متوفر ومفعل.
        """
        history = history or []
        last_error = 'لا يوجد مزود AI متاح.'

        # إذا تم تحديد نموذج محدد بشكل إجباري، نستخدمه ونكتفي به بدون Fallback
        if model_override:
            return AIService._try_generate_with_model(
                model_override, tenant_id, user_message, system_prompt, history
            )

        from app.agents.model_resolver import ModelResolver
        resolved = ModelResolver.resolve(tenant_id)
        
        if not resolved:
            current_app.logger.error('[AIService] No Available AI Provider - Falling Back To Local Reply')
            return AIResult(success=False, error=last_error)

        model = AIModel.query.get(resolved.ai_model_db_id)
        if not model:
            return AIResult(success=False, error='Resolved model not found in DB')

        result = AIService._try_generate_with_model(
            model, tenant_id, user_message, system_prompt, history
        )
        
        if result.success:
            current_app.logger.info("AI Request Completed")
        else:
            current_app.logger.warning(f"AI Request Failed: {result.error}")
            
        return result

    @staticmethod
    def _try_generate_with_model(
        model: AIModel,
        tenant_id: int,
        user_message: str,
        system_prompt: str,
        history: List[Dict],
    ) -> AIResult:
        """استدعاء الموديل الخاص وإرجاع النتيجة أو الخطأ للاستمرار."""
        if not model.provider:
            return AIResult(success=False, error='مزود النموذج فارغ (None)')
            
        api_key = AIService._get_api_key(model.provider, tenant_id)
        if not api_key:
            return AIResult(success=False, error=f'مفتاح {model.provider} غير مضبوط')

        try:
            if model.provider == 'anthropic':
                result = AIService._call_anthropic(
                    api_key, model.model_id, system_prompt, history, user_message,
                )
            elif model.provider == 'openai':
                result = AIService._call_openai(
                    api_key, model.model_id, system_prompt, history, user_message,
                )
            elif model.provider == 'google':
                result = AIService._call_gemini(
                    api_key, model.model_id, system_prompt, history, user_message,
                )
            else:
                return AIResult(success=False, error=f'مزوّد غير مدعوم: {model.provider}')

            result.model_id = model.id
            result.provider = model.provider
            result.model_name = model.display_name
            return result

        except requests.exceptions.Timeout:
            return AIResult(success=False, error=f'انتهت مهلة الاستجابة من AI ({model.provider})')
        except Exception as e:
            return AIResult(success=False, error=f'خطأ: {str(e)[:100]}')

    # ========== Anthropic ==========
    @staticmethod
    def _call_anthropic(
        api_key: str, model_id: str, system_prompt: str,
        history: List[Dict], user_message: str,
    ) -> AIResult:
        """استدعاء Claude API."""
        messages = []

        # تحويل التاريخ
        for h in history[-10:]:  # آخر 10 رسائل
            role = 'assistant' if h.get('sender_type') == 'bot' else 'user'
            content = h.get('content', '').strip()
            if content:
                messages.append({'role': role, 'content': content})

        # الرسالة الحالية
        messages.append({'role': 'user', 'content': user_message})

        body = {
            'model': model_id,
            'max_tokens': 1024,
            'messages': messages,
        }
        if system_prompt:
            body['system'] = system_prompt

        resp = requests.post(
            'https://api.anthropic.com/v1/messages',
            headers={
                'x-api-key': api_key,
                'anthropic-version': '2023-06-01',
                'content-type': 'application/json',
            },
            json=body,
            timeout=AIService.http_timeout(),
        )

        if resp.status_code != 200:
            return AIResult(
                success=False,
                error=f'Claude API error {resp.status_code}: {resp.text[:200]}',
            )

        data = resp.json()
        text = ''
        for block in data.get('content', []):
            if block.get('type') == 'text':
                text += block.get('text', '')

        usage = data.get('usage', {})
        return AIResult(
            success=True,
            text=text.strip(),
            tokens_in=usage.get('input_tokens', 0),
            tokens_out=usage.get('output_tokens', 0),
        )

    # ========== OpenAI ==========
    @staticmethod
    def _call_openai(
        api_key: str, model_id: str, system_prompt: str,
        history: List[Dict], user_message: str,
    ) -> AIResult:
        """استدعاء GPT API."""
        messages = []
        if system_prompt:
            messages.append({'role': 'system', 'content': system_prompt})

        for h in history[-10:]:
            role = 'assistant' if h.get('sender_type') == 'bot' else 'user'
            content = h.get('content', '').strip()
            if content:
                messages.append({'role': role, 'content': content})

        messages.append({'role': 'user', 'content': user_message})

        resp = requests.post(
            'https://api.openai.com/v1/chat/completions',
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            },
            json={
                'model': model_id,
                'messages': messages,
                'max_tokens': 1024,
                'temperature': 0.7,
            },
            timeout=AIService.http_timeout(),
        )

        if resp.status_code != 200:
            return AIResult(
                success=False,
                error=f'OpenAI error {resp.status_code}: {resp.text[:200]}',
            )

        data = resp.json()
        text = data['choices'][0]['message']['content'].strip()
        usage = data.get('usage', {})

        return AIResult(
            success=True,
            text=text,
            tokens_in=usage.get('prompt_tokens', 0),
            tokens_out=usage.get('completion_tokens', 0),
        )

    # ========== Google Gemini ==========
    @staticmethod
    def _call_gemini(
        api_key: str, model_id: str, system_prompt: str,
        history: List[Dict], user_message: str,
    ) -> AIResult:
        """استدعاء Gemini API."""
        contents = []
        for h in history[-10:]:
            role = 'model' if h.get('sender_type') == 'bot' else 'user'
            content = h.get('content', '').strip()
            if content:
                contents.append({
                    'role': role,
                    'parts': [{'text': content}],
                })

        contents.append({
            'role': 'user',
            'parts': [{'text': user_message}],
        })

        body = {
            'contents': contents,
            'generationConfig': {
                'maxOutputTokens': 1024,
                'temperature': 0.7,
            },
        }
        if system_prompt:
            body['systemInstruction'] = {
                'parts': [{'text': system_prompt}],
            }

        url = f'https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={api_key}'
        resp = requests.post(
            url,
            headers={'Content-Type': 'application/json'},
            json=body,
            timeout=AIService.http_timeout(),
        )

        if resp.status_code != 200:
            return AIResult(
                success=False,
                error=f'Gemini error {resp.status_code}: {resp.text[:200]}',
            )

        data = resp.json()
        text = ''
        for cand in data.get('candidates', []):
            for part in cand.get('content', {}).get('parts', []):
                text += part.get('text', '')

        usage = data.get('usageMetadata', {})
        return AIResult(
            success=True,
            text=text.strip(),
            tokens_in=usage.get('promptTokenCount', 0),
            tokens_out=usage.get('candidatesTokenCount', 0),
        )


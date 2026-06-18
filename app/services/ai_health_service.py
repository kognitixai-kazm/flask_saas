"""
app/services/ai_health_service.py — فحص جاهزية الذكاء الاصطناعي لكل التجار.

يستخدم في لوحة المنصة لعرض تنبيه عند وجود تاجر:
- اختار مزوّد AI
- لكن المفتاح غير صالح / غير موجود.

التنفيذ يعتمد على Cache TTL داخل AIService حتى لا نضرب APIs خارجية في كل تحديث.
"""
from typing import List, Dict

from app.models.tenant import Tenant
from app.models.bot_config import BotConfig
from app.services.ai_service import AIService


class AIHealthService:

    @staticmethod
    def scan_tenants_ai(limit: int = 200) -> List[Dict]:
        """
        يرجع قائمة التجار الذين يحاولون استخدام AI لكنه لا يعمل.

        السبب الممكن:
        - chose_provider = ضبط provider بدون مفتاح
        - invalid_key   = المفتاح موجود لكنه غير صالح
        - fallback_only = ما اختار مفتاحاً لكن النموذج الافتراضي للمنصة بلا مفتاح
        """
        tenants = (
            Tenant.query.filter_by(status='active')
            .order_by(Tenant.id.asc())
            .limit(limit)
            .all()
        )
        problems: List[Dict] = []

        for tenant in tenants:
            bot = BotConfig.query.filter_by(tenant_id=tenant.id).first()

            # 1) تاجر اختار provider خاص فيه
            tenant_provider = (bot.ai_provider or '').strip().lower() if bot else ''
            tenant_key = (bot.ai_api_key or '').strip() if bot else ''

            if tenant_provider and tenant_provider not in ('', 'none'):
                if not tenant_key:
                    problems.append({
                        'tenant_id': tenant.id,
                        'tenant_name': tenant.business_name,
                        'tenant_slug': tenant.slug,
                        'provider': tenant_provider,
                        'reason': 'chose_provider',
                        'message': f'اختار {tenant_provider} لكن لم يدخل مفتاح API.',
                    })
                    continue

                ok, reason = AIService.validate_api_key(tenant_provider, tenant_key)
                if not ok:
                    problems.append({
                        'tenant_id': tenant.id,
                        'tenant_name': tenant.business_name,
                        'tenant_slug': tenant.slug,
                        'provider': tenant_provider,
                        'reason': 'invalid_key',
                        'message': f'مفتاح {tenant_provider} غير صالح ({reason}).',
                    })
                    continue
                # المفتاح يعمل ✓
                continue

            # 2) تاجر لم يضبط provider خاص → نعتمد على النموذج الافتراضي للمنصة
            try:
                default_model = AIService.get_tenant_model(tenant.id)
            except Exception:
                default_model = None
            if not default_model:
                continue  # لا توجد نماذج معدّة — مشكلة منصة، لا تاجر

            sys_key = AIService._get_api_key(default_model.provider, tenant_id=None)
            if not sys_key:
                problems.append({
                    'tenant_id': tenant.id,
                    'tenant_name': tenant.business_name,
                    'tenant_slug': tenant.slug,
                    'provider': default_model.provider,
                    'reason': 'platform_key_missing',
                    'message': (
                        f'يعتمد على {default_model.provider} الافتراضي لكن المفتاح العام للمنصة فارغ.'
                    ),
                })
                continue
            ok, reason = AIService.validate_api_key(default_model.provider, sys_key)
            if not ok:
                problems.append({
                    'tenant_id': tenant.id,
                    'tenant_name': tenant.business_name,
                    'tenant_slug': tenant.slug,
                    'provider': default_model.provider,
                    'reason': 'platform_key_invalid',
                    'message': f'المفتاح العام للمنصة غير صالح ({reason}).',
                })

        return problems

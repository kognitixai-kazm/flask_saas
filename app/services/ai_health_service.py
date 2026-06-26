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
        يرجع قائمة بالمشاكل الخاصة بالذكاء الاصطناعي.
        بما أن المفاتيح أصبحت مركزية، سيتم فحص مزود المنصة الافتراضي.
        """
        from app.models.ai_provider import AIProvider
        from app.services.ai_service import AIService
        
        problems: List[Dict] = []
        provider = AIProvider.query.filter_by(is_active=True).order_by(AIProvider.priority.asc()).first()
        
        if not provider:
            problems.append({
                'tenant_id': 0,
                'tenant_name': 'المنصة',
                'tenant_slug': 'platform',
                'provider': 'none',
                'reason': 'no_active_provider',
                'message': 'لا يوجد مزود ذكاء اصطناعي مفعل للمنصة.',
            })
            return problems
            
        key = getattr(provider, 'api_key_decrypted', None)
        if not key:
            problems.append({
                'tenant_id': 0,
                'tenant_name': 'المنصة',
                'tenant_slug': 'platform',
                'provider': provider.name,
                'reason': 'missing_platform_key',
                'message': f'مزود {provider.name} ليس لديه مفتاح API.',
            })
            return problems
            
        ok, reason = AIService.validate_api_key(provider.name, key, force=False)
        if not ok:
            problems.append({
                'tenant_id': 0,
                'tenant_name': 'المنصة',
                'tenant_slug': 'platform',
                'provider': provider.name,
                'reason': 'invalid_platform_key',
                'message': f'المفتاح العام للمنصة لمزود {provider.name} غير صالح ({reason}).',
            })
            
        return problems

"""
app/services/facility_memory_service.py — ذاكرة المنشأة
تقوم هذه الخدمة بتجميع بيانات المنشأة (حسب نوع الوكيل والنية)
لتغذية الـ System Prompt وتقليل استهلاك التوكنز (لا ترسل قاعدة البيانات كاملة).
"""
import logging
from app.models.tenant import Tenant
from app.models.bot_config import BotConfig
from app.models.agent_profile import AgentProfile

logger = logging.getLogger(__name__)

class FacilityMemoryService:
    
    @staticmethod
    def get_context_for_agent(tenant_id: int, agent_type: str) -> str:
        """
        جلب السياق المناسب للوكيل المحدد.
        agent_type: 'reception', 'contract', 'accounting', 'collection', 'router'
        """
        try:
            tenant = Tenant.query.get(tenant_id)
            if not tenant:
                return "Unknown Facility."
                
            bot_config = BotConfig.query.filter_by(tenant_id=tenant_id).first()
            agent_profile = AgentProfile.query.filter_by(tenant_id=tenant_id, agent_type=agent_type).first()
            
            # معلومات أساسية
            lines = [
                f"اسم المنشأة: {tenant.business_name}",
            ]
            
            # معلومات الوكيل الحالي
            if agent_profile:
                if agent_profile.agent_name:
                    lines.append(f"اسمك كوكيل: {agent_profile.agent_name}")
                if agent_profile.tone:
                    lines.append(f"نبرة الحديث المطلوبة: {agent_profile.tone}")
                if agent_profile.custom_instructions:
                    lines.append(f"تعليمات خاصة بك: {agent_profile.custom_instructions}")
            
            # تعليمات عامة للبوت
            if bot_config:
                if bot_config.custom_instructions:
                    lines.append(f"تعليمات عامة للمنشأة: {bot_config.custom_instructions}")
                if bot_config.blocked_topics:
                    lines.append(f"مواضيع ممنوع الحديث عنها: {bot_config.blocked_topics}")
                    
            # تخصيص حسب الوكيل
            if agent_type == 'reception':
                # معلومات تفيد الاستقبال
                ad = tenant.activity_data or {}
                if ad.get('hotel_mode'):
                    lines.append(f"نظام الإيجار: {ad.get('hotel_mode')}")
                lines.append("تنبيه: يجب أخذ تواريخ الوصول والمغادرة وأسئلة العميل الأساسية قبل تحويل العميل لوكيل العقود لإتمام الحجز.")
                
            elif agent_type == 'contract':
                # معلومات تفيد التعاقد والدفع
                lines.append(f"طرق الدفع المتاحة للتحويل البنكي:")
                if tenant.bank_name:
                    lines.append(f"- البنك: {tenant.bank_name}")
                    lines.append(f"- الحساب: {tenant.bank_account_number} | الآيبان: {tenant.bank_iban}")
                    lines.append(f"- باسم: {tenant.bank_account_name}")
                lines.append("يجب إنشاء رابط الدفع أو التأكد من استلام الحوالة قبل إصدار العقد النهائي.")
                
            elif agent_type == 'accounting':
                lines.append("أنت وكيل المراجعة المالية والمحاسبية. يجب عليك تحليل طرق الحسبة وتقديم تقارير دقيقة وصلاحيات إدارية للمراجعة.")
                
            elif agent_type == 'collection':
                lines.append("أنت مسؤول عن التحصيل. قم بمتابعة المتأخرات بلباقة واحترافية وتقديم بيانات التحصيل.")

            return "\n".join(lines)
            
        except Exception as e:
            logger.error(f"[FacilityMemoryService] Error generating context: {e}")
            return ""

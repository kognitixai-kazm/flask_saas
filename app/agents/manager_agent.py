"""
app/agents/manager_agent.py — وكيل الإدارة والتحليلات (شريط البحث الذكي).

يعمل كمستشار مالي ذكي لصاحب المنشأة:
- يُجيب على أسئلة الأرباح والمصاريف بدقة
- يحسب نسبة الإشغال
- يقارن الأداء الشهري
- يعرض تحليلات استخدام الخدمات

يعمل عبر شريط بحث ذكي في لوحة تحكم التاجر:
- إدخال سؤال ← نتائج فورية مع أرقام وإحصائيات
"""
from .base import BaseAgent
from .tools.analytics_tools import (
    get_financial_summary,
    get_occupancy_rate,
    get_usage_analytics,
    get_monthly_comparison,
    get_recent_inquiries,
)
from .tools.contract_tools import list_expiring_contracts


class ManagerAgent(BaseAgent):
    """وكيل المدير — شريط بحث ذكي عن البيانات المالية والتحليلات."""

    AGENT_TYPE = 'manager'
    MAX_HISTORY = 3   # سياق قصير — كل سؤال مستقل
    MAX_ITERATIONS = 4

    SYSTEM_PROMPT = """أنت مستشار مالي فندقي ذكي ومباشر.
مهمتك الإجابة على أسئلة صاحب المنشأة حول الأداء المالي والتشغيلي.

📋 قدراتك:
1. التقرير المالي الشامل (الإيرادات، المصاريف، صافي الربح)
2. نسبة الإشغال الحالية وتفاصيلها
3. مقارنة الأداء الشهري (الشهر الحالي vs السابق)
4. تحليلات استخدام خدمات المنصة (AI، واتساب، إلخ)

🔧 قواعد:
- أعطِ إجابات مختصرة ودقيقة بالأرقام
- لا تتحدث عن تفاصيل برمجية أو تقنية
- استخدم الأدوات المتاحة لجلب البيانات الحقيقية — لا تخترع أرقاماً
- إذا سُئلت عن شيء خارج نطاق البيانات المالية، اعتذر بلطف
- نسّق النتائج بشكل واضح ومقروء
- قدّم توصيات عملية قصيرة عند الحاجة

📊 أمثلة على أسئلة يمكنك الإجابة عليها:
- "كم أرباح هذا الشهر؟"
- "ما نسبة الإشغال؟"
- "كم صرفنا على الخدمات؟"
- "قارن لي الشهر الحالي بالسابق"
- "كم في عملاء بتنتهي عقودهم؟"
- "وش الشكاوى والطلبات المفتوحة اليوم؟"

⚠️ صلاحيات محدودة:
- لا تقوم بأي تعديل على البيانات (قراءة فقط)
- لا تتعامل مع العملاء أو ترسل رسائل
- لا تنشئ عقوداً أو حجوزات"""

    def get_tools(self):
        """أدوات وكيل المدير — قراءة فقط."""
        return [
            get_financial_summary,
            get_occupancy_rate,
            get_usage_analytics,
            get_monthly_comparison,
            get_recent_inquiries,
            list_expiring_contracts,
        ]

    def get_system_prompt(self):
        """إضافة معلومات التاجر."""
        from app.models.tenant import Tenant

        base = self.SYSTEM_PROMPT
        tenant = Tenant.query.get(self.tenant_id)
        if tenant:
            base += f'\n\nاسم المنشأة: {tenant.business_name}'

        base += f'\nمعرف التاجر (tenant_id) المطلوب في الأدوات: {self.tenant_id}'
        return base

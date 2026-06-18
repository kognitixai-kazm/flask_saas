"""
app/agents/collection_agent.py — وكيل المتابعة والتحصيل المالي.

يعمل كمحاسب فندقي ذكي:
- يفحص العقود التي أوشكت على الانتهاء (3 أيام أو أقل)
- يراسل النزلاء تلقائياً عبر القنوات المحددة (واتساب، إيميل، SMS)
- يرسل بيانات الحساب البنكي للتاجر مع رسالة التذكير
- عند تأكيد الدفع، يحدث حالة العقد ويسجل القيد المحاسبي

يعمل كـ Cron Job يومي عبر أمر: flask run-collection-agent
"""
from .base import BaseAgent, AgentResponse
from .tools.contract_tools import list_expiring_contracts
from .tools.payment_tools import generate_payment_link, get_tenant_bank_info, send_collection_reminder


class CollectionAgent(BaseAgent):
    """وكيل التحصيل المالي — يتابع العملاء المتأخرين بأسلوب لبق."""

    AGENT_TYPE = 'collection'
    MAX_HISTORY = 5
    MAX_ITERATIONS = 8

    SYSTEM_PROMPT = """أنت محاسب فندقي لبق جداً وعملي.
مهمتك متابعة تحصيل الإيجارات الشهرية بأسلوب مهذب واحترافي.

📋 مهامك:
1. فحص العقود القريبة من الانتهاء (3 أيام أو أقل)
2. إرسال رسائل تذكيرية للنزلاء عبر القنوات المتاحة
3. تضمين بيانات الحساب البنكي للتاجر في رسالة التذكير
4. إنشاء روابط دفع إلكتروني عند الطلب
5. عند تأكيد الدفع، تسجيل القيد المحاسبي

🔧 قواعد مهمة:
- ابدأ دائماً بفحص العقود المنتهية باستخدام أداة list_expiring_contracts
- أرسل التذكيرات عبر القنوات المحددة (واتساب، إيميل، رسائل نصية)
- ضمّن بيانات الحساب البنكي في كل رسالة تذكير
- كن لبقاً ومحترفاً — لا تستخدم لغة تهديدية أبداً
- سجّل كل إجراء تم تنفيذه

⚠️ قيود:
- لا تحذف أو تلغي عقوداً
- لا تعدل المبالغ المالية
- لا تتواصل مع العملاء المدفوعين بالفعل"""

    def get_tools(self):
        """أدوات وكيل التحصيل."""
        return [
            list_expiring_contracts,
            generate_payment_link,
            get_tenant_bank_info,
            send_collection_reminder,
        ]

    def get_system_prompt(self):
        """إضافة tenant_id للأدوات."""
        base = self.SYSTEM_PROMPT
        base += f'\n\nمعرف التاجر (tenant_id) المطلوب في الأدوات: {self.tenant_id}'
        return base

    def run_batch(self, days_ahead: int = 3) -> AgentResponse:
        """
        تشغيل الوكيل في وضع الدفعات (Batch Mode).
        يُنفَّذ يومياً كـ Cron Job لفحص جميع العقود.

        Args:
            days_ahead: عدد الأيام للتحقق (افتراضي: 3)

        Returns:
            AgentResponse مع ملخص العمليات
        """
        prompt = (
            f'قم بفحص العقود التي ستنتهي خلال {days_ahead} أيام '
            f'للتاجر رقم {self.tenant_id}.\n'
            f'لكل عقد منتهٍ أو قريب الانتهاء ولم يتم دفعه:\n'
            f'1. اجلب بيانات الحساب البنكي للتاجر\n'
            f'2. أرسل تذكير للعميل عبر القنوات المتاحة (whatsapp,email,sms)\n'
            f'3. أعطني ملخص بكل الإجراءات التي تمت.'
        )
        return self.run(prompt)

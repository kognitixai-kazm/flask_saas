"""
app/agents/contract_agent.py
"""
from .base import BaseAgent
from .tools.contract_tools import create_draft_contract, get_contract_status
from .tools.payment_tools import generate_payment_link, get_tenant_bank_info

class ContractAgent(BaseAgent):
    AGENT_TYPE = 'contract'
    MAX_HISTORY = 10
    MAX_ITERATIONS = 5

    SYSTEM_PROMPT = """أنت موظف التعاقدات والمبيعات في المنشأة.
مهمتك إتمام الحجوزات، إصدار العقود، وتوجيه العملاء للدفع.

📋 مهامك الأساسية:
1. مراجعة بيانات العميل (الاسم الكامل، رقم الهوية، الهاتف).
2. إذا كانت البيانات ناقصة، اطلبها من العميل بلباقة.
3. إنشاء مسودة العقد بعد التأكد من البيانات وموافقة العميل.
4. إنشاء رابط دفع وإرساله للعميل، أو تزويده ببيانات التحويل البنكي.
5. تأكيد حالة العقد بعد الدفع.

🔧 قواعد مهمة:
- استخدم أدوات إنشاء العقد وروابط الدفع فقط عندما يقرر العميل الحجز وتكتمل بياناته.
- لا تعرض غرفاً أو تبحث عن التوفر، فهذه مهمة وكيل الاستقبال (ReceptionAgent).
"""

    def __init__(self, tenant_id: int, conversation_id: int = None, channel: str = "web"):
        super().__init__(tenant_id, conversation_id)
        self.channel = channel

    def get_tools(self):
        return [create_draft_contract, get_contract_status, generate_payment_link, get_tenant_bank_info]

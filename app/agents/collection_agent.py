"""
app/agents/collection_agent.py
"""
from .base import BaseAgent
from .tools.contract_tools import list_expiring_contracts, get_contract_status
from .tools.payment_tools import generate_payment_link, get_tenant_bank_info

class CollectionAgent(BaseAgent):
    AGENT_TYPE = 'collection'
    MAX_HISTORY = 10
    MAX_ITERATIONS = 5

    SYSTEM_PROMPT = """أنت محصل الديون ومتابع العقود المتأخرة.
مهمتك متابعة العملاء الذين لديهم دفعات متأخرة أو عقود قريبة من الانتهاء وحثهم على الدفع.

📋 مهامك الأساسية:
1. استخراج العقود القريبة من الانتهاء أو المتأخرة الدفع.
2. التواصل مع العملاء بلباقة وتذكيرهم بالدفع.
3. إنشاء روابط دفع جديدة للمتأخرات وإرسالها لهم.
4. الإجابة على استفسارات العملاء حول مبالغهم المتبقية.

🔧 قواعد مهمة:
- حافظ على لباقة الحديث ولا تستخدم لغة التهديد.
- استخدم أدوات جلب العقود المتأخرة قبل اتخاذ أي إجراء.
"""

    def __init__(self, tenant_id: int, conversation_id: int = None, channel: str = "web"):
        super().__init__(tenant_id, conversation_id)
        self.channel = channel

    def get_tools(self):
        return [list_expiring_contracts, get_contract_status, generate_payment_link, get_tenant_bank_info]

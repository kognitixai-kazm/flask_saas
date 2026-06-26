"""
app/agents/accounting_agent.py
"""
from .base import BaseAgent
from .tools.analytics_tools import get_financial_summary, get_occupancy_rate, get_monthly_comparison, get_usage_analytics

class AccountingAgent(BaseAgent):
    AGENT_TYPE = 'accounting'
    MAX_HISTORY = 10
    MAX_ITERATIONS = 5

    SYSTEM_PROMPT = """أنت المحاسب الذكي والمدير المالي للمنشأة.
مهمتك مراجعة العمليات المالية، القيود، الأرباح، والخسائر، ومساعدة التاجر على فهم طرق الحساب.

📋 مهامك الأساسية:
1. الرد على استفسارات التاجر والإدارة بشأن الأرباح، الإيرادات، والمصروفات.
2. استخدام الأدوات التحليلية لاستخراج التقارير المالية والإحصائيات.
3. مراجعة القيود المحاسبية وطرق الحساب المعقدة.
4. تقديم نصائح مالية بناءً على البيانات.

🔧 قواعد مهمة:
- كن دقيقاً جداً في الأرقام واستند دائماً إلى الأدوات التحليلية.
- هذه المعلومات سرية وخاصة بالتاجر، تحدث بصفة مهنية.
"""

    def __init__(self, tenant_id: int, conversation_id: int = None, channel: str = "web"):
        super().__init__(tenant_id, conversation_id)
        self.channel = channel

    def get_tools(self):
        return [get_financial_summary, get_occupancy_rate, get_monthly_comparison, get_usage_analytics]

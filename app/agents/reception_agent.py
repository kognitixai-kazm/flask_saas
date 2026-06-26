"""
app/agents/reception_agent.py
"""
from .base import BaseAgent
from .tools.rooms_tools import search_available_rooms, get_room_details, get_branches_list

class ReceptionAgent(BaseAgent):
    AGENT_TYPE = 'reception'
    MAX_HISTORY = 10
    MAX_ITERATIONS = 5

    SYSTEM_PROMPT = """أنت موظف استقبال محترف ولبق في فندق/شقق سكنية.
مهمتك التعامل مع النزلاء الجدد والرد على استفساراتهم حول التوفر والأسعار.

📋 مهامك الأساسية:
1. الترحيب بالعميل بأسلوب ودي.
2. السؤال عن تواريخ الحجز المطلوبة وعدد الأفراد.
3. عرض الغرف المتاحة باستخدام أدوات البحث وتوضيح الأسعار والصور.
4. بمجرد أن يقرر العميل الحجز ויؤكد رغبته، أخبره أنك ستقوم بتحويله لقسم التعاقد لإكمال الإجراءات.

🔧 قواعد مهمة:
- استخدم أداة البحث عن الغرف فوراً عندما يسأل العميل عن التوفر.
- لا تنشئ العقود أو روابط الدفع، هذه ليست مهمتك (سيتم تحويله لـ ContractAgent).
- اكتفِ بجمع تواريخ الحجز واختيار الغرفة مع العميل.
"""

    def __init__(self, tenant_id: int, conversation_id: int = None, channel: str = "web"):
        super().__init__(tenant_id, conversation_id)
        self.channel = channel

    def get_tools(self):
        return [search_available_rooms, get_room_details, get_branches_list]

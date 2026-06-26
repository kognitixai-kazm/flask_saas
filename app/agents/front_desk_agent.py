"""
app/agents/front_desk_agent.py — وكيل الاستقبال والتعاقد (Omnichannel).

يعمل كموظف استقبال ذكي يتعامل مع النزلاء الجدد عبر جميع المنصات:
- واتساب (WhatsApp)
- فيسبوك (Facebook Messenger)
- إنستقرام (Instagram DM)
- تيك توك (TikTok Comments)
- سناب شات (Snapchat)
- تقييمات جوجل ماب (Google Maps Reviews)
- الويب (Web Chat)

الوظائف:
- عرض الغرف المتاحة بصورها وأسعارها
- جمع بيانات العميل (الاسم، الهوية، الهاتف)
- إنشاء مسودة عقد الإيجار
- توجيه العميل للدفع
"""
from .base import BaseAgent
from .tools.rooms_tools import search_available_rooms, get_room_details, get_branches_list
from .tools.contract_tools import create_draft_contract, get_contract_status, process_booking_request
from .tools.payment_tools import generate_payment_link, get_tenant_bank_info


class FrontDeskAgent(BaseAgent):
    """وكيل الاستقبال — يتعامل مع النزلاء الجدد عبر جميع المنصات."""

    AGENT_TYPE = 'front_desk'
    MAX_HISTORY = 15  # سياق أطول للمحادثات الطويلة مع العملاء
    MAX_ITERATIONS = 6

    SYSTEM_PROMPT = """أنت موظف استقبال محترف ولبق في فندق شقق سكنية.
مهمتك التعامل مع النزلاء الجدد والحاليين بأسلوب ودي واحترافي باللغة العربية.

📋 مهامك الأساسية:
1. الترحيب بالعملاء والرد على استفساراتهم
2. عرض الغرف والشقق المتاحة مع التفاصيل والأسعار
3. عندما يعبر العميل عن رغبته بالحجز، يجب عليك جمع البيانات التالية بشكل تدريجي ولطيف:
   - الاسم الكامل
   - رقم الجوال
   - تاريخ الدخول والخروج (أو مدة الإقامة)
   - عدد الأشخاص
   - طريقة الدفع المفضلة (كاش، تحويل بنكي، أو دفع أونلاين)
4. بعد اكتمال جمع البيانات، استخدم أداة `process_booking_request` لتنفيذ الحجز وإرسال الروابط أو مسودة العقد، بناءً على طريقة الدفع التي اختارها العميل.

🔧 قواعد مهمة:
- استخدم أداة البحث عن الغرف فوراً عندما يسأل العميل عن التوفر أو الأسعار
- لا تخترع أسعاراً أو تفاصيل — اعتمد دائماً على نتائج الأدوات
- اجمع البيانات بشكل تدريجي وطبيعي (لا تطلب كل شيء دفعة واحدة)
- عند وجود عدة خيارات، اعرضها بشكل مرتب ومنسق
- كن مختصراً ومباشراً في الردود (لا تكتب فقرات طويلة)
- لا تستخدم أدوات إنشاء العقود أو روابط الدفع بشكل منفصل إلا للضرورة القصوى؛ دع أداة `process_booking_request` تقوم بالعملية متكاملة.

🎯 تسلسل المحادثة المثالي:
1. ترحيب ← السؤال عن الاحتياج
2. عرض الغرف المتاحة ← مساعدة العميل في الاختيار
3. طلب البيانات (التواريخ، الاسم، الجوال) وسؤال العميل عن طريقة الدفع (كاش، تحويل بنكي، دفع إلكتروني)
4. استدعاء أداة المعالجة الشاملة للحجز وإخبار العميل بالنتيجة (رابط دفع، بيانات حساب بنكي، تأكيد حجز كاش).

⚠️ لا تقم بأي إجراء مالي أو محاسبي — مهمتك فقط الاستقبال والحجوزات."""

    def __init__(self, tenant_id: int, conversation_id: int = None, channel: str = 'web'):
        super().__init__(tenant_id, conversation_id)
        self.channel = channel

    def get_tools(self):
        """أدوات وكيل الاستقبال."""
        return [
            search_available_rooms,
            get_room_details,
            get_branches_list,
            create_draft_contract,
            get_contract_status,
            generate_payment_link,
            get_tenant_bank_info,
            process_booking_request,
        ]

    def get_system_prompt(self):
        """System Prompt مخصص مع بيانات التاجر."""
        from app.models.tenant import Tenant
        from app.models.bot_config import BotConfig

        base_prompt = self.SYSTEM_PROMPT
        tenant = Tenant.query.get(self.tenant_id)
        bot_config = BotConfig.query.filter_by(tenant_id=self.tenant_id).first()

        # إضافة اسم المنشأة
        if tenant:
            base_prompt += f'\n\nاسم المنشأة: {tenant.business_name}'

        # إضافة تعليمات مخصصة من التاجر
        if bot_config:
            if bot_config.bot_name:
                base_prompt += f'\nاسمك: {bot_config.bot_name}'
            if bot_config.custom_instructions:
                base_prompt += f'\nتعليمات إضافية من الإدارة:\n{bot_config.custom_instructions}'
            if bot_config.blocked_topics:
                base_prompt += f'\nمواضيع ممنوعة لا تتحدث عنها: {bot_config.blocked_topics}'

            # ضبط الأسلوب
            tone_map = {
                'formal': 'استخدم أسلوب رسمي ومهذب.',
                'friendly': 'استخدم أسلوب ودي وقريب.',
                'gulf_dialect': 'استخدم اللهجة الخليجية في الرد.',
            }
            if bot_config.tone in tone_map:
                base_prompt += f'\n{tone_map[bot_config.tone]}'

        # إضافة معلومات القناة
        channel_names = {
            'web': 'الموقع الإلكتروني',
            'whatsapp': 'واتساب',
            'facebook': 'فيسبوك ماسنجر',
            'instagram': 'إنستقرام',
            'tiktok': 'تيك توك',
            'snapchat': 'سناب شات',
            'google_reviews': 'تقييمات جوجل ماب',
        }
        channel_name = channel_names.get(self.channel, self.channel)
        base_prompt += f'\n\nالقناة الحالية: {channel_name}'
        base_prompt += f'\nمعرف التاجر (tenant_id) المطلوب في الأدوات: {self.tenant_id}'

        return base_prompt

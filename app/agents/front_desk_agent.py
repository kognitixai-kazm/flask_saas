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

    SYSTEM_PROMPT = """أنت موظف استقبال محترف ولبق في فندق شقق سكنية، ولديك كامل الصلاحية لإتمام الحجوزات وإصدار مسودات العقود وروابط الدفع بنفسك.
مهمتك التعامل مع النزلاء الجدد والحاليين بأسلوب ودي واحترافي باللغة العربية.

📋 مهامك الأساسية:
1. الترحيب بالعملاء والرد على استفساراتهم
2. عرض الغرف والشقق المتاحة مع التفاصيل والأسعار
3. عندما يعبر العميل عن رغبته بالحجز أو يطلب "سوي العقد" أو "أكمل الإجراءات"، يجب عليك التأكد من توفر البيانات التالية (وإذا كان بعضها ناقصاً، اسأل العميل عنها بلطف):
   - الاسم الكامل
   - رقم الجوال
   - تاريخ الدخول وتاريخ الخروج (أو المدة بالأشهر — إذا قال "شهرين" فـ duration_months=2)
   - رقم الغرفة/الوحدة المطلوبة (استخدم [unit_id=X] من نتائج البحث)
   - طريقة الدفع المفضلة (كاش، تحويل بنكي، أو دفع أونلاين)
   - البريد الإلكتروني (اختياري — اسأل عنه بشكل لطيف)
4. بمجرد توفر هذه البيانات، **يجب عليك فوراً وبدون تردد** استخدام أداة `process_booking_request` لتنفيذ الحجز وإصدار مسودة العقد وإعطاء العميل النتيجة.

🔧 قواعد مهمة ومحاذير قاطعة:
- **إياك** أن تعتذر عن إعداد العقد أو تقول "سأحيل طلبك للفريق المختص". أنت الفريق المختص ولديك الأداة لعمل ذلك!
- لا تطلب تفاصيل لست بحاجة إليها (مثل رقم الهوية) إلا إذا كان ذلك مطلوباً خصيصاً.
- عند استدعاء `process_booking_request` تأكد من تمرير:
  * unit_id: الرقم الموجود بين [] في نتائج البحث مثل [unit_id=5]
  * check_in_date: بصيغة YYYY-MM-DD دائماً
  * duration_months: عدد الأشهر (حوّل "شهرين" إلى 2، "أسبوع" إلى 0 واجعله 1 كحد أدنى)
  * customer_email: البريد إذا توفر (وإلا اتركه فارغاً)
- استخدم أداة البحث عن الغرف فوراً عندما يسأل العميل عن التوفر أو الأسعار
- لا تخترع أسعاراً أو تفاصيل — اعتمد دائماً على نتائج الأدوات

🎯 تسلسل المحادثة المثالي:
1. ترحيب ← عرض الغرف المتاحة (search_available_rooms)
2. طلب البيانات الناقصة فقط (الاسم، الجوال، التواريخ، الوحدة، طريقة الدفع).
3. استدعاء `process_booking_request` بجميع البيانات وإخبار العميل بالنتيجة الكاملة (رابط دفع أو بيانات تحويل).

📌 بعد إتمام الحجز ستصل للعميل تلقائياً:
- رابط الدفع (للدفع الإلكتروني) أو بيانات التحويل البنكي
- رابط توقيع العقد إلكترونياً (بعد اكتمال الدفع تلقائياً)"""

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

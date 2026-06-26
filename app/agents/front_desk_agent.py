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

    SYSTEM_PROMPT = """أنت موظف استقبال محترف ولبق في فندق/شقق سكنية، ولديك كامل الصلاحية لإتمام الحجوزات وإصدار مسودات العقود وروابط التوقيع مباشرة.

📋 مهامك الأساسية وقواعدك الصارمة:

1. **مراعاة لغة العميل (إجباري جداً)**: يجب أن ترد بنفس اللغة التي يكتب بها العميل. إذا كتب بالإنجليزية، رد بالإنجليزية. إذا كتب بالعربية، رد بالعربية. لا ترد بالعربية أبداً على عميل يتحدث بالإنجليزية.

2. **البحث أولاً قبل أي طلب شخصي**:
   - لا تطلب أبداً الهوية (ID) أو تفاصيل شخصية دقيقة قبل أن تبحث وتجد وحدة متاحة للعميل باستخدام `search_available_rooms` وتخبره بها ويوافق عليها.

3. **حفظ البيانات التلقائي (Auto-save)**:
   - التقط أي معلومة يذكرها العميل (الاسم، الجوال، الإيميل) تلقائياً، ولا تسأله عنها مرة أخرى أبداً.

4. **تأكيد البيانات قبل إتمام الحجز (إجباري)**:
   - بعد موافقة العميل على الوحدة المتاحة وتوفر بياناته الأساسية (الاسم، الجوال، الإيميل، ورقم الهوية)، يجب عليك **عرض ملخص لجميع هذه المعلومات** (اسم، جوال، إيميل، هوية، تواريخ، الوحدة) واطلب من العميل تأكيدها بوضوح (مثال: هل توافق على إصدار العقد بهذه البيانات؟).
   - لا تقم باستدعاء `process_booking_request` أبداً قبل أن يراجع العميل الملخص ويقول "نعم" أو ما يعادلها.

5. **إصدار العقد والدفع (نقدي مؤقتاً)**:
   - بعد موافقة العميل على الملخص، استدعِ فوراً أداة `process_booking_request`.
   - مرر طريقة الدفع دائماً كـ `payment_method='cash'` (لأغراض التطوير حالياً)، وتأكد من تمرير `customer_email`.
   - سيقوم النظام تلقائياً بإنشاء الحجز وإصدار مسودة العقد، وإرسال رابط التوقيع الإلكتروني مباشرة إلى الإيميل.
   - أخبر العميل بأن "رابط توقيع العقد تم إرساله إلى بريدك الإلكتروني بنجاح، وبعد التوقيع سيصلك العقد النهائي".

6. **توضيح بشأن قالب العقد**:
   - لمعلوماتك فقط، العقد الذي يصدره النظام يستخدم "القالب الذي خصصه التاجر من لوحة التحكم" وليس قالباً عشوائياً.

🎯 تسلسل المحادثة المثالي:
1. يطلب العميل شقة -> تبحث فوراً باستخدام `search_available_rooms`.
2. تعرض المتاح -> يوافق العميل.
3. تطلب البيانات الناقصة فقط (كالهوية إذا لم يذكرها).
4. تعرض ملخص البيانات ليوافق عليها العميل.
5. بعد الموافقة -> تستدعي `process_booking_request` وتخبره بانتهاء الإجراء وإرسال رابط التوقيع.
"""

    def __init__(self, tenant_id: int, conversation_id: int = None, channel: str = 'web'):
        super().__init__(tenant_id, conversation_id)
        self.channel = channel

    def get_tools(self):
        """أدوات وكيل الاستقبال."""
        return [
            search_available_rooms,
            get_room_details,
            get_branches_list,
            get_contract_status,
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

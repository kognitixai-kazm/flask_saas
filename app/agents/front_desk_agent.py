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
from .tools.rooms_tools import search_available_rooms, get_room_details, get_branches_list, lock_unit_selection
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

3. **تثبيت الوحدة (إجباري جداً ومهم)**:
   - فور موافقة العميل المبدئية على وحدة معينة، يجب عليك فوراً استدعاء أداة `lock_unit_selection` لحفظ الوحدة في جلسة المحادثة، قبل طلب أي بيانات أخرى.
   - يُمنع منعاً باتاً تغيير الوحدة المختارة أو البحث من جديد إلا إذا رفضها العميل بوضوح أو أصبحت الوحدة غير متاحة (حُجزت من قبل شخص آخر).
   - يجب أن تعتمد ردودك دائماً على الوحدة المثبتة في الجلسة.

4. **حفظ البيانات التلقائي (Auto-save)**:
   - التقط أي معلومة يذكرها العميل (الاسم، الجوال، الإيميل) تلقائياً، ولا تسأله عنها مرة أخرى أبداً.

5. **تأكيد البيانات قبل إتمام الحجز (إجباري)**:
   - بعد موافقة العميل وتثبيت الوحدة، وتوفر بياناته الأساسية (الاسم، الجوال، الإيميل، ورقم الهوية)، يجب عليك **عرض ملخص لجميع هذه المعلومات** (اسم، جوال، إيميل، هوية، تواريخ، الوحدة المثبتة) واطلب من العميل تأكيدها بوضوح.
   - لا تقم باستدعاء `process_booking_request` أبداً قبل أن يراجع العميل الملخص ويقول "نعم" أو ما يعادلها.

6. **إصدار العقد والدفع (نقدي مؤقتاً)**:
   - بعد موافقة العميل على الملخص، استدعِ فوراً أداة `process_booking_request`.
   - مرر طريقة الدفع دائماً كـ `payment_method='cash'` (لأغراض التطوير حالياً)، وتأكد من تمرير `customer_email`.
   - سيقوم النظام تلقائياً بإنشاء الحجز وإصدار مسودة العقد، وإرسال رابط التوقيع الإلكتروني مباشرة إلى الإيميل.
   - أخبر العميل بأن "رابط توقيع العقد تم إرساله إلى بريدك الإلكتروني بنجاح، وبعد التوقيع سيصلك العقد النهائي".

6. **توضيح بشأن قالب العقد**:
   - لمعلوماتك فقط، العقد الذي يصدره النظام يستخدم "القالب الذي خصصه التاجر من لوحة التحكم" وليس قالباً عشوائياً.

🎯 تسلسل المحادثة المثالي:
1. يطلب العميل شقة -> تبحث فوراً باستخدام `search_available_rooms`.
2. تعرض المتاح -> يوافق العميل.
3. تستدعي فوراً `lock_unit_selection` لتثبيت الوحدة.
4. تطلب البيانات الناقصة فقط (كالهوية إذا لم يذكرها).
5. تعرض ملخص البيانات (بما فيها الوحدة المثبتة) ليوافق عليها العميل.
6. بعد الموافقة -> تستدعي `process_booking_request` وتخبره بإرسال رابط التوقيع.
"""

    def __init__(self, tenant_id: int, conversation_id: int = None, channel: str = 'web'):
        super().__init__(tenant_id, conversation_id)
        self.channel = channel

    def get_tools(self):
        """أدوات وكيل الاستقبال."""
        return [
            search_available_rooms,
            lock_unit_selection,
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

        # جلب الوحدة المثبتة إذا وجدت لمنع التغيير العشوائي
        from app.models.conversation import Conversation
        if self.conversation_id:
            conv = Conversation.query.get(self.conversation_id)
            if conv and conv.extra_data and 'booking_state' in conv.extra_data:
                state = conv.extra_data['booking_state']
                selected_unit_id = state.get('selected_unit_id')
                if selected_unit_id:
                    from app.models.hotel_models import Unit
                    unit = Unit.query.filter_by(id=selected_unit_id, tenant_id=self.tenant_id).first()
                    if unit and unit.is_available and unit.status == 'available':
                        base_prompt += f'\n\n[حالة الجلسة - هاااام جداً]: لقد قام العميل باختيار وتثبيت الوحدة (رقم {unit.unit_number} - {unit.type_label} | unit_id={unit.id}) في هذه الجلسة. يُمنع منعاً باتاً تغيير هذه الوحدة أو اقتراح بدائل. اعتمد عليها في الحجز والعقد.'
                    else:
                        base_prompt += f'\n\n[تنبيه هام]: الوحدة التي اختارها العميل سابقاً (unit_id={selected_unit_id}) لم تعد متاحة الآن! يجب إبلاغ العميل والاعتذار فوراً، ثم البحث عن بديل.'

        return base_prompt

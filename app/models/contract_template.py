"""
app/models/contract_template.py — قالب عقد قابل للتخصيص.

كل تاجر ينشئ قوالب عقود (مثل: عقد إيجار شهري، عقد إيجار يومي).
كل قالب يحدد:
- الحقول المطلوبة من العميل (اسم، هوية، صور...)
- شروط الدفع (كامل / جزئي)
- طريقة توليد العقد (PDF تلقائي / API خارجي)
- ربط مع نظام التاجر (لو موجود)
"""
from datetime import datetime
from ..extensions import db


class ContractTemplate(db.Model):
    """قالب عقد قابل للتخصيص لكل تاجر."""
    __tablename__ = 'contract_templates'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)

    # ========== التعريف ==========
    name = db.Column(db.String(200), nullable=False)
    # contract_type: monthly_rental | daily_rental | service | custom
    contract_type = db.Column(db.String(50), default='monthly_rental')

    description = db.Column(db.Text, default='')
    is_active = db.Column(db.Boolean, default=True)

    # ========== مصدر التوليد (الجديد) ==========
    # internal: قالب المنصة الجاهز (يستخدم شعار + لون + اسم نشاط التاجر)
    # external: نظام التاجر الخارجي عبر API
    provider = db.Column(db.String(20), default='internal', nullable=False, index=True)

    # شروط العقد (يكتبها التاجر — تظهر في PDF)
    terms_text = db.Column(db.Text, default='')
    # ميزات/خدمات تشمل العقد (يكتبها التاجر — تظهر في PDF)
    features_text = db.Column(db.Text, default='')

    # ========== الكلمات المفتاحية للتفعيل ==========
    # كلمات في رسالة العميل تشغّل هذا القالب
    # مثال: "إيجار شهري, عقد سنوي, ايجار طويل"
    trigger_keywords = db.Column(db.Text, default='')

    # ========== بيانات المؤجر (الطرف الأول) ==========
    lessor_name = db.Column(db.String(200), default='')
    lessor_id_number = db.Column(db.String(50), default='')
    lessor_phone = db.Column(db.String(50), default='')
    lessor_address = db.Column(db.Text, default='')

    # ========== الحقول المطلوبة ==========
    # JSON list: [{"key": "full_name", "label": "الاسم الكامل", "type": "text", "required": true}, ...]
    # types: text | phone | email | id_number | image | date | number
    required_fields = db.Column(db.JSON, default=list)

    # ========== شروط الدفع ==========
    # full | partial | tenant_decides
    payment_mode = db.Column(db.String(30), default='full')
    # لو partial: المبلغ المطلوب
    partial_amount = db.Column(db.Numeric(10, 2), default=0)
    # لو partial: نسبة (بدلاً من مبلغ ثابت)
    partial_percentage = db.Column(db.Numeric(5, 2), default=0)

    # سعر العقد الأساسي
    base_price = db.Column(db.Numeric(10, 2), default=0)
    price_unit = db.Column(db.String(20), default='monthly')  # monthly | yearly | daily | onetime

    # ========== طريقة التوليد ==========
    # internal_pdf | external_api
    generation_method = db.Column(db.String(30), default='internal_pdf')

    # لو internal_pdf: قالب PDF (يرفع التاجر template.pdf أو نص)
    pdf_template_url = db.Column(db.String(500), default='')  # رابط Cloudinary
    pdf_template_text = db.Column(db.Text, default='')  # نص القالب مع متغيرات {field_key}

    # لو external_api:
    external_api_url = db.Column(db.String(500), default='')
    external_api_method = db.Column(db.String(10), default='POST')  # POST | PUT
    external_api_auth = db.Column(db.String(500), default='')  # Bearer token / API key
    external_api_headers = db.Column(db.JSON, default=dict)

    # ========== الإرسال ==========
    send_to_customer_whatsapp = db.Column(db.Boolean, default=True)
    send_to_customer_email = db.Column(db.Boolean, default=True)
    send_to_tenant_email = db.Column(db.Boolean, default=True)

    # ========== التعليمات للبوت ==========
    # نص ينقله البوت للعميل عند بدء التدفق
    welcome_message = db.Column(db.Text, default='')
    # رسالة تأكيد بعد جمع البيانات
    confirmation_message = db.Column(db.Text, default='')

    # ========== التذكير بالدفع ==========
    reminder_message = db.Column(db.Text, default='نود تذكيركم باقتراب موعد الدفع للإيجار. شاكرين ومقدرين حسن تعاونكم.')

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = db.relationship('Tenant', backref=db.backref(
        'contract_templates', lazy='dynamic', cascade='all, delete-orphan',
    ))

    @staticmethod
    def default_fields_for_type(contract_type: str) -> list:
        """حقول افتراضية لنوع العقد."""
        common = [
            {'key': 'full_name', 'label': 'الاسم الكامل', 'type': 'text', 'required': True},
            {'key': 'phone', 'label': 'رقم الجوال', 'type': 'phone', 'required': True},
            {'key': 'email', 'label': 'البريد الإلكتروني', 'type': 'email', 'required': False},
            {'key': 'id_number', 'label': 'رقم الهوية', 'type': 'id_number', 'required': True},
        ]
        if contract_type in ('monthly_rental', 'daily_rental'):
            common.extend([
                {'key': 'id_image_front', 'label': 'صورة الهوية - الوجه الأمامي', 'type': 'image', 'required': True},
                {'key': 'id_image_back', 'label': 'صورة الهوية - الوجه الخلفي', 'type': 'image', 'required': True},
                {'key': 'address', 'label': 'العنوان الوطني', 'type': 'text', 'required': True},
                {'key': 'check_in_date', 'label': 'تاريخ الوصول', 'type': 'date', 'required': True},
                {'key': 'duration', 'label': 'مدة الإيجار (شهر)', 'type': 'number', 'required': True},
                {'key': 'guests_count', 'label': 'عدد الضيوف', 'type': 'number', 'required': False},
            ])
        return common

    def trigger_keywords_list(self):
        """قائمة الكلمات المفتاحية."""
        if not self.trigger_keywords:
            return []
        return [k.strip() for k in self.trigger_keywords.split(',') if k.strip()]

    def matches_message(self, message: str) -> bool:
        """هل الرسالة تطابق هذا القالب؟"""
        kws = self.trigger_keywords_list()
        if not kws:
            return False
        msg_lower = (message or '').lower()
        import re
        msg_lower = re.sub(r'[إأآا]', 'ا', msg_lower)
        msg_lower = re.sub(r'ة', 'ه', msg_lower)

        for kw in kws:
            kw_clean = kw.lower()
            kw_clean = re.sub(r'[إأآا]', 'ا', kw_clean)
            kw_clean = re.sub(r'ة', 'ه', kw_clean)
            if kw_clean in msg_lower:
                return True
        return False

    def get_payment_amount(self) -> float:
        """المبلغ المطلوب دفعه حسب الإعدادات."""
        if self.payment_mode == 'full':
            return float(self.base_price or 0)
        if self.payment_mode == 'partial':
            if self.partial_amount and float(self.partial_amount) > 0:
                return float(self.partial_amount)
            if self.partial_percentage and float(self.partial_percentage) > 0:
                return float(self.base_price or 0) * float(self.partial_percentage) / 100
        return 0.0

    def __repr__(self):
        return f'<ContractTemplate {self.name} tenant={self.tenant_id}>'

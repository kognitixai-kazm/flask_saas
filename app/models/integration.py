"""
app/models/integration.py — تكاملات كل tenant (واتساب، دفع، محاسبة، عقود).
أنت كمدير المنصة تدخل المفاتيح من لوحتك /sa/.
"""
from datetime import datetime
from ..extensions import db


class Integration(db.Model):
    """تكامل خدمة خارجية لـ tenant معيّن."""
    __tablename__ = 'integrations'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)

    # نوع التكامل
    # whatsapp | payment | accounting | contracts
    service_type = db.Column(db.String(30), nullable=False, index=True)

    # المزوّد
    # whatsapp: meta_cloud
    # payment: moyasar | tap | stripe
    # accounting: qoyod | daftra | xero
    # contracts: docusign | custom
    provider = db.Column(db.String(50), nullable=False)

    # المفاتيح (مشفّرة في الإنتاج)
    api_key = db.Column(db.String(500), default='')
    api_secret = db.Column(db.String(500), default='')
    access_token = db.Column(db.Text, default='')

    # واتساب خاص
    phone_number = db.Column(db.String(30), default='')
    phone_number_id = db.Column(db.String(50), default='')
    waba_id = db.Column(db.String(50), default='')  # WhatsApp Business Account ID
    webhook_verify_token = db.Column(db.String(100), default='')

    # دفع خاص
    payment_mode = db.Column(db.String(20), default='test')  # test | live
    payment_currency = db.Column(db.String(10), default='SAR')

    # إعدادات إضافية (JSON مرن)
    extra_config = db.Column(db.JSON, default=dict)

    # الحالة
    is_active = db.Column(db.Boolean, default=False, nullable=False)
    is_verified = db.Column(db.Boolean, default=False)  # تم التحقق من المفاتيح
    last_error = db.Column(db.Text, default='')

    # إحصائيات
    messages_sent = db.Column(db.Integer, default=0)
    messages_received = db.Column(db.Integer, default=0)
    payments_count = db.Column(db.Integer, default=0)
    payments_total = db.Column(db.Numeric(12, 2), default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # علاقات
    tenant = db.relationship('Tenant', backref=db.backref('integrations', lazy='dynamic', cascade='all, delete-orphan'))

    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'service_type', name='uq_tenant_service'),
    )

    SERVICE_LABELS = {
        'whatsapp': '💬 واتساب',
        'payment': '💳 بوابة الدفع',
        'accounting': '🧾 النظام المحاسبي',
        'contracts': '📄 العقود الإلكترونية',
        'facebook': '👍 فيسبوك',
        'instagram': '📸 انستغرام',
        'tiktok': '🎵 تيك توك',
        'snapchat': '👻 سناب شات',
        'linkedin': '💼 لينكدإن',
        'google_maps': '🗺️ خرائط جوجل',
        'srm': '📦 إدارة الموردين (SRM)',
        'booking_com': '🏨 Booking.com',
    }

    PROVIDER_LABELS = {
        'meta_cloud': 'Meta Cloud API',
        'moyasar': 'Moyasar',
        'tap': 'Tap Payments',
        'stripe': 'Stripe',
        'qoyod': 'قيود',
        'daftra': 'دفترة',
        'xero': 'Xero',
        'docusign': 'DocuSign',
        'custom': 'مخصص',
        'facebook_graph_api': 'Facebook Graph API',
        'instagram_graph_api': 'Instagram Graph API',
        'tiktok_for_business_api': 'TikTok For Business API',
        'snap_marketing_api': 'Snapchat Marketing API',
        'linkedin_marketing_api': 'LinkedIn Marketing API',
        'google_my_business_api': 'Google My Business API',
        'booking_api': 'Booking.com API',
        'custom_srm': 'مورد مخصص',
    }

    @property
    def service_label(self):
        return self.SERVICE_LABELS.get(self.service_type, self.service_type)

    @property
    def provider_label(self):
        return self.PROVIDER_LABELS.get(self.provider, self.provider)

    @property
    def status_text(self):
        if not self.is_active:
            return '⏸️ معطّل'
        if not self.is_verified:
            return '⚠️ غير متحقق'
        return '✅ مفعّل'

    def __repr__(self):
        return f'<Integration {self.service_type}/{self.provider} tenant={self.tenant_id}>'

    # ========== Decrypted Properties ==========
    @property
    def api_key_decrypted(self):
        from app.utils.encryption import decrypt_value
        return decrypt_value(self.api_key)

    @api_key_decrypted.setter
    def api_key_decrypted(self, val):
        from app.utils.encryption import encrypt_value, decrypt_value
        val = (val or '').strip()
        if decrypt_value(self.api_key) != val:
            self.api_key = encrypt_value(val) if val else ''

    @property
    def api_secret_decrypted(self):
        from app.utils.encryption import decrypt_value
        return decrypt_value(self.api_secret)

    @api_secret_decrypted.setter
    def api_secret_decrypted(self, val):
        from app.utils.encryption import encrypt_value, decrypt_value
        val = (val or '').strip()
        if decrypt_value(self.api_secret) != val:
            self.api_secret = encrypt_value(val) if val else ''

    @property
    def access_token_decrypted(self):
        from app.utils.encryption import decrypt_value
        return decrypt_value(self.access_token)

    @access_token_decrypted.setter
    def access_token_decrypted(self, val):
        from app.utils.encryption import encrypt_value, decrypt_value
        val = (val or '').strip()
        if decrypt_value(self.access_token) != val:
            self.access_token = encrypt_value(val) if val else ''

    @property
    def webhook_verify_token_decrypted(self):
        from app.utils.encryption import decrypt_value
        return decrypt_value(self.webhook_verify_token)

    @webhook_verify_token_decrypted.setter
    def webhook_verify_token_decrypted(self, val):
        from app.utils.encryption import encrypt_value, decrypt_value
        val = (val or '').strip()
        if decrypt_value(self.webhook_verify_token) != val:
            self.webhook_verify_token = encrypt_value(val) if val else ''


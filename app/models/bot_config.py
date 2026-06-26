"""
app/models/bot_config.py — إعدادات البوت لكل tenant.
يشمل: أسلوب الرد + تعليمات مخصصة + مفاتيح API (صور/صوت/AI/اتصال).
يُدار من لوحة الأدمن (/sa/).
"""
from datetime import datetime
from ..extensions import db


class BotConfig(db.Model):
    """إعدادات البوت الخاصة بكل tenant."""
    __tablename__ = 'bot_configs'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, unique=True, index=True)

    # ========== أسلوب الرد ==========
    # formal | friendly | gulf_dialect | custom
    tone = db.Column(db.String(30), default='friendly')
    # اسم البوت (يظهر في الردود)
    bot_name = db.Column(db.String(100), default='')
    # صياغة الوكيل في الردود القاعدية: neutral | male | female
    agent_gender = db.Column(db.String(10), default='neutral', nullable=False)
    # تعليمات مخصصة (نص حر يوجّه البوت)
    custom_instructions = db.Column(db.Text, default='')
    # كلمات أو مواضيع ممنوعة
    blocked_topics = db.Column(db.Text, default='')

    # ========== مفاتيح API ==========
    # معالج صور (Cloudinary / ImgBB / Imgur)
    image_provider = db.Column(db.String(30), default='')
    image_api_key = db.Column(db.Text, default='')
    image_api_secret = db.Column(db.Text, default='')

    # معالج صوت (Google Speech / OpenAI Whisper)
    voice_provider = db.Column(db.String(30), default='')
    voice_api_key = db.Column(db.Text, default='')

    # AI إضافي (خاص بالتاجر — بديل عن المفتاح العام) (DEPRECATED: تم نقلها للإدارة المركزية)
    # openai | anthropic | google_gemini | mistral
    # سيتم إزالتها لاحقاً بالكامل، نتركها الآن كتعليقات لتجنب الأخطاء في أجزاء قديمة
    # ai_provider = db.Column(db.String(30), default='')
    # ai_api_key = db.Column(db.Text, default='')
    # ai_model = db.Column(db.String(50), default='')

    # بوت الاتصال الصوتي (Twilio / Vonage)
    call_provider = db.Column(db.String(30), default='')  # twilio | vonage | bland
    call_api_key = db.Column(db.Text, default='')
    call_api_secret = db.Column(db.Text, default='')
    call_phone_number = db.Column(db.String(30), default='')
    call_webhook_url = db.Column(db.String(500), default='')
    call_is_active = db.Column(db.Boolean, default=False)
    # صوت البوت: male_ar | female_ar | male_en | female_en
    call_voice = db.Column(db.String(30), default='female_ar')
    call_greeting = db.Column(db.Text, default='')  # رسالة الترحيب الصوتية

    # ========== قاعدة المعرفة (PDF) ==========
    # النص المستخرج من ملفات PDF المرفوعة
    knowledge_base = db.Column(db.Text, default='')
    knowledge_files_count = db.Column(db.Integer, default=0)
    knowledge_last_updated = db.Column(db.DateTime, nullable=True)

    # ========== التعلم التلقائي ==========
    auto_learn_enabled = db.Column(db.Boolean, default=True)
    # عدد الردود المتعلّمة
    learned_replies_count = db.Column(db.Integer, default=0)

    # ========== نوايا دلالية (sentence-transformers) + عتبة التشابه ==========
    semantic_intent_enabled = db.Column(db.Boolean, default=False, nullable=False)
    semantic_threshold = db.Column(db.Float, default=0.42, nullable=False)

    # ========== واتساب (تحكم التاجر — الربط التقني يبقى عند المنصة) ==========
    # إذا False: الرسائل الواردة تُحفظ فقط دون رد بوت تلقائي (الرد من لوحة التاجر).
    whatsapp_auto_reply_enabled = db.Column(db.Boolean, default=True, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # علاقة
    tenant = db.relationship('Tenant', backref=db.backref('bot_config', uselist=False, cascade='all, delete-orphan'))

    TONE_LABELS = {
        'formal': '🎩 رسمي',
        'friendly': '😊 ودّي',
        'gulf_dialect': '🏜️ لهجة خليجية',
        'custom': '✏️ مخصص',
    }

    @property
    def tone_label(self):
        return self.TONE_LABELS.get(self.tone, self.tone)

    def __repr__(self):
        return f'<BotConfig tenant={self.tenant_id} tone={self.tone}>'

    # ========== Decrypted Properties ==========
    @property
    def image_api_key_decrypted(self):
        from app.utils.encryption import decrypt_value
        return decrypt_value(self.image_api_key)

    @image_api_key_decrypted.setter
    def image_api_key_decrypted(self, val):
        from app.utils.encryption import encrypt_value, decrypt_value
        val = (val or '').strip()
        if decrypt_value(self.image_api_key) != val:
            self.image_api_key = encrypt_value(val) if val else ''

    @property
    def voice_api_key_decrypted(self):
        from app.utils.encryption import decrypt_value
        return decrypt_value(self.voice_api_key)

    @voice_api_key_decrypted.setter
    def voice_api_key_decrypted(self, val):
        from app.utils.encryption import encrypt_value, decrypt_value
        val = (val or '').strip()
        if decrypt_value(self.voice_api_key) != val:
            self.voice_api_key = encrypt_value(val) if val else ''



    @property
    def call_api_key_decrypted(self):
        from app.utils.encryption import decrypt_value
        return decrypt_value(self.call_api_key)

    @call_api_key_decrypted.setter
    def call_api_key_decrypted(self, val):
        from app.utils.encryption import encrypt_value, decrypt_value
        val = (val or '').strip()
        if decrypt_value(self.call_api_key) != val:
            self.call_api_key = encrypt_value(val) if val else ''

    @property
    def call_api_secret_decrypted(self):
        from app.utils.encryption import decrypt_value
        return decrypt_value(self.call_api_secret)

    @call_api_secret_decrypted.setter
    def call_api_secret_decrypted(self, val):
        from app.utils.encryption import encrypt_value, decrypt_value
        val = (val or '').strip()
        if decrypt_value(self.call_api_secret) != val:
            self.call_api_secret = encrypt_value(val) if val else ''


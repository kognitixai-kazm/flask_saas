"""
app/models/system_settings.py — إعدادات النظام العامة (key/value).

استخدام: تخزين مفاتيح API ومتغيرات يمكن تعديلها من لوحة الأدمن
بدون تعديل ملف .env.

المفاتيح المخزّنة:
- WHATSAPP_APP_SECRET (للتحقق من توقيع Meta)
- WHATSAPP_VERIFY_TOKEN (العام)
- AI_OPENAI_KEY / AI_ANTHROPIC_KEY (مفاتيح AI العامة)
- CLOUDINARY_CLOUD_NAME / CLOUDINARY_API_KEY / CLOUDINARY_API_SECRET
- SMTP_HOST / SMTP_USER / SMTP_PASSWORD / SMTP_PORT
- إلخ.
"""
from datetime import datetime
from ..extensions import db


class SystemSetting(db.Model):
    """
    جدول إعدادات النظام — يخزّن أي مفتاح/قيمة.

    القيم الحساسة (passwords, secrets) يمكن تشفيرها لاحقاً.
    """
    __tablename__ = 'system_settings'

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False, index=True)
    value = db.Column(db.Text, default='')

    # تصنيف: whatsapp / ai / payment / email / cloudinary / general
    category = db.Column(db.String(50), default='general', index=True)

    # حساس؟ (يخفي القيمة في العرض)
    is_secret = db.Column(db.Boolean, default=False)

    description = db.Column(db.String(500), default='')

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = db.Column(db.String(100), default='')

    def __repr__(self):
        return f'<SystemSetting {self.key}>'

    @staticmethod
    def get(key: str, default: str = '') -> str:
        """جلب قيمة مفتاح."""
        s = SystemSetting.query.filter_by(key=key).first()
        return s.value if s else default

    @staticmethod
    def set(key: str, value: str, category: str = 'general',
            is_secret: bool = False, description: str = '',
            updated_by: str = ''):
        """تعيين/تحديث قيمة."""
        s = SystemSetting.query.filter_by(key=key).first()
        if s:
            s.value = value
            if updated_by:
                s.updated_by = updated_by
        else:
            s = SystemSetting(
                key=key, value=value,
                category=category, is_secret=is_secret,
                description=description, updated_by=updated_by,
            )
            db.session.add(s)
        return s

    @staticmethod
    def get_all_by_category(category: str = None):
        """جلب كل المفاتيح أو حسب التصنيف."""
        q = SystemSetting.query
        if category:
            q = q.filter_by(category=category)
        return q.order_by(SystemSetting.key).all()

    @staticmethod
    def seed_defaults():
        """إنشاء المفاتيح الافتراضية (فاضية) لتظهر في اللوحة."""
        defaults = [
            # WhatsApp
            ('WHATSAPP_APP_SECRET', 'whatsapp', True,
             'App Secret من Meta Developer (للتحقق من توقيع webhook)'),
            ('WHATSAPP_VERIFY_TOKEN', 'whatsapp', True,
             'Verify Token العام لـ webhook (يُستخدم كـ fallback)'),

            # AI
            ('AI_OPENAI_KEY', 'ai', True, 'OpenAI API Key العام للمنصة'),
            ('AI_ANTHROPIC_KEY', 'ai', True, 'Anthropic API Key العام'),
            ('AI_GOOGLE_KEY', 'ai', True, 'Google Gemini API Key العام'),
            ('AI_DEFAULT_MODEL', 'ai', False, 'النموذج الافتراضي (مثل: gpt-4o-mini)'),

            # Cloudinary
            ('CLOUDINARY_CLOUD_NAME', 'cloudinary', False, 'Cloudinary Cloud Name'),
            ('CLOUDINARY_API_KEY', 'cloudinary', True, 'Cloudinary API Key'),
            ('CLOUDINARY_API_SECRET', 'cloudinary', True, 'Cloudinary API Secret'),

            # Email (SMTP)
            ('SMTP_HOST', 'email', False, 'مثل: smtp.gmail.com'),
            ('SMTP_PORT', 'email', False, 'مثل: 587'),
            ('SMTP_USER', 'email', False, 'البريد المرسِل'),
            ('SMTP_PASSWORD', 'email', True, 'كلمة مرور التطبيق'),
            ('SMTP_FROM_NAME', 'email', False, 'الاسم الظاهر للمرسِل'),
            ('MAIL_ENABLED', 'email', False, 'true/false'),
        ]
        for key, cat, is_sec, desc in defaults:
            existing = SystemSetting.query.filter_by(key=key).first()
            if not existing:
                db.session.add(SystemSetting(
                    key=key, value='', category=cat,
                    is_secret=is_sec, description=desc,
                ))
        db.session.commit()

"""
app/models/service_pricing.py — أسعار الخدمات الإضافية.

يحدد المؤسس من /sa/ai-pricing سعر:
- الرسالة العادية (نص فقط، بدون AI)
- إرسال صورة
- إرسال صوت
- معالجة صورة (OCR / تحليل)
- معالجة صوت (تفريغ)
- رسالة WhatsApp (فوق 1000 المجاني)
"""
from datetime import datetime
from ..extensions import db


class ServicePricing(db.Model):
    """أسعار الخدمات الإضافية."""
    __tablename__ = 'service_pricing'

    id = db.Column(db.Integer, primary_key=True)

    # المعرّف الفريد للخدمة
    # text_message | image_send | audio_send | image_process | audio_process | whatsapp_message
    service_key = db.Column(db.String(50), unique=True, nullable=False, index=True)

    # الاسم المعروض
    display_name = db.Column(db.String(100), nullable=False)

    # رمز
    icon = db.Column(db.String(10), default='💬')

    # السعر (بالريال) لكل وحدة
    price = db.Column(db.Numeric(10, 4), default=0.0)

    # التكلفة الفعلية على المؤسس
    cost = db.Column(db.Numeric(10, 4), default=0.0)

    # وصف
    description = db.Column(db.String(500), default='')

    is_active = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer, default=0)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @staticmethod
    def get_price(service_key: str) -> float:
        """جلب السعر الحالي لخدمة."""
        s = ServicePricing.query.filter_by(service_key=service_key, is_active=True).first()
        return float(s.price) if s else 0.0

    @staticmethod
    def seed_defaults():
        """إنشاء أسعار افتراضية."""
        defaults = [
            {
                'service_key': 'text_message',
                'display_name': 'رسالة نصية عادية',
                'icon': '💬',
                'price': 0.02,
                'cost': 0.005,
                'description': 'رد من القواعد المحلية أو البحث في DB (بدون AI)',
                'sort_order': 1,
            },
            {
                'service_key': 'image_send',
                'display_name': 'إرسال صورة',
                'icon': '🖼️',
                'price': 0.05,
                'cost': 0.01,
                'description': 'إرسال صورة من Cloudinary للعميل',
                'sort_order': 2,
            },
            {
                'service_key': 'audio_send',
                'display_name': 'إرسال صوت',
                'icon': '🎵',
                'price': 0.08,
                'cost': 0.02,
                'description': 'إرسال رسالة صوتية للعميل',
                'sort_order': 3,
            },
            {
                'service_key': 'image_process',
                'display_name': 'معالجة صورة (OCR/تحليل)',
                'icon': '🔍',
                'price': 0.30,
                'cost': 0.10,
                'description': 'تحليل صورة بالـ AI (Vision API)',
                'sort_order': 4,
            },
            {
                'service_key': 'audio_process',
                'display_name': 'معالجة صوت (تفريغ)',
                'icon': '🎙️',
                'price': 0.20,
                'cost': 0.06,
                'description': 'تحويل الصوت إلى نص (Whisper)',
                'sort_order': 5,
            },
            {
                'service_key': 'whatsapp_message',
                'display_name': 'رسالة واتساب',
                'icon': '📱',
                'price': 0.15,
                'cost': 0.04,
                'description': 'رسالة عبر WhatsApp Business API (فوق المجاني)',
                'sort_order': 6,
            },
        ]

        for data in defaults:
            existing = ServicePricing.query.filter_by(service_key=data['service_key']).first()
            if not existing:
                db.session.add(ServicePricing(**data))
        db.session.commit()

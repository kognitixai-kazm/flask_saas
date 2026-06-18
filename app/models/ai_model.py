"""
app/models/ai_model.py — النماذج المتاحة وأسعارها.

يديره المؤسس من /sa/ai-pricing:
- اسم النموذج (Claude Sonnet, GPT-4o, Gemini)
- المزوّد (anthropic, openai, google)
- الـ model ID (مثل: gpt-4o-mini)
- التكلفة الفعلية للمؤسس (ما يدفعه لـ OpenAI/Anthropic)
- سعر البيع للتاجر (لكل رسالة)
- مفعّل أم لا
"""
from datetime import datetime
from ..extensions import db


class AIModel(db.Model):
    """نموذج AI متاح للاستخدام في المنصة."""
    __tablename__ = 'ai_models'

    id = db.Column(db.Integer, primary_key=True)

    # الاسم المعروض (Claude Sonnet 4.5)
    display_name = db.Column(db.String(100), nullable=False)

    # المزوّد: anthropic | openai | google
    provider = db.Column(db.String(30), nullable=False, index=True)

    # معرّف النموذج عند المزوّد
    # مثل: claude-sonnet-4-5 | gpt-4o-mini | gemini-pro
    model_id = db.Column(db.String(100), nullable=False)

    # رمز إيموجي للعرض
    icon = db.Column(db.String(10), default='🤖')

    # وصف مختصر للتاجر
    description = db.Column(db.Text, default='')

    # ============ الأسعار (يحددها المؤسس) ============
    # سعر البيع للتاجر لكل رسالة (بالريال السعودي)
    price_per_message = db.Column(db.Numeric(10, 4), default=0.20)

    # التكلفة الفعلية للمؤسس (للمتابعة الداخلية فقط)
    cost_per_message = db.Column(db.Numeric(10, 4), default=0.05)

    # ============ الحالة ============
    is_active = db.Column(db.Boolean, default=True)
    is_default = db.Column(db.Boolean, default=False)
    sort_order = db.Column(db.Integer, default=0)

    # ============ الجودة (لاختيار التاجر) ============
    # 1=اقتصادي | 2=متوازن | 3=متقدم | 4=احترافي
    quality_tier = db.Column(db.Integer, default=2)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    QUALITY_LABELS = {
        1: '🟢 اقتصادي',
        2: '🔵 متوازن',
        3: '🟣 متقدم',
        4: '🟡 احترافي',
    }

    @property
    def quality_label(self):
        return self.QUALITY_LABELS.get(self.quality_tier, 'غير محدد')

    @property
    def margin_percent(self):
        """نسبة هامش الربح."""
        if self.cost_per_message and float(self.cost_per_message) > 0:
            margin = (float(self.price_per_message) - float(self.cost_per_message)) / float(self.price_per_message) * 100
            return round(margin, 1)
        return 0

    def __repr__(self):
        return f'<AIModel {self.display_name} ({self.provider})>'

    @staticmethod
    def seed_defaults():
        """إنشاء النماذج الافتراضية."""
        defaults = [
            # Claude
            {
                'display_name': 'Claude Haiku',
                'provider': 'anthropic',
                'model_id': 'claude-haiku-4-5',
                'icon': '🟢',
                'description': 'سريع واقتصادي، مناسب للردود البسيطة',
                'price_per_message': 0.05,
                'cost_per_message': 0.01,
                'quality_tier': 1,
                'sort_order': 1,
            },
            {
                'display_name': 'Claude Sonnet',
                'provider': 'anthropic',
                'model_id': 'claude-sonnet-4-6',
                'icon': '🔵',
                'description': 'متوازن، الأنسب لمعظم الاستخدامات',
                'price_per_message': 0.15,
                'cost_per_message': 0.04,
                'quality_tier': 2,
                'is_default': True,
                'sort_order': 2,
            },
            {
                'display_name': 'Claude Opus',
                'provider': 'anthropic',
                'model_id': 'claude-opus-4-7',
                'icon': '🟣',
                'description': 'الأقوى من Anthropic، للحالات المعقدة',
                'price_per_message': 0.40,
                'cost_per_message': 0.12,
                'quality_tier': 4,
                'sort_order': 3,
            },
            # OpenAI
            {
                'display_name': 'GPT-4o Mini',
                'provider': 'openai',
                'model_id': 'gpt-4o-mini',
                'icon': '⚡',
                'description': 'الإصدار الاقتصادي من GPT',
                'price_per_message': 0.05,
                'cost_per_message': 0.01,
                'quality_tier': 1,
                'sort_order': 4,
            },
            {
                'display_name': 'GPT-4o',
                'provider': 'openai',
                'model_id': 'gpt-4o',
                'icon': '🔥',
                'description': 'أحدث وأقوى من OpenAI',
                'price_per_message': 0.20,
                'cost_per_message': 0.06,
                'quality_tier': 3,
                'sort_order': 5,
            },
            # Google
            {
                'display_name': 'Gemini Pro',
                'provider': 'google',
                'model_id': 'gemini-1.5-pro',
                'icon': '✨',
                'description': 'من Google، يدعم العربية بشكل ممتاز',
                'price_per_message': 0.10,
                'cost_per_message': 0.03,
                'quality_tier': 2,
                'sort_order': 6,
            },
        ]

        for data in defaults:
            existing = AIModel.query.filter_by(
                provider=data['provider'],
                model_id=data['model_id'],
            ).first()
            if not existing:
                db.session.add(AIModel(**data))
        db.session.commit()

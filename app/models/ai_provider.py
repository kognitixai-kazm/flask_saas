from datetime import datetime
from ..extensions import db

class AIProvider(db.Model):
    """جدول شركات الذكاء الاصطناعي (مثل OpenAI, Anthropic, Google)"""
    __tablename__ = 'ai_providers'

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    icon = db.Column(db.String(10), default='🤖')
    is_active = db.Column(db.Boolean, default=True)
    
    # مفتاح الـ API الخاص بالمزود (مخزن مشفر)
    api_key = db.Column(db.Text, default='')
    
    # أولوية المزود في نظام Fallback (1 هو الأعلى أولوية)
    priority = db.Column(db.Integer, default=10)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    models = db.relationship('AIModel', backref='ai_provider_rel', lazy='dynamic', cascade='all, delete-orphan')

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

    def __repr__(self):
        return f'<AIProvider {self.slug}>'

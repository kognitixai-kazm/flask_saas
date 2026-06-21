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
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    models = db.relationship('AIModel', backref='ai_provider_rel', lazy='dynamic', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<AIProvider {self.slug}>'

"""
app/models/tenant_integrations.py — تكامل خدمة الرسائل النصية للمستأجر
"""
from datetime import datetime
from ..extensions import db

class TenantIntegration(db.Model):
    """تكامل خدمة SMS لمستأجر معيّن."""
    __tablename__ = 'tenant_integrations'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    
    provider_name = db.Column(db.String(50), nullable=False, default='twilio')
    api_key = db.Column(db.String(255), nullable=False, default='')
    sender_id = db.Column(db.String(50), nullable=False, default='')
    
    is_active = db.Column(db.Boolean, default=False, nullable=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # علاقات
    tenant = db.relationship('Tenant', backref=db.backref('sms_integrations', lazy='dynamic', cascade='all, delete-orphan'))

    def __repr__(self):
        return f'<TenantIntegration SMS {self.provider_name} tenant={self.tenant_id}>'

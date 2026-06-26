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
    api_key = db.Column(db.Text, nullable=False, default='')
    sender_id = db.Column(db.String(50), nullable=False, default='')
    
    is_active = db.Column(db.Boolean, default=False, nullable=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # علاقات
    tenant = db.relationship('Tenant', backref=db.backref('sms_integrations', lazy='dynamic', cascade='all, delete-orphan'))

    def __repr__(self):
        return f'<TenantIntegration SMS {self.provider_name} tenant={self.tenant_id}>'

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


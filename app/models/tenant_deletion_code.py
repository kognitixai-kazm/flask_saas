"""
رمز تحقق لمرة واحدة عند حذف النشاط من لوحة التاجر.
"""
from datetime import datetime

from ..extensions import db


class TenantDeletionCode(db.Model):
    __tablename__ = 'tenant_deletion_codes'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(
        db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True
    )
    code_hash = db.Column(db.String(128), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f'<TenantDeletionCode tenant={self.tenant_id}>'

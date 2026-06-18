"""
app/models/tenant_user.py — مستخدمو المستأجر (المالك + موظفوه)
"""
from datetime import datetime
from ..extensions import db


class TenantUser(db.Model):
    """مستخدم يعمل لصالح tenant معين."""
    __tablename__ = 'tenant_users'

    id = db.Column(db.Integer, primary_key=True)

    tenant_id = db.Column(
        db.Integer, db.ForeignKey('tenants.id'),
        nullable=False, index=True
    )

    username = db.Column(db.String(80), nullable=False, index=True)
    email = db.Column(db.String(255), nullable=False, index=True)
    full_name = db.Column(db.String(200))
    phone = db.Column(db.String(30))
    password_hash = db.Column(db.String(255), nullable=False)

    # الدور: owner, admin, staff
    role = db.Column(db.String(20), default='staff', nullable=False)

    is_active = db.Column(db.Boolean, default=True, nullable=False)
    last_login_at = db.Column(db.DateTime)
    last_login_ip = db.Column(db.String(45))

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow,
        onupdate=datetime.utcnow, nullable=False
    )

    # علاقات
    tenant = db.relationship('Tenant', back_populates='users')

    # قيد: username فريد داخل نفس المستأجر فقط
    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'username', name='uq_tenant_username'),
        db.UniqueConstraint('tenant_id', 'email', name='uq_tenant_email'),
    )

    def __repr__(self):
        return f'<TenantUser {self.username}@{self.tenant_id}>'

    @property
    def is_owner(self):
        return self.role == 'owner'

    @property
    def is_admin(self):
        return self.role in ('owner', 'admin')

    def to_dict(self):
        return {
            'id': self.id,
            'tenant_id': self.tenant_id,
            'username': self.username,
            'email': self.email,
            'full_name': self.full_name,
            'role': self.role,
            'is_active': self.is_active,
        }

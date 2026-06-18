"""
app/models/audit_log.py — سجل تدقيق لكل عملية حساسة
"""
from datetime import datetime
from ..extensions import db


class AuditLog(db.Model):
    """سجل الأحداث الحساسة في النظام."""
    __tablename__ = 'audit_logs'

    id = db.Column(db.BigInteger, primary_key=True)

    # super_admin | tenant_user | system | anonymous
    actor_type = db.Column(db.String(20), nullable=False, index=True)
    actor_id = db.Column(db.Integer, index=True)

    # ربط بالمستأجر المتأثر (nullable)
    tenant_id = db.Column(
        db.Integer, db.ForeignKey('tenants.id'),
        nullable=True, index=True
    )

    # الفعل: login, logout, create_tenant, suspend_tenant, change_plan...
    action = db.Column(db.String(100), nullable=False, index=True)

    # الهدف (مثلاً tenant:5 أو plan:3)
    target = db.Column(db.String(100))

    # بيانات إضافية
    extra_data = db.Column(db.JSON, default=dict)

    # معلومات الطلب
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(500))

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self):
        return f'<AuditLog {self.action} by {self.actor_type}:{self.actor_id}>'

    def to_dict(self):
        return {
            'id': self.id,
            'actor_type': self.actor_type,
            'actor_id': self.actor_id,
            'tenant_id': self.tenant_id,
            'action': self.action,
            'target': self.target,
            'extra_data': self.extra_data,
            'ip_address': self.ip_address,
            'created_at': self.created_at.isoformat(),
        }

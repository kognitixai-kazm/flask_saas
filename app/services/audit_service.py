"""
app/services/audit_service.py — تسجيل الأحداث الحساسة.
"""
from flask import request

from app.extensions import db
from app.models.audit_log import AuditLog


class AuditService:

    @staticmethod
    def log(
        actor_type: str,
        action: str,
        actor_id: int = None,
        tenant_id: int = None,
        target: str = None,
        extra_data: dict = None,
    ) -> AuditLog:
        """تسجيل حدث في سجل التدقيق."""
        try:
            entry = AuditLog(
                actor_type=actor_type,
                actor_id=actor_id,
                tenant_id=tenant_id,
                action=action,
                target=target,
                extra_data=extra_data or {},
                ip_address=request.remote_addr if request else None,
                user_agent=str(request.user_agent)[:500] if request else None,
            )
            db.session.add(entry)
            db.session.commit()
            return entry
        except Exception:
            # لا نريد أن يفشل التطبيق بسبب خطأ في الـ log
            db.session.rollback()
            return None

    @staticmethod
    def get_recent(limit=50, tenant_id=None, actor_type=None):
        """جلب آخر الأحداث."""
        q = AuditLog.query
        if tenant_id:
            q = q.filter_by(tenant_id=tenant_id)
        if actor_type:
            q = q.filter_by(actor_type=actor_type)
        return q.order_by(AuditLog.created_at.desc()).limit(limit).all()

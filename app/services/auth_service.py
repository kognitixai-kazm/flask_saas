"""
app/services/auth_service.py — منطق المصادقة لكل العوالم الثلاثة.
"""
from datetime import datetime
from flask import request, session

from app.extensions import db
from app.models.super_admin import SuperAdmin
from app.models.tenant_user import TenantUser
from app.utils.passwords import hash_password, verify_password
from app.services.audit_service import AuditService


class AuthService:
    """خدمة المصادقة المركزية."""

    # ========================
    # Super Admin
    # ========================
    @staticmethod
    def create_super_admin(username: str, email: str, password: str) -> SuperAdmin:
        admin = SuperAdmin(
            username=username,
            email=email,
            password_hash=hash_password(password),
        )
        db.session.add(admin)
        db.session.commit()
        return admin

    @staticmethod
    def login_super_admin(username: str, password: str) -> SuperAdmin | None:
        """محاولة تسجيل دخول Super Admin. ترجع الكائن أو None."""
        admin = SuperAdmin.query.filter(
            (SuperAdmin.username == username) | (SuperAdmin.email == username)
        ).first()

        if not admin or not admin.is_active:
            return None

        if not verify_password(admin.password_hash, password):
            AuditService.log(
                actor_type='super_admin',
                actor_id=admin.id if admin else None,
                action='login_failed',
                target=f'super_admin:{username}',
            )
            return None

        # نجاح
        admin.last_login_at = datetime.utcnow()
        admin.last_login_ip = request.remote_addr
        db.session.commit()

        # حفظ في session
        session.clear()
        session['sa_user_id'] = admin.id

        AuditService.log(
            actor_type='super_admin',
            actor_id=admin.id,
            action='login_success',
        )
        return admin

    @staticmethod
    def logout_super_admin():
        """تسجيل خروج Super Admin."""
        sa_id = session.get('sa_user_id')
        if sa_id:
            AuditService.log(
                actor_type='super_admin',
                actor_id=sa_id,
                action='logout',
            )
        session.clear()

    # ========================
    # Tenant User
    # ========================
    @staticmethod
    def create_tenant_user(
        tenant_id: int,
        username: str,
        email: str,
        password: str,
        full_name: str = '',
        phone: str = '',
        role: str = 'owner',
    ) -> TenantUser:
        """إنشاء مستخدم جديد لمستأجر."""
        user = TenantUser(
            tenant_id=tenant_id,
            username=username,
            email=email,
            full_name=full_name,
            phone=phone,
            password_hash=hash_password(password),
            role=role,
        )
        db.session.add(user)
        db.session.commit()
        return user

    @staticmethod
    def login_tenant_user(username: str, password: str) -> TenantUser | None:
        """تسجيل دخول مستخدم مستأجر."""
        user = TenantUser.query.filter(
            (TenantUser.username == username) | (TenantUser.email == username)
        ).first()

        if not user or not user.is_active:
            return None

        if not verify_password(user.password_hash, password):
            AuditService.log(
                actor_type='tenant_user',
                actor_id=user.id,
                tenant_id=user.tenant_id,
                action='login_failed',
            )
            return None

        user.last_login_at = datetime.utcnow()
        user.last_login_ip = request.remote_addr
        db.session.commit()

        # Session rotation: نمسح القديم ونحفظ الجديد
        session.clear()
        session['tenant_user_id'] = user.id
        session['tenant_id'] = user.tenant_id

        AuditService.log(
            actor_type='tenant_user',
            actor_id=user.id,
            tenant_id=user.tenant_id,
            action='login_success',
        )
        return user

    @staticmethod
    def logout_tenant_user():
        """تسجيل خروج مستخدم مستأجر."""
        user_id = session.get('tenant_user_id')
        tenant_id = session.get('tenant_id')
        if user_id:
            AuditService.log(
                actor_type='tenant_user',
                actor_id=user_id,
                tenant_id=tenant_id,
                action='logout',
            )
        session.clear()

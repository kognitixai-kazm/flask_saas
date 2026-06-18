"""
@tenant_required — يحمي مسارات /app/*
يفحص tenant_session cookie. يحقن g.current_user و g.current_tenant.
"""
from functools import wraps
from flask import session, redirect, url_for, flash, g

from app.models.tenant_user import TenantUser
from app.models.tenant import Tenant


def tenant_required(f):
    """يتأكد أن المستخدم مسجّل دخول كـ tenant user."""
    @wraps(f)
    def decorated(*args, **kwargs):
        tenant_user_id = session.get('tenant_user_id')

        if not tenant_user_id:
            flash('يجب تسجيل الدخول أولاً', 'warning')
            return redirect(url_for('tenant.login'))

        user = TenantUser.query.get(tenant_user_id)
        if not user or not user.is_active:
            session.pop('tenant_user_id', None)
            flash('الجلسة غير صالحة', 'danger')
            return redirect(url_for('tenant.login'))

        tenant = Tenant.query.get(user.tenant_id)
        if not tenant or tenant.status == 'cancelled':
            session.pop('tenant_user_id', None)
            flash('الحساب غير متاح', 'danger')
            return redirect(url_for('tenant.login'))

        if tenant.status == 'suspended':
            flash('حسابك معلّق. تواصل مع الدعم.', 'warning')
            return redirect(url_for('tenant.login'))

        # حقن في g
        g.current_user = user
        g.current_tenant = tenant

        return f(*args, **kwargs)

    return decorated


def tenant_owner_required(f):
    """يتأكد أن المستخدم هو owner المستأجر."""
    @wraps(f)
    @tenant_required
    def decorated(*args, **kwargs):
        if not g.current_user.is_owner:
            flash('هذا الإجراء متاح لصاحب الحساب فقط', 'danger')
            return redirect(url_for('tenant.dashboard'))
        return f(*args, **kwargs)

    return decorated

"""
@super_admin_required — يحمي مسارات /sa/*
يفحص sa_session cookie فقط. لا يشارك أي شيء مع عالم tenant.
"""
from functools import wraps
from flask import session, redirect, url_for, flash, request, g, abort

from app.models.super_admin import SuperAdmin


def super_admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        sa_user_id = session.get('sa_user_id')

        if not sa_user_id:
            flash('يجب تسجيل الدخول أولاً', 'warning')
            return redirect(url_for('super_admin.login'))

        admin = SuperAdmin.query.get(sa_user_id)
        if not admin or not admin.is_active:
            session.pop('sa_user_id', None)
            flash('الجلسة غير صالحة', 'danger')
            return redirect(url_for('super_admin.login'))

        # إتاحة بيانات الأدمن في g لكل الـ request
        g.current_admin = admin
        return f(*args, **kwargs)

    return decorated

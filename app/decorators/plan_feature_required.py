"""
@plan_feature_required('whatsapp') — يتأكد أن باقة العميل تدعم الميزة.
"""
from functools import wraps
from flask import g, flash, redirect, url_for, abort


def plan_feature_required(feature_key: str):
    """
    ديكوريتر يتأكد أن الباقة تشمل ميزة معيّنة.
    الاستخدام:
        @tenant_required
        @plan_feature_required('whatsapp')
        def whatsapp_settings():
            ...
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            tenant = getattr(g, 'current_tenant', None)
            if not tenant:
                abort(403)

            # جلب الباقة
            subscription = tenant.subscription
            if not subscription or not subscription.is_active:
                flash('اشتراكك غير فعّال. يرجى تجديده.', 'warning')
                return redirect(url_for('tenant.billing'))

            plan = subscription.plan
            if not plan or not plan.has_feature(feature_key):
                flash(f'هذه الميزة غير متوفرة في باقتك الحالية ({plan.name_ar if plan else "—"}). قم بالترقية.', 'info')
                return redirect(url_for('tenant.billing'))

            return f(*args, **kwargs)

        return decorated
    return decorator

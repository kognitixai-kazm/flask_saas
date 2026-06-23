"""
app/blueprints/super_admin.py — لوحة السوبر أدمن (/sa)
مسار منفصل تماماً + جلسة منفصلة (sa_session).
"""
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, g, session, current_app
from sqlalchemy import func

from app.extensions import limiter
from app.decorators import super_admin_required
from app.services.auth_service import AuthService
from app.services.tenant_service import TenantService
from app.services.plan_service import PlanService
from app.services.activity_service import ActivityService
from app.services.audit_service import AuditService
from app.models.tenant import Tenant
from app.models.plan import Plan, PlanPricing, PlanLimit, PlanAgent, PlanPermission, PlanModule
from app.models.activity import Activity
from app.models.subscription import Subscription
from app.models.conversation import Conversation, Message
from app.models.audit_log import AuditLog
from app.models.super_admin import SuperAdmin
from app.extensions import db

bp = Blueprint('super_admin', __name__, template_folder='../../templates/super_admin')


# ========================
# Bootstrap (أول دخول — لا يوجد أي SuperAdmin بعد)
# ========================
@bp.route('/setup', methods=['GET', 'POST'])
@limiter.limit('10 per hour')
def setup():
    """
    صفحة إعداد أول مدير للمنصة.
    متاحة فقط عندما لا يوجد أي SuperAdmin في قاعدة البيانات.
    بعد إنشاء أول مدير، تصبح هذه الصفحة 404.
    """
    if SuperAdmin.query.count() > 0:
        # المنصة جاهزة — الصفحة غير متاحة
        from flask import abort
        abort(404)

    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''
        password_confirm = request.form.get('password_confirm') or ''

        errors = []
        if not username or len(username) < 3:
            errors.append('اسم المستخدم يجب أن يكون 3 أحرف على الأقل')
        if '@' not in email or len(email) < 5:
            errors.append('أدخل بريداً إلكترونياً صحيحاً')
        if len(password) < 8:
            errors.append('كلمة المرور يجب أن تكون 8 أحرف على الأقل')
        if password != password_confirm:
            errors.append('تأكيد كلمة المرور غير متطابق')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('super_admin/setup.html', username=username, email=email)

        # تحقق نهائي من السباق (race) — لو شخص آخر أنشأ في نفس الوقت
        if SuperAdmin.query.count() > 0:
            flash('تم إعداد المنصة بالفعل. يرجى تسجيل الدخول.', 'info')
            return redirect(url_for('super_admin.login'))

        admin = AuthService.create_super_admin(username=username, email=email, password=password)
        # دخول تلقائي بعد الإنشاء
        session.clear()
        session['sa_user_id'] = admin.id
        AuditService.log(
            actor_type='super_admin',
            actor_id=admin.id,
            action='bootstrap_setup',
        )
        flash('🎉 تم إنشاء حساب المدير. مرحباً بك!', 'success')
        return redirect(url_for('super_admin.dashboard'))

    return render_template('super_admin/setup.html')


# ========================
# Login / Logout
# ========================
@bp.route('/login', methods=['GET', 'POST'])
@limiter.limit('5 per minute')
def login():
    # لو لا يوجد أي مدير → حوّل لصفحة الإعداد الأولي
    if SuperAdmin.query.count() == 0:
        return redirect(url_for('super_admin.setup'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        admin = AuthService.login_super_admin(username, password)
        if admin:
            return redirect(url_for('super_admin.dashboard'))
        flash('بيانات غير صحيحة', 'danger')
    return render_template('super_admin/login.html')


@bp.route('/logout', methods=['POST'])
def logout():
    AuthService.logout_super_admin()
    return redirect(url_for('super_admin.login'))


@bp.route('/forgot-password', methods=['GET', 'POST'])
@limiter.limit('8 per hour')
def forgot_password():
    if session.get('sa_user_id'):
        return redirect(url_for('super_admin.dashboard'))
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        if '@' not in email or len(email) < 5:
            flash('أدخل بريداً إلكترونياً صحيحاً.', 'danger')
            return render_template('super_admin/forgot_password.html')
        admin = SuperAdmin.query.filter(func.lower(SuperAdmin.email) == email).first()
        if admin and admin.is_active:
            from app.services.password_reset_service import issue_token, PURPOSE_SUPER_ADMIN
            from app.services.email_service import EmailService

            raw = issue_token(PURPOSE_SUPER_ADMIN, admin.id)
            site = (current_app.config.get('SITE_URL') or '').rstrip('/')
            url = f"{site}/sa/reset-password?t={raw}"
            intro = 'طُلبت إعادة تعيين كلمة مرور حساب إدارة المنصة.'
            mail_on = bool(current_app.config.get('MAIL_ENABLED'))
            sent_ok = EmailService.send_password_reset_link(admin.email, intro, url)
            if not mail_on:
                current_app.logger.warning(
                    '[sa-forgot-password] MAIL_ENABLED=False — لم يُرسل بريد. '
                    'الرابط (استخدمه لمرة واحدة خلال ساعة): %s',
                    url,
                )
                flash(
                    'البريد معطّل في الإعدادات (MAIL_ENABLED=false). لم يُرسل شيء. '
                    'شغّل السيرفر واقرأ سجل الطرفية/اللوغ، أو استخدم الأمر: '
                    'cd flask_saas ثم flask reset-super-admin-password',
                    'warning',
                )
            elif not sent_ok:
                current_app.logger.error(
                    '[sa-forgot-password] فشل SMTP للبريد %s — تحقّق من MAIL_SERVER وMAIL_USERNAME '
                    'وMAIL_PASSWORD و MAIL_DEFAULT_SENDER (يفضّل أن يطابق بريد الإرسال).',
                    admin.email,
                )
                flash(
                    'تعذّر إرسال البريد — تحقّق من إعدادات SMTP في ملف .env '
                    '(مثلاً كلمة مرور التطبيق لجيميل «App Password»، والمنفذ 587 وتفعيل STARTTLS)، '
                    'وتأكد أن MAIL_DEFAULT_SENDER يطابق عادةً نفس MAIL_USERNAME.',
                    'danger',
                )
            else:
                flash(
                    'إذا كان البريد مسجلاً لدينا، ستصلك رسالة تحتوي على رابط إعادة التعيين.',
                    'info',
                )
        else:
            flash(
                'إذا كان البريد مسجلاً لدينا، ستصلك رسالة تحتوي على رابط إعادة التعيين.',
                'info',
            )
        return redirect(url_for('super_admin.login'))
    return render_template('super_admin/forgot_password.html')


@bp.route('/reset-password', methods=['GET', 'POST'])
@limiter.limit('30 per minute')
def reset_password():
    from app.utils.passwords import hash_password
    from app.services.password_reset_service import find_valid_token, PURPOSE_SUPER_ADMIN

    token = (request.args.get('t') or request.form.get('token') or '').strip()
    if request.method == 'GET':
        if not token or not find_valid_token(PURPOSE_SUPER_ADMIN, token):
            flash('الرابط غير صالح أو منتهي.', 'danger')
            return redirect(url_for('super_admin.forgot_password'))
        return render_template('super_admin/reset_password.html', token=token)

    token = (request.form.get('token') or '').strip()
    new = request.form.get('new_password') or ''
    new2 = request.form.get('new_password_confirm') or ''
    if len(new) < 6:
        flash('كلمة المرور يجب أن تكون 6 أحرف على الأقل.', 'danger')
        return render_template('super_admin/reset_password.html', token=token)
    if new != new2:
        flash('تأكيد كلمة المرور غير متطابق.', 'danger')
        return render_template('super_admin/reset_password.html', token=token)
    row = find_valid_token(PURPOSE_SUPER_ADMIN, token)
    if not row:
        flash('الرابط غير صالح أو منتهي.', 'danger')
        return redirect(url_for('super_admin.forgot_password'))
    admin = SuperAdmin.query.get(row.subject_id)
    if not admin or not admin.is_active:
        flash('الحساب غير متاح.', 'danger')
        return redirect(url_for('super_admin.login'))
    admin.password_hash = hash_password(new)
    row.used_at = datetime.utcnow()
    db.session.commit()
    flash('تم تغيير كلمة المرور. سجّل الدخول بالجديدة.', 'success')
    return redirect(url_for('super_admin.login'))


@bp.route('/account/change-password', methods=['GET', 'POST'])
@super_admin_required
def account_change_password():
    from app.utils.passwords import verify_password, hash_password
    from app.services.password_reset_service import revoke_all_for_subject, PURPOSE_SUPER_ADMIN

    if request.method == 'POST':
        cur = request.form.get('current_password') or ''
        new = request.form.get('new_password') or ''
        new2 = request.form.get('new_password_confirm') or ''
        if not cur or not new:
            flash('املأ كلمة المرور الحالية والجديدة.', 'danger')
            return redirect(url_for('super_admin.account_change_password'))
        if len(new) < 6:
            flash('كلمة المرور الجديدة يجب أن تكون 6 أحرف على الأقل.', 'danger')
            return redirect(url_for('super_admin.account_change_password'))
        if new != new2:
            flash('تأكيد كلمة المرور غير متطابق.', 'danger')
            return redirect(url_for('super_admin.account_change_password'))
        admin = g.current_admin
        if not verify_password(admin.password_hash, cur):
            flash('كلمة المرور الحالية غير صحيحة.', 'danger')
            return redirect(url_for('super_admin.account_change_password'))
        admin.password_hash = hash_password(new)
        db.session.commit()
        try:
            revoke_all_for_subject(PURPOSE_SUPER_ADMIN, admin.id)
        except Exception:
            pass
        flash('تم تغيير كلمة المرور.', 'success')
        return redirect(url_for('super_admin.account_change_password'))
    return render_template('super_admin/change_password.html')


# ========================
# Dashboard
# ========================
@bp.route('/')
@super_admin_required
def dashboard():
    stats = {
        'total_tenants': Tenant.query.count(),
        'active_tenants': Tenant.query.filter_by(status='active').count(),
        'pending_tenants': Tenant.query.filter_by(status='pending').count(),
        'total_plans': Plan.query.filter_by(status='active').count(),
        'active_subs': Subscription.query.filter_by(status='active').count(),
        'trial_subs': Subscription.query.filter_by(status='trial').count(),
        'total_conversations': Conversation.query.count(),
        'total_messages': Message.query.count(),
    }
    recent_tenants = Tenant.query.order_by(Tenant.created_at.desc()).limit(10).all()
    recent_logs = AuditService.get_recent(limit=20)

    # تنبيه: تجار AI لا يعمل عندهم (يستخدم كاش TTL داخل AIService)
    try:
        from app.services.ai_health_service import AIHealthService
        ai_problems = AIHealthService.scan_tenants_ai(limit=80)
    except Exception as e:
        current_app.logger.warning(f'[Dashboard] AI health scan failed: {e}')
        ai_problems = []

    # استهلاك AI + WhatsApp لكل تاجر (آخر 30 يوماً)
    try:
        from app.models.message_usage import MessageUsage
        usage_breakdown = MessageUsage.per_tenant_breakdown(days=30, limit=50)
    except Exception as e:
        current_app.logger.warning(f'[Dashboard] usage breakdown failed: {e}')
        usage_breakdown = []

    return render_template('super_admin/dashboard.html',
        stats=stats, recent_tenants=recent_tenants, recent_logs=recent_logs,
        ai_problems=ai_problems, usage_breakdown=usage_breakdown)


@bp.route('/tenant-usage')
@super_admin_required
def tenant_usage_report():
    """تقرير استهلاك AI + واتساب لكل تاجر (فترة قابلة للتغيير)."""
    days = request.args.get('days', default=30, type=int) or 30
    if days < 1:
        days = 30
    if days > 366:
        days = 366

    try:
        from app.models.message_usage import MessageUsage
        usage_breakdown = MessageUsage.per_tenant_breakdown(days=days, limit=500)
    except Exception as e:
        current_app.logger.warning(f'[tenant-usage] breakdown failed: {e}')
        usage_breakdown = []

    return render_template(
        'super_admin/tenant_usage_report.html',
        usage_breakdown=usage_breakdown,
        usage_days=days,
    )


# ========================
# Tenants Management
# ========================
@bp.route('/tenants')
@super_admin_required
def tenants_list():
    status_filter = request.args.get('status')
    q = Tenant.query
    if status_filter:
        q = q.filter_by(status=status_filter)
    tenants = q.order_by(Tenant.created_at.desc()).all()
    return render_template('super_admin/tenants.html', tenants=tenants, status_filter=status_filter)


@bp.route('/tenants/<int:id>')
@super_admin_required
def tenant_detail(id):
    tenant = Tenant.query.get_or_404(id)
    return render_template('super_admin/tenant_detail.html', tenant=tenant)


@bp.route('/tenants/<int:id>/suspend', methods=['POST'])
@super_admin_required
def tenant_suspend(id):
    TenantService.suspend_tenant(id)
    flash('تم تعليق المستأجر', 'warning')
    return redirect(url_for('super_admin.tenant_detail', id=id))


@bp.route('/tenants/<int:id>/activate', methods=['POST'])
@super_admin_required
def tenant_activate(id):
    TenantService.activate_tenant(id)
    flash('تم تفعيل المستأجر', 'success')
    return redirect(url_for('super_admin.tenant_detail', id=id))


@bp.route('/tenants/<int:id>/renew_subscription', methods=['POST'])
@super_admin_required
def tenant_renew_subscription(id):
    tenant = Tenant.query.get_or_404(id)
    sub = tenant.subscription
    if not sub:
        flash('لا يوجد اشتراك لهذا المستأجر', 'danger')
        return redirect(url_for('super_admin.tenant_detail', id=id))
        
    days = int(request.form.get('days', 30))
    sub.status = 'active'
    if not sub.ends_at or sub.ends_at < datetime.utcnow():
        from datetime import timedelta
        sub.ends_at = datetime.utcnow() + timedelta(days=days)
    else:
        from datetime import timedelta
        sub.ends_at = sub.ends_at + timedelta(days=days)
        
    sub.chats_used_this_month = 0
    sub.ai_calls_this_month = 0
    sub.usage_reset_date = datetime.utcnow().date()
    db.session.commit()
    
    from app.services.audit_service import AuditService
    AuditService.log(
        actor_type='super_admin',
        action='subscription_renewed',
        tenant_id=tenant.id,
        extra_data={'days_added': days}
    )
    flash(f'تم تجديد الاشتراك وإعادة تعيين الاستهلاك بنجاح. أضيف {days} يوم.', 'success')
    return redirect(url_for('super_admin.tenant_detail', id=id))



@bp.route('/tenants/<int:id>/approve_request', methods=['POST'])
@super_admin_required
def tenant_approve_request(id):
    """قبول طلب الاشتراك."""
    ok, info = TenantService.approve_request(id)
    if ok:
        flash(info, 'success')
    else:
        flash(f'تعذّرت الموافقة: {info}', 'danger')
    return redirect(url_for('super_admin.tenant_detail', id=id))


@bp.route('/tenants/<int:id>/reject_request', methods=['POST'])
@super_admin_required
def tenant_reject_request(id):
    """رفض طلب الاشتراك."""
    reason = (request.form.get('reason') or '').strip()
    ok = TenantService.reject_request(id, reason)
    if ok:
        flash('تم رفض الطلب.', 'warning')
    else:
        flash('تعذّر رفض الطلب.', 'danger')
    return redirect(url_for('super_admin.tenants_list', status='cancelled'))


@bp.route('/tenants/<int:id>/delete', methods=['POST'])
@super_admin_required
def tenant_delete(id):
    from app.services.tenant_deletion_service import TenantDeletionService

    tenant = Tenant.query.get_or_404(id)
    biz = tenant.business_name
    TenantDeletionService.purge_rows_for_tenant(id)
    AuditService.log(
        actor_type='super_admin',
        actor_id=g.current_admin.id,
        tenant_id=None,
        action='tenant_deleted',
        target=f'tenant:{id}',
        extra_data={'deleted_tenant_id': id, 'business_name': biz},
    )
    tenant = Tenant.query.get(id)
    if not tenant:
        flash('المستأجر غير موجود', 'danger')
        return redirect(url_for('super_admin.tenants_list'))
    TenantDeletionService.delete_tenant_object(tenant)
    db.session.commit()
    flash('تم حذف المستأجر', 'success')
    return redirect(url_for('super_admin.tenants_list'))


# ========================
# Plans Management (CRUD)
# ========================
@bp.route('/plans')
@super_admin_required
def plans_list():
    plans = Plan.query.order_by(Plan.sort_order).all()
    return render_template('super_admin/plans.html', plans=plans)


@bp.route('/plans/new', methods=['GET', 'POST'])
@bp.route('/plans/<int:id>/edit', methods=['GET', 'POST'])
@super_admin_required
def plan_form(id=None):
    plan = Plan.query.get(id) if id else None

    if request.method == 'POST':
        data = request.form
        if not plan:
            plan = Plan()
            db.session.add(plan)
            plan.pricing = PlanPricing()
            plan.limits = PlanLimit()

        # Update base plan fields
        plan.code = data['code']
        plan.name_ar = data['name_ar']
        plan.name_en = data['name_en']
        plan.description_ar = data.get('description', '')
        plan.description_en = data.get('description', '')
        plan.status = 'active' if 'is_active' in data else 'draft'
        plan.is_popular = 'is_featured' in data
        plan.sort_order = int(data.get('sort_order', 0))
        plan.trial_days = int(data.get('trial_days', 14))

        # Update pricing
        if not plan.pricing:
            plan.pricing = PlanPricing(plan_id=plan.id)
            db.session.add(plan.pricing)
        plan.pricing.price_monthly = float(data.get('price_monthly', 0))
        plan.pricing.price_yearly = float(data.get('price_yearly', 0))
        plan.pricing.currency = data.get('currency', 'SAR')

        # Update limits
        if not plan.limits:
            plan.limits = PlanLimit(plan_id=plan.id)
            db.session.add(plan.limits)
        plan.limits.max_users = int(data.get('max_users', 1))
        plan.limits.max_branches = int(data.get('max_branches', 1))
        
        db.session.flush() # ensure plan has ID if newly created

        # Update max chats (we can map it to max_conversations in PlanAgent for generic AI agent)
        # Assuming we just keep it simple, or create a specific module/limit if required.
        # But wait, max_chats_per_month is not directly in PlanLimit. 
        # PlanAgent has max_conversations, monthly_usage_limit.
        agent = PlanAgent.query.filter_by(plan_id=plan.id, agent_type='chat').first()
        if not agent:
            agent = PlanAgent(plan_id=plan.id, agent_type='chat', is_enabled=True)
            db.session.add(agent)
        agent.monthly_usage_limit = int(data.get('max_chats_per_month', 1000))
        
        # Features (Modules/Permissions)
        feature_keys = ['whatsapp', 'analytics', 'custom_branding', 'priority_support']
        for key in feature_keys:
            is_enabled = f'feat_{key}' in data
            module = PlanModule.query.filter_by(plan_id=plan.id, module_name=key).first()
            if not module:
                module = PlanModule(plan_id=plan.id, module_name=key)
                db.session.add(module)
            module.is_enabled = is_enabled

        db.session.commit()
        flash('تم حفظ الباقة', 'success')
        return redirect(url_for('super_admin.plans_list'))

    return render_template('super_admin/plan_form.html', plan=plan)


@bp.route('/plans/<int:id>/delete', methods=['POST'])
@super_admin_required
def plan_delete(id):
    plan = Plan.query.get_or_404(id)
    db.session.delete(plan)
    db.session.commit()
    flash('تم حذف الباقة', 'success')
    return redirect(url_for('super_admin.plans_list'))


# ========================
# Activities Management
# ========================
@bp.route('/activities')
@super_admin_required
def activities_list():
    activities = Activity.query.order_by(Activity.sort_order).all()
    return render_template('super_admin/activities.html', activities=activities)


# ========================
# Audit Logs
# ========================
@bp.route('/audit-logs')
@super_admin_required
def audit_logs():
    logs = AuditService.get_recent(limit=100)
    return render_template('super_admin/audit_logs.html', logs=logs)


# ========================
# System Health
# ========================
@bp.route('/system')
@super_admin_required
def system_info():
    """نفس صفحة إعدادات النظام — التوجيه لتفادي عرض القالب بدون سياق (settings_by_cat)."""
    return redirect(url_for('admin_system.index'))

"""
app/blueprints/tenant.py — لوحة تحكم العميل (/app)
تشمل: Setup → Login → Dashboard → Profile → Settings → Billing → Conversations
"""
import uuid
from datetime import datetime
from pathlib import Path
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, session, current_app
from sqlalchemy import func
from werkzeug.utils import secure_filename
from flask_limiter.util import get_remote_address

from app.extensions import db, limiter
from app.decorators import tenant_required, tenant_owner_required
from app.models.tenant import Tenant
from app.models.tenant_user import TenantUser
from app.services.auth_service import AuthService
from app.services.tenant_service import TenantService
from app.services.plan_service import PlanService
from app.services.activity_service import ActivityService
from app.utils.tokens import SetupTokenManager

bp = Blueprint('tenant', __name__, template_folder='../../templates/tenant')


def _delete_account_send_code_key():
    uid = session.get('tenant_user_id')
    return f'tenant_del_code_u:{uid}' if uid else get_remote_address()


# ========================
# Setup (أول مرة بعد التسجيل)
# ========================
@bp.route('/setup', methods=['GET', 'POST'])
@limiter.limit('10 per hour')
def setup():
    """
    صفحة إعداد الحساب — يصل إليها العميل عبر token لمرة واحدة.
    يحدد username + password ثم يُنشأ tenant_user (owner).
    """
    token = request.args.get('token') or request.form.get('token')
    if not token:
        flash('رابط غير صالح', 'danger')
        return redirect(url_for('public.home'))

    tenant_id = SetupTokenManager.verify(token)
    if not tenant_id:
        flash('الرابط منتهي أو غير صالح. يرجى التسجيل مجدداً.', 'danger')
        return redirect(url_for('registration.step1'))

    tenant = Tenant.query.get(tenant_id)
    if not tenant:
        flash('الحساب غير موجود', 'danger')
        return redirect(url_for('public.home'))

    if tenant.setup_completed:
        flash('تم إعداد هذا الحساب مسبقاً. يرجى تسجيل الدخول.', 'info')
        return redirect(url_for('tenant.login'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        password_confirm = request.form.get('password_confirm', '')

        errors = []
        if not username or len(username) < 3:
            errors.append('اسم المستخدم يجب أن يكون 3 أحرف على الأقل')
        if not password or len(password) < 6:
            errors.append('كلمة المرور يجب أن تكون 6 أحرف على الأقل')
        if password != password_confirm:
            errors.append('كلمة المرور غير متطابقة')

        # التحقق من عدم تكرار username
        if TenantUser.query.filter_by(tenant_id=tenant.id, username=username).first():
            errors.append('اسم المستخدم مستخدم مسبقاً')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('tenant/setup.html', tenant=tenant, token=token, username=username)

        # إنشاء المستخدم (owner)
        user = AuthService.create_tenant_user(
            tenant_id=tenant.id,
            username=username,
            email=tenant.owner_email,
            password=password,
            full_name=tenant.owner_full_name,
            phone=tenant.owner_phone,
            role='owner',
        )

        # إكمال الإعداد
        TenantService.complete_setup(tenant.id)

        # تسجيل الدخول تلقائياً
        session.clear()
        session['tenant_user_id'] = user.id
        session['tenant_id'] = tenant.id

        flash(f'مرحباً {tenant.owner_full_name}! تم إعداد حسابك بنجاح 🎉', 'success')
        return redirect(url_for('tenant.dashboard'))

    return render_template('tenant/setup.html', tenant=tenant, token=token)


# ========================
# Login / Logout
# ========================
@bp.route('/login', methods=['GET', 'POST'])
@limiter.limit('10 per minute')
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = AuthService.login_tenant_user(username, password)
        if user:
            tenant = Tenant.query.get(user.tenant_id)
            flash(f'مرحباً {user.full_name or user.username}', 'success')
            return redirect(url_for('tenant.dashboard'))
        flash('اسم المستخدم أو كلمة المرور غير صحيحة', 'danger')
    return render_template('tenant/login.html')


@bp.route('/logout', methods=['POST'])
def logout():
    AuthService.logout_tenant_user()
    flash('تم تسجيل الخروج', 'info')
    return redirect(url_for('tenant.login'))


@bp.route('/forgot-password', methods=['GET', 'POST'])
@limiter.limit('8 per hour')
def forgot_password():
    """طلب رابط إعادة تعيين كلمة المرور (بريد المستخدم المسجّل في لوحة النشاط)."""
    if session.get('tenant_user_id'):
        return redirect(url_for('tenant.dashboard'))
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        if '@' not in email or len(email) < 5:
            flash('أدخل بريداً إلكترونياً صحيحاً.', 'danger')
            return render_template('tenant/forgot_password.html')
        from app.services.password_reset_service import issue_token, PURPOSE_TENANT_USER
        from app.services.email_service import EmailService

        users = (
            TenantUser.query.filter(
                func.lower(TenantUser.email) == email,
                TenantUser.is_active.is_(True),
            )
            .limit(8)
            .all()
        )
        
        if not users:
            flash('البريد الإلكتروني غير صحيح أو غير مسجل في النظام.', 'danger')
            return render_template('tenant/forgot_password.html')

        site = (current_app.config.get('SITE_URL') or '').rstrip('/')
        for u in users[:5]:
            tenant = Tenant.query.get(u.tenant_id)
            if not tenant:
                continue
            raw = issue_token(PURPOSE_TENANT_USER, u.id)
            url = f"{site}/app/reset-password?t={raw}"
            intro = (
                f"طُلبت إعادة تعيين كلمة المرور لحسابك في «{tenant.business_name}» "
                f"(اسم الدخول: {u.username})."
            )
            EmailService.send_password_reset_link(u.email, intro, url)
        flash(
            'تم إرسال رابط إعادة التعيين إلى بريدك الإلكتروني.',
            'info',
        )
        return redirect(url_for('tenant.login'))
    return render_template('tenant/forgot_password.html')


@bp.route('/reset-password', methods=['GET', 'POST'])
@limiter.limit('30 per minute')
def reset_password():
    """إعادة تعيين كلمة المرور عبر الرابط المرسل بالبريد."""
    from app.utils.passwords import hash_password
    from app.services.password_reset_service import find_valid_token, PURPOSE_TENANT_USER

    token = (request.args.get('t') or request.form.get('token') or '').strip()
    if request.method == 'GET':
        if not token or not find_valid_token(PURPOSE_TENANT_USER, token):
            flash('الرابط غير صالح أو منتهي. اطلب رابطاً جديداً من «نسيت كلمة المرور».', 'danger')
            return redirect(url_for('tenant.forgot_password'))
        return render_template('tenant/reset_password.html', token=token)

    token = (request.form.get('token') or '').strip()
    new = request.form.get('new_password') or ''
    new2 = request.form.get('new_password_confirm') or ''
    if len(new) < 6:
        flash('كلمة المرور يجب أن تكون 6 أحرف على الأقل.', 'danger')
        return render_template('tenant/reset_password.html', token=token)
    if new != new2:
        flash('تأكيد كلمة المرور غير متطابق.', 'danger')
        return render_template('tenant/reset_password.html', token=token)
    row = find_valid_token(PURPOSE_TENANT_USER, token)
    if not row:
        flash('الرابط غير صالح أو منتهي.', 'danger')
        return redirect(url_for('tenant.forgot_password'))
    u = TenantUser.query.get(row.subject_id)
    if not u or not u.is_active:
        flash('الحساب غير متاح.', 'danger')
        return redirect(url_for('tenant.login'))
    u.password_hash = hash_password(new)
    row.used_at = datetime.utcnow()
    db.session.commit()
    flash('تم تغيير كلمة المرور. يمكنك تسجيل الدخول الآن.', 'success')
    return redirect(url_for('tenant.login'))


# ========================
# Dashboard (يتغير حسب النشاط)
# ========================
@bp.route('/dashboard')
@tenant_required
def dashboard():
    tenant = g.current_tenant
    stats = TenantService.get_dashboard_stats(tenant)

    # تحميل handler النشاط لبيانات إضافية
    handler = ActivityService.load_handler(tenant.activity.code) if tenant.activity else None
    activity_data = handler.get_dashboard_data(tenant) if handler else {}

    # === تحليلات ===
    analytics = _build_analytics(tenant)

    return render_template('tenant/dashboard.html',
        tenant=tenant, stats=stats, activity_data=activity_data, analytics=analytics)


def _build_analytics(tenant):
    """بناء بيانات التحليلات حسب نوع النشاط."""
    result = {'top_items': [], 'recent_bookings': 0, 'total_bookings': 0}

    try:
        from app.models.booking import Booking
        result['total_bookings'] = Booking.query.filter_by(tenant_id=tenant.id).count()
        result['recent_bookings'] = Booking.query.filter_by(tenant_id=tenant.id, status='new').count()
        result['confirmed_bookings'] = Booking.query.filter_by(tenant_id=tenant.id, status='confirmed').count()
    except Exception:
        pass

    try:
        if tenant.activity and tenant.activity.code == 'hotel':
            from app.models.hotel_models import Unit
            from sqlalchemy import func
            from app.models.booking import Booking
            
            # أكثر نوع وحدة مطلوب
            top = db.session.query(
                Booking.requested_unit_type, func.count(Booking.id).label('cnt')
            ).filter_by(tenant_id=tenant.id).group_by(
                Booking.requested_unit_type
            ).order_by(func.count(Booking.id).desc()).limit(5).all()
            type_labels = {'room': 'غرفة', 'apartment': 'شقة', 'suite': 'جناح', 'villa': 'فيلا'}
            result['top_items'] = [
                {'name': type_labels.get(t[0], t[0] or 'غير محدد'), 'count': t[1]}
                for t in top if t[0]
            ]

            # إحصائيات الوحدات
            result['total_units'] = Unit.query.filter_by(tenant_id=tenant.id).count()
            result['available_units'] = Unit.query.filter_by(tenant_id=tenant.id, status='available').count()
            result['booked_units'] = Unit.query.filter_by(tenant_id=tenant.id, status='booked').count()
            result['maintenance_units'] = Unit.query.filter_by(tenant_id=tenant.id, status='maintenance').count()
            
            # مبيعات الفندق (حجوزات مؤكدة)
            result['hotel_sales'] = db.session.query(func.sum(Booking.total_amount)).filter(
                Booking.tenant_id == tenant.id,
                Booking.status.in_(['confirmed', 'completed'])
            ).scalar() or 0
            
            # مبيعات العقود (للنمط الشهري)
            try:
                from app.models.contract import Contract
                result['contract_sales'] = db.session.query(func.sum(Contract.total_amount)).filter_by(
                    tenant_id=tenant.id, status='signed'
                ).scalar() or 0
                result['active_contracts'] = Contract.query.filter_by(tenant_id=tenant.id, status='signed').count()
            except:
                result['contract_sales'] = 0
                result['active_contracts'] = 0

        elif tenant.activity and tenant.activity.code == 'restaurant':
            # أكثر صنف مطلوب (من الرسائل)
            from app.models.restaurant_models import MenuItem
            from app.models.conversation import Message
            from sqlalchemy import func

            # أكثر أصناف شعبية (is_popular أو الأكثر ذكراً)
            popular = MenuItem.query.filter_by(
                tenant_id=tenant.id, is_popular=True, is_available=True
            ).limit(5).all()
            result['top_items'] = [
                {'name': item.name, 'count': 0, 'price': str(item.final_price)}
                for item in popular
            ]

            # إحصائيات المنيو
            result['total_items'] = MenuItem.query.filter_by(tenant_id=tenant.id).count()
            result['available_items'] = MenuItem.query.filter_by(tenant_id=tenant.id, is_available=True).count()
    except Exception:
        pass

    # إحصائيات الشات
    try:
        from app.models.custom_reply import CustomReply
        result['custom_replies'] = CustomReply.query.filter_by(tenant_id=tenant.id, is_active=True).count()
        result['learned_replies'] = CustomReply.query.filter_by(tenant_id=tenant.id, source='learned').count()
    except Exception:
        result['custom_replies'] = 0
        result['learned_replies'] = 0

    return result


# ========================
# AI Agents Hub
# ========================
@bp.route('/ai-agents')
@tenant_required
def ai_agents():
    """شاشة إدارة فريق الذكاء الاصطناعي في لوحة التاجر."""
    tenant = g.current_tenant
    return render_template('tenant/ai_agents.html', tenant=tenant)


# ========================
# Profile
# ========================
@bp.route('/profile', methods=['GET', 'POST'])
@tenant_required
def profile():
    tenant = g.current_tenant
    if request.method == 'POST':
        tenant.business_name = request.form.get('business_name', tenant.business_name)
        tenant.owner_phone = request.form.get('phone', tenant.owner_phone)
        tenant.primary_color = request.form.get('primary_color', tenant.primary_color)

        # حقول الحساب البنكي (تظهر للعميل عند التحويل)
        if 'bank_name' in request.form:
            tenant.bank_name = (request.form.get('bank_name') or '').strip()[:100]
        if 'bank_account_name' in request.form:
            tenant.bank_account_name = (request.form.get('bank_account_name') or '').strip()[:200]
        if 'bank_account_number' in request.form:
            tenant.bank_account_number = (request.form.get('bank_account_number') or '').strip()[:40]
        if 'bank_iban' in request.form:
            tenant.bank_iban = (request.form.get('bank_iban') or '').strip().replace(' ', '').upper()[:40]

        # رفع الشعار
        logo_file = request.files.get('logo')
        if logo_file and logo_file.filename:
            saved_path = _save_logo(tenant, logo_file)
            if saved_path:
                tenant.logo_path = saved_path

        db.session.commit()
        flash('تم حفظ التعديلات', 'success')
        return redirect(url_for('tenant.profile'))
    return render_template('tenant/profile.html', tenant=tenant)


@bp.route('/profile/change-password', methods=['POST'])
@tenant_required
def profile_change_password():
    """تغيير كلمة مرور المستخدم الحالي في لوحة النشاط."""
    from app.utils.passwords import verify_password, hash_password
    from app.services.password_reset_service import revoke_all_for_subject, PURPOSE_TENANT_USER

    cur = request.form.get('current_password') or ''
    new = request.form.get('new_password') or ''
    new2 = request.form.get('new_password_confirm') or ''
    if not cur or not new:
        flash('املأ كلمة المرور الحالية والجديدة.', 'danger')
        return redirect(url_for('tenant.profile'))
    if len(new) < 6:
        flash('كلمة المرور الجديدة يجب أن تكون 6 أحرف على الأقل.', 'danger')
        return redirect(url_for('tenant.profile'))
    if new != new2:
        flash('تأكيد كلمة المرور غير متطابق.', 'danger')
        return redirect(url_for('tenant.profile'))
    u = g.current_user
    if not verify_password(u.password_hash, cur):
        flash('كلمة المرور الحالية غير صحيحة.', 'danger')
        return redirect(url_for('tenant.profile'))
    u.password_hash = hash_password(new)
    db.session.commit()
    try:
        revoke_all_for_subject(PURPOSE_TENANT_USER, u.id)
    except Exception:
        pass
    flash('تم تغيير كلمة المرور.', 'success')
    return redirect(url_for('tenant.profile'))


@bp.route('/remove-logo', methods=['POST'])
@tenant_required
def remove_logo():
    """حذف الشعار."""
    tenant = g.current_tenant
    if tenant.logo_path:
        # حذف الملف من السيرفر
        try:
            logo_full = Path(current_app.static_folder) / tenant.logo_path.replace('/static/', '')
            if logo_full.exists():
                logo_full.unlink()
        except Exception:
            pass
        tenant.logo_path = ''
        db.session.commit()
        flash('تم حذف الشعار', 'info')
    return redirect(url_for('tenant.profile'))


def _save_logo(tenant, file):
    """حفظ ملف الشعار وإرجاع المسار."""
    allowed = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg'}
    safe = secure_filename(file.filename)
    if not safe or '.' not in safe:
        flash('نوع الملف غير مدعوم', 'danger')
        return None
    ext = '.' + safe.rsplit('.', 1)[1].lower()
    if ext not in allowed:
        flash('نوع الملف غير مدعوم. المسموح: JPG, PNG, GIF, WebP, SVG', 'danger')
        return None

    # محاولة Cloudinary أولاً (لا يضيع الشعار في إعادة التشغيل)
    try:
        from app.services.cloudinary_service import CloudinaryService
        if CloudinaryService.is_configured() and ext != '.svg':
            file.stream.seek(0)
            res = CloudinaryService.upload_image(
                file=file.stream,
                folder=f'logos/tenant_{tenant.id}',
                tags=['logo'],
            )
            if res.get('success') and res.get('url'):
                return res['url']
    except Exception as e:
        current_app.logger.warning(f'[tenant] logo cloudinary failed: {e}')

    # Fallback: تخزين محلي
    upload_dir = Path(current_app.static_folder) / 'uploads' / 'logos'
    upload_dir.mkdir(parents=True, exist_ok=True)

    filename = f'logo_{tenant.id}_{uuid.uuid4().hex[:8]}{ext}'
    file.save(upload_dir / filename)

    return url_for('static', filename=f'uploads/logos/{filename}')


# ========================
# Settings (إعدادات النشاط)
# ========================
@bp.route('/settings', methods=['GET', 'POST'])
@tenant_required
def settings():
    tenant = g.current_tenant
    if request.method == 'POST':
        # إعدادات التذكير العامة
        tenant.settings = tenant.settings or {}
        
        req_email = 'reminder_send_email' in request.form
        req_whatsapp = 'reminder_send_whatsapp' in request.form
        req_sms = 'reminder_send_sms' in request.form
        
        # التحقق من الواتساب
        if req_whatsapp:
            from app.services.whatsapp_service import WhatsAppService
            wa_config = WhatsAppService._get_config(tenant.id)
            if not wa_config or not wa_config.is_active:
                req_whatsapp = False
                flash('لم يتم تفعيل الواتساب كقناة للتذكير. الرجاء ربطه وتفعيله أولاً.', 'danger')
                
        # التحقق من الـ SMS
        if req_sms:
            from app.models.tenant_integrations import TenantIntegration
            sms_config = TenantIntegration.query.filter_by(tenant_id=tenant.id, is_active=True).first()
            if not sms_config or not sms_config.api_key:
                req_sms = False
                flash('لم يتم تفعيل الرسائل النصية للتذكير. الرجاء ربط مزود SMS أولاً.', 'danger')
                
        tenant.settings['reminder_send_email'] = req_email
        tenant.settings['reminder_send_whatsapp'] = req_whatsapp
        tenant.settings['reminder_send_sms'] = req_sms
        
        tenant.settings['global_reminder_message'] = request.form.get('global_reminder_message', '').strip()

        # حفظ activity_data كـ JSON
        tenant.activity_data = tenant.activity_data or {}
        for key in request.form:
            if key.startswith('activity_'):
                field_key = key.replace('activity_', '')
                tenant.activity_data[field_key] = request.form[key]
                
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(tenant, "settings")
        flag_modified(tenant, "activity_data")

        db.session.commit()
        flash('تم حفظ الإعدادات بنجاح', 'success')
        return redirect(url_for('tenant.settings'))

    activity = tenant.activity
    return render_template('tenant/settings.html',
        tenant=tenant, activity=activity)


# ========================
# Billing / Subscription
# ========================
@bp.route('/billing')
@tenant_required
def billing():
    tenant = g.current_tenant
    plans = PlanService.get_active_plans()
    return render_template('tenant/billing.html', tenant=tenant, plans=plans)


@bp.route('/billing/change-plan/<int:plan_id>', methods=['POST'])
@tenant_owner_required
def change_plan(plan_id):
    PlanService.change_plan(g.current_tenant.id, plan_id)
    flash('تم تغيير الباقة', 'success')
    return redirect(url_for('tenant.billing'))


# ========================
# Chat Link + QR
# ========================
@bp.route('/chat-link')
@tenant_required
def chat_link():
    tenant = g.current_tenant
    return render_template('tenant/chat_link.html', tenant=tenant)


@bp.route('/chat-link/customize', methods=['POST'])
@tenant_owner_required
def customize_slug():
    """تخصيص رابط الشات (slug)."""
    import re
    tenant = g.current_tenant
    new_slug = (request.form.get('new_slug') or '').strip().lower()

    # تحقق من الصيغة: حروف صغيرة، أرقام، شرطة، 3-32 حرف
    if not re.match(r'^[a-z0-9][a-z0-9-]{1,30}[a-z0-9]$', new_slug):
        flash(
            'الرابط يجب أن يحتوي على حروف إنجليزية صغيرة وأرقام وشرطات فقط (3-32 حرف)',
            'danger',
        )
        return redirect(url_for('tenant.chat_link'))

    # كلمات محجوزة
    reserved = {
        'admin', 'api', 'app', 'login', 'logout', 'register', 'sa',
        'super-admin', 'tenant', 'user', 'static', 'public', 'home',
        'settings', 'dashboard', 'chat', 'help', 'support', 'about',
    }
    if new_slug in reserved:
        flash('هذا الرابط محجوز، يرجى اختيار رابط آخر', 'danger')
        return redirect(url_for('tenant.chat_link'))

    # التحقق من عدم تكرار الـ slug
    existing = Tenant.query.filter(
        Tenant.slug == new_slug,
        Tenant.id != tenant.id,
    ).first()
    if existing:
        flash('هذا الرابط مستخدم من قِبل نشاط آخر، يرجى اختيار رابط مختلف', 'danger')
        return redirect(url_for('tenant.chat_link'))

    old_slug = tenant.slug
    tenant.slug = new_slug
    try:
        db.session.commit()
        flash(f'تم تغيير الرابط بنجاح من "{old_slug}" إلى "{new_slug}"', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'[customize_slug] error: {e}')
        flash('حدث خطأ، يرجى المحاولة مرة أخرى', 'danger')

    return redirect(url_for('tenant.chat_link'))


# ========================
# Conversations
# ========================
@bp.route('/conversations')
@tenant_required
def conversations():
    from app.models.conversation import Conversation
    convs = Conversation.query.filter_by(
        tenant_id=g.current_tenant.id
    ).order_by(Conversation.updated_at.desc()).all()
    return render_template(
        'tenant/conversations.html',
        tenant=g.current_tenant,
        conversations=convs,
    )


# ========================
# Team (الموظفون - لاحقاً)
# ========================
@bp.route('/team')
@tenant_owner_required
def team():
    users = g.current_tenant.users.all()
    return render_template(
        'tenant/team.html',
        users=users,
        tenant=g.current_tenant,
    )


# ==================== Branches (مشترك لكل الأنشطة) ====================
@bp.route('/branches')
@tenant_required
def branches():
    from app.models.branch import Branch
    items = Branch.query.filter_by(tenant_id=g.current_tenant.id).all()
    return render_template('tenant/hotel/branches.html', branches=items)


@bp.route('/branches/new', methods=['GET', 'POST'])
@bp.route('/branches/<int:id>/edit', methods=['GET', 'POST'])
@tenant_required
def branch_form(id=None):
    from app.models.branch import Branch
    item = Branch.query.filter_by(id=id, tenant_id=g.current_tenant.id).first() if id else None

    if request.method == 'POST':
        if not item:
            item = Branch(tenant_id=g.current_tenant.id)
            db.session.add(item)
        item.name = request.form['name']
        item.address = request.form.get('address', '')
        item.city = request.form.get('city', '')
        item.map_link = request.form.get('map_link', '')
        item.phone = request.form.get('phone', '')
        item.whatsapp = request.form.get('whatsapp', '')
        item.email = request.form.get('email', '')
        item.complaints_email = request.form.get('complaints_email', '')
        item.is_main = 'is_main' in request.form
        from app.utils.working_hours_ui import working_hours_from_request

        item.working_hours = working_hours_from_request(request.form)
        db.session.commit()
        flash('تم حفظ الفرع', 'success')
        return redirect(url_for('tenant.branches'))
    from app.utils.working_hours_ui import working_hours_form_defaults

    hours_form = working_hours_form_defaults(item.working_hours if item else None)
    return render_template(
        'tenant/hotel/branch_form.html',
        branch=item,
        hours_form=hours_form,
        cancel_url=url_for('tenant.branches'),
    )


@bp.route('/branches/<int:id>/delete', methods=['POST'])
@tenant_required
def branch_delete(id):
    from app.models.branch import Branch
    item = Branch.query.filter_by(id=id, tenant_id=g.current_tenant.id).first_or_404()
    db.session.delete(item)
    db.session.commit()
    flash('تم حذف الفرع', 'success')
    return redirect(url_for('tenant.branches'))


# ==================== حذف النشاط (الحساب كاملاً) ====================
@bp.route('/delete-account/send-code', methods=['POST'])
@limiter.limit('5 per hour', key_func=_delete_account_send_code_key)
@tenant_owner_required
def delete_account_send_code():
    """إرسال رمز تحقق إلى بريد المالك المسجّل عند التسجيل."""
    from app.services.email_service import EmailService
    from app.services.tenant_deletion_service import TenantDeletionService

    tenant = g.current_tenant
    email = (tenant.owner_email or '').strip()
    if not email:
        flash('لا يوجد بريد مالك مسجّل. تواصل مع الدعم لحذف الحساب.', 'danger')
        return redirect(url_for('tenant.delete_account'))

    if TenantDeletionService.count_recent_code_sends(tenant.id) >= TenantDeletionService.MAX_SENDS_PER_HOUR:
        flash('تجاوزت الحد المسموح لطلب الرمز. حاول لاحقاً.', 'warning')
        return redirect(url_for('tenant.delete_account'))

    code = TenantDeletionService.issue_email_code(tenant.id)
    EmailService.send_tenant_deletion_code(email, tenant.business_name, code)
    if not current_app.config.get('MAIL_ENABLED', False):
        flash(
            f'وضع التطوير: البريد غير مفعّل. الرمز الحالي: {code} (يظهر أيضاً في سجل السيرفر)',
            'warning',
        )
    else:
        flash('تم إرسال رمز التحقق إلى بريد المالك المسجّل.', 'success')
    return redirect(url_for('tenant.delete_account'))


@bp.route('/delete-account', methods=['GET', 'POST'])
@tenant_owner_required
def delete_account():
    tenant = g.current_tenant
    if request.method == 'POST':
        from app.services.tenant_deletion_service import TenantDeletionService
        from app.utils.passwords import verify_password

        confirm = request.form.get('confirm_name', '').strip()
        if confirm != (tenant.business_name or '').strip():
            flash('اسم النشاط غير مطابق (يجب مطابقة الاسم الحرف بحرف بدون مسافات زائدة في البداية/النهاية). لم يتم الحذف.', 'danger')
            return redirect(url_for('tenant.delete_account'))

        code = (request.form.get('email_code') or '').strip()
        if not TenantDeletionService.verify_latest_code(tenant.id, code):
            flash('رمز التحقق من البريد غير صحيح أو منتهي. اطلب رمزاً جديداً.', 'danger')
            return redirect(url_for('tenant.delete_account'))

        panel_pw = request.form.get('panel_password') or ''
        if not verify_password(g.current_user.password_hash, panel_pw):
            flash('كلمة مرور لوحة التحكم غير صحيحة.', 'danger')
            return redirect(url_for('tenant.delete_account'))

        try:
            TenantDeletionService.delete_tenant_object(tenant)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('delete_account failed: %s', e)
            flash('تعذر إكمال الحذف. تواصل مع الدعم.', 'danger')
            return redirect(url_for('tenant.delete_account'))

        session.clear()
        flash('تم حذف حسابك ونشاطك بالكامل.', 'info')
        return redirect(url_for('public.home'))

    masked = _mask_email(tenant.owner_email or '')
    return render_template('tenant/delete_account.html', tenant=tenant, owner_email_masked=masked)


def _mask_email(email: str) -> str:
    email = (email or '').strip()
    if '@' not in email:
        return email or '—'
    local, _, domain = email.partition('@')
    if len(local) <= 2:
        show = local[0] + '*' if local else '*'
    else:
        show = local[0] + '***' + local[-1]
    return f'{show}@{domain}'

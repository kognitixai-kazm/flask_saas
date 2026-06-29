"""
app/blueprints/registration.py — تدفق طلب الاشتراك (/register)

التدفق المؤقت (قبل تفعيل الدفع الإلكتروني الرسمي):
    خطوة 1: بيانات أساسية (اسم، إيميل، جوال، اسم الشركة)
    خطوة 2: اختيار النشاط → يُسجَّل «طلب وصول» (Tenant بحالة pending)
    صفحة الانتظار: يُراجَع الطلب من الأدمن، وعند الموافقة يصل رابط الإعداد بالبريد.
"""
from flask import Blueprint, render_template, request, session, redirect, url_for, flash, current_app

from app.extensions import db, limiter, csrf
from app.models.tenant import Tenant
from app.services.tenant_service import TenantService
from app.services.activity_service import ActivityService

bp = Blueprint('registration', __name__, template_folder='../../templates/registration')


# ========================
# خطوة 1: البيانات الأساسية
# ========================
@bp.route('/', methods=['GET', 'POST'])
@limiter.limit('10 per hour')
def step1():
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()
        business_name = request.form.get('business_name', '').strip()

        errors = []
        if not full_name:
            errors.append('الاسم الكامل مطلوب')
        if not email or '@' not in email:
            errors.append('بريد إلكتروني صالح مطلوب')
        if not phone:
            errors.append('رقم الجوال مطلوب')
        if not business_name:
            errors.append('اسم المنشأة مطلوب')

        existing = Tenant.query.filter_by(owner_email=email).first()
        if existing:
            errors.append('هذا البريد مسجّل مسبقاً. يرجى تسجيل الدخول.')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('registration/step1.html',
                full_name=full_name, email=email, phone=phone, business_name=business_name)

        session['reg_full_name'] = full_name
        session['reg_email'] = email
        session['reg_phone'] = phone
        session['reg_business_name'] = business_name
        return redirect(url_for('registration.step2'))

    return render_template('registration/step1.html')


# ========================
# خطوة 2: اختيار النشاط → إرسال طلب وصول
# ========================
@bp.route('/activity', methods=['GET', 'POST'])
def step2():
    if 'reg_email' not in session:
        flash('يرجى إكمال البيانات أولاً', 'warning')
        return redirect(url_for('registration.step1'))

    activities = ActivityService.get_active_activities()

    if request.method == 'POST':
        activity_id = request.form.get('activity_id')
        if not activity_id:
            flash('يرجى اختيار نوع النشاط', 'danger')
            return render_template('registration/step2.html', activities=activities)

        # نمط الفندق إن كان النشاط فندقاً
        hotel_mode = (request.form.get('hotel_mode') or '').strip().lower()
        if hotel_mode not in ('daily', 'monthly'):
            hotel_mode = 'daily'  # الافتراضي يشمل الشهري

        try:
            session['reg_activity_id'] = int(activity_id)
            session['reg_hotel_mode'] = hotel_mode
            
            # Generate OTP
            import random
            otp = str(random.randint(100000, 999999))
            session['reg_otp'] = otp
            
            # Send OTP
            from app.services.email_service import EmailService
            EmailService.send_registration_otp(session['reg_email'], otp)
            
            return redirect(url_for('registration.verify'))

        except Exception as e:
            current_app.logger.error(f'Registration OTP error: {e}')
            flash('حدث خطأ أثناء إرسال رمز التحقق. حاول لاحقاً.', 'danger')

    return render_template('registration/step2.html', activities=activities)


# ========================
# خطوة 3: التحقق من البريد (OTP)
# ========================
@bp.route('/verify', methods=['GET', 'POST'])
def verify():
    if 'reg_email' not in session or 'reg_otp' not in session:
        flash('يرجى إكمال البيانات أولاً', 'warning')
        return redirect(url_for('registration.step1'))
        
    if request.method == 'POST':
        user_code = request.form.get('code', '').strip()
        if user_code == session['reg_otp']:
            # OTP verified, create tenant directly
            from app.services.tenant_service import _resolve_default_plan, TenantService
            plan = _resolve_default_plan()
            if not plan:
                flash('لا توجد باقة فعالة للتسجيل. تواصل مع الإدارة.', 'danger')
                return redirect(url_for('registration.step1'))
                
            tenant, setup_url, _ = TenantService.create_tenant(
                business_name=session['reg_business_name'],
                owner_full_name=session['reg_full_name'],
                owner_email=session['reg_email'],
                owner_phone=session['reg_phone'],
                activity_id=session['reg_activity_id'],
                plan_id=plan.id
            )
            
            # Set hotel_mode if needed
            hotel_mode = session.get('reg_hotel_mode')
            if hotel_mode and tenant.activity and (tenant.activity.code or '').lower() == 'hotel':
                ad = dict(tenant.activity_data or {})
                ad['hotel_mode'] = hotel_mode
                tenant.activity_data = ad
                from app.extensions import db as _db
                _db.session.commit()
                
            # Clear session
            for key in list(session.keys()):
                if key.startswith('reg_'):
                    session.pop(key)
                    
            return redirect(setup_url)
            
        else:
            flash('الرمز غير صحيح، يرجى المحاولة مرة أخرى.', 'danger')
            
    return render_template('registration/verify.html', email=session['reg_email'])


# ========================
# (محفوظ مؤقّتاً للتوافق العكسي — يُعيد توجيه لاختيار النشاط)
# ========================
@bp.route('/plan', methods=['GET', 'POST'])
def step3():
    return redirect(url_for('registration.step2'))


# ========================
# صفحة استلام الطلب
# ========================
@bp.route('/success')
def success():
    biz = session.pop('request_business_name', None)
    em = session.pop('request_owner_email', None)
    return render_template('registration/success.html', business_name=biz, owner_email=em)

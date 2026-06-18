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
            tenant = TenantService.request_subscription(
                business_name=session['reg_business_name'],
                owner_full_name=session['reg_full_name'],
                owner_email=session['reg_email'],
                owner_phone=session['reg_phone'],
                activity_id=int(activity_id),
            )

            # احفظ نمط الفندق إن كان النشاط hotel
            try:
                if tenant and tenant.activity and (tenant.activity.code or '').lower() == 'hotel':
                    ad = dict(tenant.activity_data or {})
                    ad['hotel_mode'] = hotel_mode
                    tenant.activity_data = ad
                    from app.extensions import db as _db
                    _db.session.commit()
            except Exception as _e:
                current_app.logger.warning(f'set hotel_mode at registration failed: {_e}')

            for key in list(session.keys()):
                if key.startswith('reg_'):
                    session.pop(key)

            session['request_business_name'] = tenant.business_name
            session['request_owner_email'] = tenant.owner_email

            return redirect(url_for('registration.success'))

        except Exception as e:
            current_app.logger.error(f'Registration request error: {e}')
            flash('حدث خطأ غير متوقع. حاول لاحقاً أو راسلنا.', 'danger')

    return render_template('registration/step2.html', activities=activities)


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

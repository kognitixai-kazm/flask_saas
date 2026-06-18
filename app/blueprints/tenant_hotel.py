"""
app/blueprints/tenant_hotel.py — إدارة بيانات نشاط الفندق (/app/hotel/*)
الفروع + الطوابق + الوحدات + الخدمات — كلها من لوحة التحكم.
"""
import uuid
from pathlib import Path

from flask import Blueprint, render_template, request, redirect, url_for, flash, g, current_app, jsonify
from werkzeug.utils import secure_filename
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.decorators import tenant_required
from app.models.branch import Branch
from app.models.hotel_models import Floor, Unit, HotelService
from app.services.ical_service import ICalService

bp = Blueprint('tenant_hotel', __name__, template_folder='../../templates/tenant/hotel')


def _ensure_hotel(f):
    """يتأكد أن النشاط فندق."""
    from functools import wraps
    @wraps(f)
    @tenant_required
    def decorated(*args, **kwargs):
        if g.current_tenant.activity.code != 'hotel':
            flash('هذا القسم خاص بالفنادق فقط', 'danger')
            return redirect(url_for('tenant.dashboard'))
        return f(*args, **kwargs)
    return decorated


# ==================== نمط الإيجار (يومي / شهري / كلاهما) ====================
@bp.route('/mode', methods=['GET', 'POST'])
@_ensure_hotel
def mode_settings():
    tenant = g.current_tenant
    if request.method == 'POST':
        new_mode = (request.form.get('hotel_mode') or 'daily').strip().lower()
        if new_mode == 'both':  # توافق رجعي
            new_mode = 'daily'
        if new_mode not in ('daily', 'monthly'):
            new_mode = 'daily'
        ad = dict(tenant.activity_data or {})
        ad['hotel_mode'] = new_mode
        tenant.activity_data = ad
        db.session.commit()
        flash('تم تحديث نمط الإيجار. ستظهر الميزات المتعلقة بالنمط المختار فقط.', 'success')
        return redirect(url_for('tenant_hotel.mode_settings'))

    return render_template('tenant/hotel/mode_settings.html',
        current_mode=tenant.hotel_mode)


# ==================== الفروع ====================
@bp.route('/branches')
@_ensure_hotel
def branches():
    items = Branch.query.filter_by(tenant_id=g.current_tenant.id).all()
    return render_template('tenant/hotel/branches.html', branches=items)


@bp.route('/branches/new', methods=['GET', 'POST'])
@bp.route('/branches/<int:id>/edit', methods=['GET', 'POST'])
@_ensure_hotel
def branch_form(id=None):
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
        return redirect(url_for('tenant_hotel.branches'))

    from app.utils.working_hours_ui import working_hours_form_defaults

    hours_form = working_hours_form_defaults(item.working_hours if item else None)
    return render_template(
        'tenant/hotel/branch_form.html',
        branch=item,
        hours_form=hours_form,
        cancel_url=url_for('tenant_hotel.branches'),
    )


@bp.route('/branches/<int:id>/delete', methods=['POST'])
@_ensure_hotel
def branch_delete(id):
    item = Branch.query.filter_by(id=id, tenant_id=g.current_tenant.id).first_or_404()
    db.session.delete(item)
    db.session.commit()
    flash('تم حذف الفرع', 'success')
    return redirect(url_for('tenant_hotel.branches'))


# ==================== الطوابق ====================
@bp.route('/floors')
@_ensure_hotel
def floors():
    items = Floor.query.filter_by(tenant_id=g.current_tenant.id).all()
    return render_template('tenant/hotel/floors.html', floors=items)


@bp.route('/floors/new', methods=['GET', 'POST'])
@bp.route('/floors/<int:id>/edit', methods=['GET', 'POST'])
@_ensure_hotel
def floor_form(id=None):
    item = Floor.query.filter_by(id=id, tenant_id=g.current_tenant.id).first() if id else None
    branches_list = Branch.query.filter_by(tenant_id=g.current_tenant.id).all()

    if request.method == 'POST':
        if not item:
            item = Floor(tenant_id=g.current_tenant.id)
            db.session.add(item)
        item.branch_id = int(request.form['branch_id'])
        item.number = request.form['number']
        item.name = request.form.get('name', '')
        item.notes = request.form.get('notes', '')
        db.session.commit()
        flash('تم حفظ الطابق', 'success')
        return redirect(url_for('tenant_hotel.floors'))

    return render_template('tenant/hotel/floor_form.html', floor=item, branches=branches_list)


@bp.route('/floors/<int:id>/delete', methods=['POST'])
@_ensure_hotel
def floor_delete(id):
    item = Floor.query.filter_by(id=id, tenant_id=g.current_tenant.id).first_or_404()
    db.session.delete(item)
    db.session.commit()
    flash('تم حذف الطابق', 'success')
    return redirect(url_for('tenant_hotel.floors'))


# ==================== الوحدات (غرف/شقق/أجنحة) ====================
@bp.route('/units')
@_ensure_hotel
def units():
    items = Unit.query.filter_by(tenant_id=g.current_tenant.id).all()
    return render_template('tenant/hotel/units.html', units=items)


@bp.route('/units/new', methods=['GET', 'POST'])
@bp.route('/units/<int:id>/edit', methods=['GET', 'POST'])
@_ensure_hotel
def unit_form(id=None):
    item = Unit.query.filter_by(id=id, tenant_id=g.current_tenant.id).first() if id else None
    is_edit = item is not None
    branches_list = Branch.query.filter_by(tenant_id=g.current_tenant.id).all()
    floors_list = Floor.query.filter_by(tenant_id=g.current_tenant.id).all()

    # قاموس الطوابق مجمّعاً حسب branch_id لاستخدامه في JS
    import json as _json
    floors_by_branch = {}
    for f in floors_list:
        floors_by_branch.setdefault(str(f.branch_id), []).append(
            {'id': f.id, 'label': f'طابق {f.number}'}
        )
    floors_by_branch_json = _json.dumps(floors_by_branch, ensure_ascii=False)

    _unit_types = [('room','غرفة'),('apartment','شقة'),('suite','جناح'),('villa','فيلا')]

    if request.method == 'POST':
        # احفظ id الأصلي قبل أي تعديل (None للوحدات الجديدة)
        original_id = item.id if item else None

        # إذا كانت وحدة جديدة أنشئها بدون إضافتها للجلسة حتى تمر التحققات
        if not item:
            item = Unit(tenant_id=g.current_tenant.id)

        # استخراج البيانات من النموذج
        submitted_branch_id = int(request.form['branch_id'])
        submitted_floor_id = int(request.form['floor_id']) if request.form.get('floor_id') else None
        submitted_unit_type = request.form['unit_type']
        submitted_unit_number = (request.form.get('unit_number') or '').strip()

        item.branch_id = submitted_branch_id
        item.floor_id = submitted_floor_id
        item.unit_type = submitted_unit_type
        item.unit_number = submitted_unit_number

        # تحقق مبكّر: رقم الوحدة مكرر في نفس الفرع فقط
        dup = Unit.query.filter(
            Unit.tenant_id == g.current_tenant.id,
            Unit.branch_id == submitted_branch_id,
            Unit.unit_number == submitted_unit_number,
            Unit.id != (original_id or 0),
        ).first()
        if dup:
            # للوحدات الجديدة: لا نحتاج rollback لأنها لم تُضف للجلسة
            # للوحدات المعدّلة: نتراجع ليعود DB لحالته الأصلية
            if is_edit:
                db.session.rollback()
                # أعد بناء كائن عرض بالقيم المُرسلة (للحفاظ على ما أدخله المستخدم)
                item = Unit(id=original_id, tenant_id=g.current_tenant.id,
                            branch_id=submitted_branch_id, floor_id=submitted_floor_id,
                            unit_type=submitted_unit_type, unit_number=submitted_unit_number)
            branch_obj = Branch.query.filter_by(id=submitted_branch_id).first()
            branch_name = branch_obj.name if branch_obj else f'#{submitted_branch_id}'
            flash(
                f'رقم الوحدة «{submitted_unit_number}» مستخدم مسبقاً في فرع «{branch_name}». '
                f'استخدم رقماً مختلفاً، أو عدّل الوحدة الموجودة بدل إنشاء جديدة.',
                'error',
            )
            return render_template(
                'tenant/hotel/unit_form.html',
                unit=item, is_edit=is_edit,
                branches=branches_list, floors=floors_list,
                floors_by_branch_json=floors_by_branch_json,
                unit_types=_unit_types,
            )

        # اجتاز التحقق — أضف الوحدة الجديدة للجلسة الآن
        if not is_edit:
            db.session.add(item)
        item.description = request.form.get('description', '')

        # التفاصيل الداخلية (الجديدة)
        item.bedrooms_count = int(request.form.get('bedrooms_count') or 0)
        item.living_rooms = int(request.form.get('living_rooms') or 0)
        item.halls = int(request.form.get('halls') or 0)
        item.bathrooms_count = int(request.form.get('bathrooms_count') or 1)
        item.kitchens = int(request.form.get('kitchens') or 0)
        item.extra_rooms = request.form.get('extra_rooms', '')
        item.max_guests = int(request.form.get('max_guests') or 2)

        item.daily_price = float(request.form.get('daily_price') or 0)
        item.monthly_price = float(request.form.get('monthly_price') or 0)
        item.yearly_price = float(request.form.get('yearly_price') or 0)
        item.availability_type = request.form.get('availability_type', 'daily')
        item.status = request.form.get('status', 'available')
        item.is_available = (item.status == 'available')
        item.amenities = request.form.get('amenities', '')
        item.ical_import_url = request.form.get('ical_import_url', '')

        # صور + 360 (360 كما هو؛ الصور العادية = روابط من النص + ملفات مرفوعة)
        item.image_360_link = request.form.get('image_360_link', '')
        images_text = request.form.get('images_text', '').strip()
        image_urls = [u.strip() for u in images_text.split('\n') if u.strip()] if images_text else []
        from app.services.cloudinary_service import CloudinaryService
        use_cloud = CloudinaryService.is_configured()
        upload_root = Path(current_app.config['UPLOAD_FOLDER']) / 'hotel_units' / str(g.current_tenant.id)
        if not use_cloud:
            upload_root.mkdir(parents=True, exist_ok=True)
        allowed_ext = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
        for up in request.files.getlist('unit_images'):
            if not up or not up.filename:
                continue
            safe = secure_filename(up.filename)
            if not safe or '.' not in safe:
                continue
            ext = '.' + safe.rsplit('.', 1)[1].lower()
            if ext not in allowed_ext:
                continue

            if use_cloud:
                # رفع لـ Cloudinary (لا يضيع عند إعادة تشغيل السيرفر)
                up.stream.seek(0)
                res = CloudinaryService.upload_image(
                    file=up.stream,
                    folder=f'hotel_units/tenant_{g.current_tenant.id}',
                    tags=['hotel_unit'],
                )
                if res.get('success') and res.get('url'):
                    image_urls.append(res['url'])
                else:
                    current_app.logger.warning(f'[hotel] cloudinary upload failed: {res.get("error")}')
            else:
                stored_name = f'{uuid.uuid4().hex}{ext}'
                up.save(upload_root / stored_name)
                rel = f'uploads/hotel_units/{g.current_tenant.id}/{stored_name}'
                image_urls.append(url_for('static', filename=rel))
        item.images = image_urls

        # إنشاء طابق جديد إذا أدخل رقم
        new_floor = request.form.get('new_floor_number', '').strip()
        if new_floor and not item.floor_id:
            floor = Floor.query.filter_by(
                branch_id=item.branch_id, number=new_floor
            ).first()
            if not floor:
                floor = Floor(tenant_id=g.current_tenant.id, branch_id=item.branch_id, number=new_floor)
                db.session.add(floor)
                db.session.flush()
            item.floor_id = floor.id

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash('تعذّر الحفظ — قد يكون رقم الوحدة مكرراً في نفس الفرع.', 'error')
            return render_template(
                'tenant/hotel/unit_form.html',
                unit=item, is_edit=is_edit,
                branches=branches_list, floors=floors_list,
                floors_by_branch_json=floors_by_branch_json,
                unit_types=_unit_types,
            )
        flash('تم حفظ الوحدة', 'success')
        return redirect(url_for('tenant_hotel.units'))

    return render_template('tenant/hotel/unit_form.html',
        unit=item, is_edit=is_edit,
        branches=branches_list, floors=floors_list,
        floors_by_branch_json=floors_by_branch_json,
        unit_types=_unit_types)


@bp.route('/units/<int:id>/delete', methods=['POST'])
@_ensure_hotel
def unit_delete(id):
    item = Unit.query.filter_by(id=id, tenant_id=g.current_tenant.id).first_or_404()
    db.session.delete(item)
    db.session.commit()
    flash('تم حذف الوحدة', 'success')
    return redirect(url_for('tenant_hotel.units'))


# ==================== الخدمات ====================
@bp.route('/services')
@_ensure_hotel
def services():
    items = HotelService.query.filter_by(tenant_id=g.current_tenant.id).all()
    return render_template('tenant/hotel/services.html', services=items)


@bp.route('/services/new', methods=['GET', 'POST'])
@bp.route('/services/<int:id>/edit', methods=['GET', 'POST'])
@_ensure_hotel
def service_form(id=None):
    item = HotelService.query.filter_by(id=id, tenant_id=g.current_tenant.id).first() if id else None

    if request.method == 'POST':
        if not item:
            item = HotelService(tenant_id=g.current_tenant.id)
            db.session.add(item)
        item.name = request.form['name']
        item.description = request.form.get('description', '')
        item.icon = request.form.get('icon', '')
        item.is_free = 'is_free' in request.form
        item.price = float(request.form.get('price', 0))
        item.is_active = 'is_active' in request.form
        db.session.commit()
        flash('تم حفظ الخدمة', 'success')
        return redirect(url_for('tenant_hotel.services'))

    return render_template('tenant/hotel/service_form.html', service=item)


@bp.route('/services/<int:id>/delete', methods=['POST'])
@_ensure_hotel
def service_delete(id):
    item = HotelService.query.filter_by(id=id, tenant_id=g.current_tenant.id).first_or_404()
    db.session.delete(item)
    db.session.commit()
    flash('تم حذف الخدمة', 'success')
    return redirect(url_for('tenant_hotel.services'))

# ==================== لوحة الشقق التفاعلية (Dashboard) ====================
@bp.route('/units/dashboard')
@_ensure_hotel
def units_dashboard():
    tenant_id = g.current_tenant.id
    items = Unit.query.filter_by(tenant_id=tenant_id).all()
    branches = Branch.query.filter_by(tenant_id=tenant_id).all()
    
    # --- حساب الإحصائيات للنظرة السريعة ---
    from app.models.booking import Booking
    from sqlalchemy import func
    from datetime import datetime, timedelta

    # 1. إجمالي المبيعات (الحجوزات المؤكدة أو المكتملة)
    total_sales = db.session.query(func.sum(Booking.total_amount)).filter(
        Booking.tenant_id == tenant_id,
        Booking.status.in_(['confirmed', 'completed'])
    ).scalar() or 0

    # 2. الحجوزات الجديدة (بانتظار التأكيد)
    new_bookings_count = Booking.query.filter_by(
        tenant_id=tenant_id, status='new'
    ).count()

    # 3. حالة الوحدات
    total_units = len(items)
    available_units = sum(1 for u in items if u.status == 'available')
    booked_units = sum(1 for u in items if u.status == 'booked')
    maintenance_units = sum(1 for u in items if u.status == 'maintenance')
    
    occupancy_rate = (booked_units / total_units * 100) if total_units > 0 else 0

    # 4. معالجة النمط الشهري (العقود)
    hotel_mode = getattr(g.current_tenant, 'hotel_mode', 'daily')
    active_contracts_count = 0
    total_contract_sales = 0
    recent_contracts = []
    
    try:
        if hotel_mode == 'monthly':
            from app.models.contract import Contract
            active_contracts_count = Contract.query.filter_by(
                tenant_id=tenant_id, status='signed'
            ).count()
            total_contract_sales = db.session.query(func.sum(Contract.payment_amount)).filter_by(
                tenant_id=tenant_id, status='signed'
            ).scalar() or 0
            recent_contracts = Contract.query.filter_by(tenant_id=tenant_id).order_by(Contract.created_at.desc()).limit(5).all()
    except Exception:
        pass

    # 5. الطلبات الأخيرة (آخر 5 حجوزات)
    recent_bookings = Booking.query.filter_by(tenant_id=tenant_id).order_by(Booking.created_at.desc()).limit(5).all()

    stats = {
        'total_sales': float(total_sales + total_contract_sales),
        'new_bookings_count': new_bookings_count,
        'active_contracts_count': active_contracts_count,
        'total_units': total_units,
        'available_units': available_units,
        'booked_units': booked_units,
        'maintenance_units': maintenance_units,
        'occupancy_rate': round(occupancy_rate, 1),
        'hotel_mode': hotel_mode
    }

    status_options = Unit.STATUS_LABELS
    return render_template('tenant/hotel/units_dashboard.html', 
                           units=items, 
                           branches=branches, 
                           status_options=status_options,
                           stats=stats,
                           recent_bookings=recent_bookings,
                           recent_contracts=recent_contracts)

@bp.route('/units/<int:id>/status', methods=['POST'])
@_ensure_hotel
def update_unit_status(id):
    item = Unit.query.filter_by(id=id, tenant_id=g.current_tenant.id).first_or_404()
    
    new_status = request.form.get('status') or request.json.get('status')
    if new_status in Unit.STATUS_LABELS:
        item.status = new_status
        item.is_available = (new_status == 'available')
        db.session.commit()
        return jsonify({
            'success': True, 
            'new_status': new_status, 
            'status_label': item.status_label, 
            'color_class': item.status_color_class
        })
    
    
    return jsonify({'success': False, 'error': 'حالة غير صالحة'}), 400

@bp.route('/units/<int:id>/sync_ical', methods=['POST'])
@_ensure_hotel
def sync_unit_ical(id):
    item = Unit.query.filter_by(id=id, tenant_id=g.current_tenant.id).first_or_404()
    if not item.ical_import_url:
        flash('لا يوجد رابط استيراد لهذه الوحدة.', 'warning')
    else:
        success = ICalService.sync_unit_from_ical(item.id)
        if success:
            flash('تم مزامنة التقويم بنجاح وتم استيراد الحجوزات.', 'success')
        else:
            flash('فشلت عملية المزامنة. تأكد من صحة الرابط الخارجي.', 'error')
            
    return redirect(request.referrer or url_for('tenant_hotel.units_dashboard'))

"""
app/blueprints/tenant_bookings.py — إدارة الحجوزات (/app/bookings/*)
التاجر يشوف الحجوزات ويأكّدها أو يرفضها.
"""
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, jsonify

from app.extensions import db
from app.decorators import tenant_required
from app.models.booking import Booking
from app.models.branch import Branch

bp = Blueprint('tenant_bookings', __name__, template_folder='../../templates/tenant/bookings')


@bp.route('/')
@tenant_required
def list_bookings():
    """قائمة الحجوزات مع فلاتر."""
    status_filter = request.args.get('status', '')
    booking_type = request.args.get('type', '')

    q = Booking.query.filter_by(tenant_id=g.current_tenant.id)

    if status_filter:
        q = q.filter_by(status=status_filter)
    if booking_type:
        q = q.filter_by(booking_type=booking_type)

    bookings = q.order_by(Booking.created_at.desc()).all()

    # إحصائيات
    counts = {
        'new': Booking.query.filter_by(tenant_id=g.current_tenant.id, status='new').count(),
        'confirmed': Booking.query.filter_by(tenant_id=g.current_tenant.id, status='confirmed').count(),
        'cancelled': Booking.query.filter_by(tenant_id=g.current_tenant.id, status='cancelled').count(),
        'completed': Booking.query.filter_by(tenant_id=g.current_tenant.id, status='completed').count(),
        'total': Booking.query.filter_by(tenant_id=g.current_tenant.id).count(),
    }

    return render_template('tenant/bookings/list.html',
        bookings=bookings, counts=counts,
        status_filter=status_filter, booking_type=booking_type)


@bp.route('/<int:id>')
@tenant_required
def detail(id):
    """تفاصيل حجز."""
    booking = Booking.query.filter_by(id=id, tenant_id=g.current_tenant.id).first_or_404()
    branches = Branch.query.filter_by(tenant_id=g.current_tenant.id, is_active=True).all()
    return render_template('tenant/bookings/detail.html', booking=booking, branches=branches)


@bp.route('/<int:id>/confirm', methods=['POST'])
@tenant_required
def confirm(id):
    """تأكيد حجز."""
    booking = Booking.query.filter_by(id=id, tenant_id=g.current_tenant.id).first_or_404()
    booking.status = 'confirmed'
    booking.confirmed_by = g.current_user.full_name or g.current_user.username
    booking.confirmed_at = datetime.utcnow()
    booking.admin_notes = request.form.get('admin_notes', booking.admin_notes)

    # ربط بفرع إذا اختار
    branch_id = request.form.get('branch_id')
    if branch_id:
        booking.branch_id = int(branch_id)

    # -----------------
    # القيود المحاسبية
    # -----------------
    if booking.total_amount and booking.total_amount > 0:
        from app.services.accounting_service import create_journal_entry, seed_default_accounts
        from app.models.accounting import Account
        
        if Account.query.filter_by(tenant_id=g.current_tenant.id).count() == 0:
            seed_default_accounts(g.current_tenant.id)
            
        rev_acc = Account.query.filter_by(tenant_id=g.current_tenant.id, code='401').first()
        cash_acc = Account.query.filter_by(tenant_id=g.current_tenant.id, code='101').first()
        
        if rev_acc and cash_acc:
            lines = [
                {'account_id': cash_acc.id, 'debit': booking.total_amount, 'credit': 0},
                {'account_id': rev_acc.id, 'debit': 0, 'credit': booking.total_amount}
            ]
            success, msg = create_journal_entry(
                tenant_id=g.current_tenant.id,
                description=f"إيراد حجز #{booking.booking_number}",
                reference_id=booking.booking_number,
                reference_type="booking",
                lines=lines
            )
            if not success:
                db.session.rollback()
                flash(f'فشل إنشاء القيد المحاسبي: {msg}', 'danger')
                return redirect(url_for('tenant_bookings.detail', id=id))

    db.session.commit()
    flash('تم تأكيد الحجز ✅', 'success')

    # إرسال إشعار للعميل (إيميل)
    _notify_customer(booking, 'confirmed')

    return redirect(url_for('tenant_bookings.detail', id=id))


@bp.route('/<int:id>/cancel', methods=['POST'])
@tenant_required
def cancel(id):
    """إلغاء حجز."""
    booking = Booking.query.filter_by(id=id, tenant_id=g.current_tenant.id).first_or_404()
    booking.status = 'cancelled'
    booking.cancelled_at = datetime.utcnow()
    booking.admin_notes = request.form.get('admin_notes', booking.admin_notes)
    
    # عكس أي قيود محاسبية مسجلة لهذا الحجز إن وجدت
    from app.services.accounting_service import reverse_journal_entry
    reverse_journal_entry(
        tenant_id=g.current_tenant.id,
        original_reference_id=booking.booking_number,
        original_reference_type="booking",
        reason="تم إلغاء الحجز"
    )
    
    db.session.commit()
    flash('تم إلغاء الحجز', 'warning')

    _notify_customer(booking, 'cancelled')

    return redirect(url_for('tenant_bookings.detail', id=id))


@bp.route('/<int:id>/complete', methods=['POST'])
@tenant_required
def complete(id):
    """تم إنهاء الحجز (العميل حضر)."""
    booking = Booking.query.filter_by(id=id, tenant_id=g.current_tenant.id).first_or_404()
    booking.status = 'completed'
    db.session.commit()
    flash('تم إنهاء الحجز ✔️', 'success')
    return redirect(url_for('tenant_bookings.detail', id=id))


@bp.route('/<int:id>/no-show', methods=['POST'])
@tenant_required
def no_show(id):
    """العميل لم يحضر."""
    booking = Booking.query.filter_by(id=id, tenant_id=g.current_tenant.id).first_or_404()
    booking.status = 'no_show'
    db.session.commit()
    flash('تم تسجيل عدم الحضور', 'info')
    return redirect(url_for('tenant_bookings.detail', id=id))


@bp.route('/new', methods=['GET', 'POST'])
@tenant_required
def create_manual():
    """إنشاء حجز يدوي (من التاجر مباشرة)."""
    branches = Branch.query.filter_by(tenant_id=g.current_tenant.id, is_active=True).all()
    activity_code = g.current_tenant.activity.code if g.current_tenant.activity else ''

    if request.method == 'POST':
        booking = Booking(
            tenant_id=g.current_tenant.id,
            booking_number=Booking.generate_booking_number(),
            booking_type='hotel_room' if activity_code == 'hotel' else 'restaurant_table',
            customer_name=request.form.get('customer_name', ''),
            customer_phone=request.form.get('customer_phone', ''),
            customer_email=request.form.get('customer_email', ''),
            guests_count=int(request.form.get('guests_count') or 1),
            notes=request.form.get('notes', ''),
            source='manual',
            status='confirmed',
            confirmed_by=g.current_user.full_name or g.current_user.username,
            confirmed_at=datetime.utcnow(),
        )

        branch_id = request.form.get('branch_id')
        if branch_id:
            booking.branch_id = int(branch_id)

        # حسب النشاط
        if activity_code == 'hotel':
            checkin = request.form.get('checkin_date')
            checkout = request.form.get('checkout_date')
            if checkin:
                booking.checkin_date = datetime.strptime(checkin, '%Y-%m-%d').date()
            if checkout:
                booking.checkout_date = datetime.strptime(checkout, '%Y-%m-%d').date()
            booking.requested_unit_type = request.form.get('requested_unit_type', '')
            unit_id = request.form.get('unit_id')
            if unit_id:
                booking.unit_id = int(unit_id)
        else:
            res_date = request.form.get('reservation_date')
            if res_date:
                booking.reservation_date = datetime.strptime(res_date, '%Y-%m-%d').date()
            booking.reservation_time = request.form.get('reservation_time', '')

        total = request.form.get('total_amount')
        if total:
            booking.total_amount = float(total)

        db.session.add(booking)
        db.session.flush() # للحصول على رقم الحجز أو الآي دي إن لزم
        
        # -----------------
        # القيود المحاسبية
        # -----------------
        if booking.total_amount and booking.total_amount > 0:
            from app.services.accounting_service import create_journal_entry, seed_default_accounts
            from app.models.accounting import Account
            
            if Account.query.filter_by(tenant_id=g.current_tenant.id).count() == 0:
                seed_default_accounts(g.current_tenant.id)
                
            rev_acc = Account.query.filter_by(tenant_id=g.current_tenant.id, code='401').first()
            cash_acc = Account.query.filter_by(tenant_id=g.current_tenant.id, code='101').first()
            
            if rev_acc and cash_acc:
                lines = [
                    {'account_id': cash_acc.id, 'debit': booking.total_amount, 'credit': 0},
                    {'account_id': rev_acc.id, 'debit': 0, 'credit': booking.total_amount}
                ]
                success, msg = create_journal_entry(
                    tenant_id=g.current_tenant.id,
                    description=f"إيراد حجز يدوي #{booking.booking_number}",
                    reference_id=booking.booking_number,
                    reference_type="booking",
                    lines=lines
                )
                if not success:
                    db.session.rollback()
                    flash(f'فشل إنشاء القيد المحاسبي: {msg}', 'danger')
                    return render_template('tenant/bookings/create.html', branches=branches, activity_code=activity_code)

        db.session.commit()
        flash(f'تم إنشاء الحجز #{booking.booking_number} ✅', 'success')
        return redirect(url_for('tenant_bookings.list_bookings'))

    return render_template('tenant/bookings/create.html',
        branches=branches, activity_code=activity_code)


def _notify_customer(booking, action):
    """إشعار العميل بالإيميل و/أو واتساب عند تأكيد/إلغاء."""
    from flask import current_app

    try:
        from app.services.email_service import EmailService
        tenant = booking.tenant

        if booking.customer_email:
            if action == 'confirmed':
                subject = f"✅ تم تأكيد حجزك — {tenant.business_name}"
                body = f"""
                <div dir="rtl" style="font-family:Tahoma,Arial;padding:20px;">
                    <h2 style="color:#16a34a;">✅ تم تأكيد حجزك!</h2>
                    <p>مرحباً {booking.customer_name}،</p>
                    <p>تم تأكيد حجزك رقم <strong>#{booking.booking_number}</strong> في {tenant.business_name}.</p>
                    <div style="background:#f0fdf4;padding:16px;border-radius:8px;margin:16px 0;">
                        <p>👥 عدد الضيوف: {booking.guests_count}</p>
                        {'<p>📅 الدخول: ' + str(booking.checkin_date) + '</p><p>📅 الخروج: ' + str(booking.checkout_date) + '</p>' if booking.checkin_date else ''}
                        {'<p>📅 التاريخ: ' + str(booking.reservation_date) + '</p><p>⏰ الوقت: ' + booking.reservation_time + '</p>' if booking.reservation_date else ''}
                    </div>
                    <p>نتطلع لرؤيتك! 🎉</p>
                </div>
                """
            else:
                subject = f"❌ تم إلغاء حجزك — {tenant.business_name}"
                body = f"""
                <div dir="rtl" style="font-family:Tahoma,Arial;padding:20px;">
                    <h2 style="color:#dc2626;">❌ تم إلغاء الحجز</h2>
                    <p>مرحباً {booking.customer_name}،</p>
                    <p>نأسف لإبلاغك بإلغاء حجزك رقم #{booking.booking_number}.</p>
                    {'<p>ملاحظة: ' + booking.admin_notes + '</p>' if booking.admin_notes else ''}
                    <p>للاستفسار تواصل معنا.</p>
                </div>
                """

            EmailService._send(booking.customer_email, subject, body)
    except Exception as e:
        current_app.logger.warning(f'Booking email notification failed: {e}')

    phone = (booking.customer_phone or '').strip()
    if not phone:
        return

    try:
        from app.services.whatsapp_service import WhatsAppService
        cfg = WhatsAppService._get_config(booking.tenant_id)
        if not cfg or not cfg.is_active:
            return
        tenant = booking.tenant
        if action == 'confirmed':
            wa_text = (
                f'✅ تم تأكيد حجزك رقم #{booking.booking_number} في {tenant.business_name}.\n'
                f'👥 عدد الضيوف: {booking.guests_count}\n'
                f'نتطلع لرؤيتك!'
            )
        else:
            wa_text = (
                f'❌ تم إلغاء حجزك رقم #{booking.booking_number} في {tenant.business_name}.\n'
                f'للاستفسار تواصل معنا.'
            )
        WhatsAppService.send_text(booking.tenant_id, phone, wa_text)
    except Exception as e:
        current_app.logger.warning(f'Booking WhatsApp notification failed: {e}')

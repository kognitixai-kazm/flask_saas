"""
app/models/booking.py — نظام الحجوزات.
يخدم كل الأنشطة:
  - فندق: حجز غرفة/شقة (تاريخ دخول + خروج)
  - مطعم: حجز طاولة (تاريخ + وقت + عدد أشخاص)
"""
from datetime import datetime
from ..extensions import db


class Booking(db.Model):
    """حجز من زائر لنشاط معيّن."""
    __tablename__ = 'bookings'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True, index=True)

    # نوع الحجز: hotel_room | restaurant_table
    booking_type = db.Column(db.String(30), nullable=False, index=True)

    # رقم الحجز (تلقائي)
    booking_number = db.Column(db.String(20), unique=True, nullable=False)

    # بيانات العميل
    customer_name = db.Column(db.String(200), nullable=False)
    customer_phone = db.Column(db.String(30), default='')
    customer_email = db.Column(db.String(255), default='')

    # تفاصيل الحجز (تختلف حسب النوع)
    # فندق: تاريخ دخول وخروج
    checkin_date = db.Column(db.Date, nullable=True)
    checkout_date = db.Column(db.Date, nullable=True)

    # مطعم: تاريخ ووقت
    reservation_date = db.Column(db.Date, nullable=True)
    reservation_time = db.Column(db.String(10), default='')  # "19:00"

    # مشترك
    guests_count = db.Column(db.Integer, default=1)

    # ربط بالوحدة (فندق) — اختياري
    unit_id = db.Column(db.Integer, db.ForeignKey('hotel_units.id'), nullable=True)

    # نوع الوحدة المطلوبة (إذا ما حدد وحدة معيّنة)
    requested_unit_type = db.Column(db.String(50), default='')  # room, apartment, suite...

    # ملاحظات العميل
    notes = db.Column(db.Text, default='')

    # الحالة: new | confirmed | cancelled | completed | no_show
    status = db.Column(db.String(20), default='new', nullable=False, index=True)

    # رد التاجر
    admin_notes = db.Column(db.Text, default='')
    confirmed_by = db.Column(db.String(100), default='')

    # المبلغ (اختياري)
    total_amount = db.Column(db.Numeric(10, 2), default=0)
    currency = db.Column(db.String(10), default='SAR')

    # هل تم الدفع
    is_paid = db.Column(db.Boolean, default=False)
    payment_method = db.Column(db.String(30), default='')  # cash | card | online
    payment_reference = db.Column(db.String(100), default='')

    # مصدر الحجز: chat | whatsapp | manual | website
    source = db.Column(db.String(20), default='chat')

    # ربط بالمحادثة (إذا جاء من الشات)
    conversation_id = db.Column(db.Integer, db.ForeignKey('conversations.id'), nullable=True)
    visitor_id = db.Column(db.String(64), default='')

    # هل تم إبلاغ التاجر
    notification_sent = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    confirmed_at = db.Column(db.DateTime, nullable=True)
    cancelled_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # علاقات
    tenant = db.relationship('Tenant', backref=db.backref('bookings', lazy='dynamic', cascade='all, delete-orphan'))
    branch = db.relationship('Branch', backref=db.backref('bookings', lazy='dynamic'))
    unit = db.relationship('Unit', backref=db.backref('bookings', lazy='dynamic'))

    STATUS_LABELS = {
        'new': '🆕 جديد',
        'confirmed': '✅ مؤكد',
        'cancelled': '❌ ملغي',
        'completed': '✔️ مكتمل',
        'no_show': '⚠️ لم يحضر',
    }

    BOOKING_TYPE_LABELS = {
        'hotel_room': '🏨 حجز غرفة/وحدة',
        'restaurant_table': '🍽️ حجز طاولة',
    }

    @property
    def status_label(self):
        return self.STATUS_LABELS.get(self.status, self.status)

    @property
    def type_label(self):
        return self.BOOKING_TYPE_LABELS.get(self.booking_type, self.booking_type)

    @property
    def duration_nights(self):
        """عدد الليالي (للفنادق)."""
        if self.checkin_date and self.checkout_date:
            return (self.checkout_date - self.checkin_date).days
        return 0

    def __repr__(self):
        return f'<Booking #{self.booking_number} {self.status} tenant={self.tenant_id}>'

    @staticmethod
    def generate_booking_number():
        """توليد رقم حجز فريد."""
        import random
        import string
        prefix = 'BK'
        chars = string.digits
        while True:
            number = prefix + ''.join(random.choices(chars, k=8))
            if not Booking.query.filter_by(booking_number=number).first():
                return number

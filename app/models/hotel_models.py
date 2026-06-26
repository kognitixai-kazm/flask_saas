"""
app/models/hotel_models.py — جداول نشاط الفنادق.
كل جدول مرتبط بـ tenant_id → عزل كامل.
"""
from datetime import datetime
import uuid
from ..extensions import db


class Floor(db.Model):
    """طابق داخل فرع فندقي."""
    __tablename__ = 'hotel_floors'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False, index=True)

    number = db.Column(db.String(10), nullable=False)
    name = db.Column(db.String(100), default='')
    notes = db.Column(db.Text, default='')

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    branch = db.relationship('Branch', back_populates='floors')
    units = db.relationship('Unit', back_populates='floor', lazy='dynamic')

    __table_args__ = (
        db.UniqueConstraint('branch_id', 'number', name='uq_branch_floor'),
    )

    def __repr__(self):
        return f'<Floor {self.number} branch={self.branch_id}>'


class Unit(db.Model):
    """وحدة: شقة / غرفة / جناح / فيلا."""
    __tablename__ = 'hotel_units'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False, index=True)
    floor_id = db.Column(db.Integer, db.ForeignKey('hotel_floors.id'), nullable=True)

    # apartment | room | suite | villa
    unit_type = db.Column(db.String(30), nullable=False, index=True)
    unit_number = db.Column(db.String(20), nullable=False)
    title = db.Column(db.String(200), default='')
    description = db.Column(db.Text, default='')

    # التفاصيل الداخلية (كلها اختيارية)
    bedrooms_count = db.Column(db.Integer, default=0)      # غرف النوم
    living_rooms = db.Column(db.Integer, default=0)         # الصالة
    halls = db.Column(db.Integer, default=0)                # المجلس
    bathrooms_count = db.Column(db.Integer, default=1)      # الحمامات
    kitchens = db.Column(db.Integer, default=0)             # المطبخ
    extra_rooms = db.Column(db.String(200), default='')     # غرف إضافية (نص حر)
    area_sqm = db.Column(db.Float, nullable=True)
    max_guests = db.Column(db.Integer, default=2)

    # للتوافق مع الكود القديم
    @property
    def rooms_count(self):
        return self.bedrooms_count or 1

    # الأسعار
    daily_price = db.Column(db.Numeric(10, 2), default=0)
    monthly_price = db.Column(db.Numeric(10, 2), default=0)
    yearly_price = db.Column(db.Numeric(10, 2), default=0)

    # daily | monthly | yearly | all
    availability_type = db.Column(db.String(20), default='daily')
    is_available = db.Column(db.Boolean, default=True, index=True)
    
    # available | booked | maintenance | storage | office | closed
    status = db.Column(db.String(30), default='available', index=True)

    amenities = db.Column(db.Text, default='')

    # الصور + رابط 360
    image_360_link = db.Column(db.String(500), default='')   # رابط جولة 360
    images = db.Column(db.JSON, default=list)                 # قائمة روابط الصور

    # iCal Sync
    ical_import_url = db.Column(db.String(1000), default='')
    ical_export_token = db.Column(db.String(100), default=lambda: str(uuid.uuid4()), unique=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    branch = db.relationship('Branch', back_populates='units')
    floor = db.relationship('Floor', back_populates='units')

    UNIT_TYPE_LABELS = {
        'apartment': 'شقة', 'room': 'غرفة', 'suite': 'جناح', 'villa': 'فيلا'
    }

    STATUS_LABELS = {
        'available': 'متاحة',
        'reserved': 'محجوزة مبدئياً',
        'booked': 'مؤجرة / محجوزة',
        'maintenance': 'صيانة',
        'office': 'مكتب',
        'storage': 'مستودع',
        'closed': 'مغلقة'
    }

    STATUS_COLORS = {
        'available': 'bg-green-100 text-green-700 border-green-200',
        'reserved': 'bg-yellow-100 text-yellow-700 border-yellow-200',
        'booked': 'bg-red-100 text-red-700 border-red-200',
        'maintenance': 'bg-yellow-100 text-yellow-800 border-yellow-200',
        'office': 'bg-gray-800 text-gray-100 border-gray-900',
        'storage': 'bg-gray-800 text-gray-100 border-gray-900',
        'closed': 'bg-gray-800 text-gray-100 border-gray-900'
    }

    @property
    def type_label(self):
        return self.UNIT_TYPE_LABELS.get(self.unit_type, self.unit_type)

    @property
    def status_label(self):
        return self.STATUS_LABELS.get(self.status, self.status)

    @property
    def status_color_class(self):
        return self.STATUS_COLORS.get(self.status, 'bg-gray-100 text-gray-700 border-gray-200')

    __table_args__ = (
        db.UniqueConstraint('branch_id', 'unit_number', name='uq_branch_unit'),
    )


class HotelService(db.Model):
    """خدمة فندقية (واي فاي، مسبح، مواقف...)."""
    __tablename__ = 'hotel_services'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)

    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default='')
    icon = db.Column(db.String(10), default='')

    is_free = db.Column(db.Boolean, default=True)
    price = db.Column(db.Numeric(10, 2), default=0)

    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

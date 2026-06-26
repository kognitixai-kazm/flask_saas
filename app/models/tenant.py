"""
app/models/tenant.py — العميل (الشركة/المنشأة) = المستأجر
"""
from datetime import datetime
from ..extensions import db


class Tenant(db.Model):
    """المستأجر = صاحب النشاط التجاري."""
    __tablename__ = 'tenants'

    id = db.Column(db.Integer, primary_key=True)

    # Slug فريد غير قابل للتخمين (nanoid)
    slug = db.Column(db.String(32), unique=True, nullable=False, index=True)

    # بيانات النشاط
    business_name = db.Column(db.String(200), nullable=False)

    # بيانات المالك (نسخة تعريفية — الحساب الفعلي في tenant_users)
    owner_full_name = db.Column(db.String(200), nullable=False)
    owner_email = db.Column(db.String(255), nullable=False, index=True)
    owner_phone = db.Column(db.String(30))

    # العلاقات
    activity_id = db.Column(
        db.Integer, db.ForeignKey('activities.id'),
        nullable=False, index=True
    )
    plan_id = db.Column(
        db.Integer, db.ForeignKey('plans.id'),
        nullable=False, index=True
    )

    # الحالة
    # pending: تم التسجيل، لم يكمل setup بعد
    # active: فعّال
    # suspended: معلّق من الأدمن
    # cancelled: ألغى الاشتراك
    status = db.Column(db.String(20), default='pending', nullable=False, index=True)

    # هل أكمل خطوة setup (username/password)؟
    setup_completed = db.Column(db.Boolean, default=False, nullable=False)

    # اختياري: شعار + ألوان للشات (برندنج)
    logo_path = db.Column(db.String(500))
    primary_color = db.Column(db.String(7), default='#2563eb')

    # السماح للمدير العام بفتح سقف استهلاك الذكاء الاصطناعي للتاجر
    has_unlimited_ai = db.Column(db.Boolean, default=False, nullable=False)

    # ===== الحساب البنكي للتحويل (يظهر للعميل عند طلب التحويل) =====
    bank_name = db.Column(db.String(100), default='')          # الراجحي / الأهلي / إنماء ...
    bank_account_name = db.Column(db.String(200), default='')  # اسم صاحب الحساب (للتأكد)
    bank_account_number = db.Column(db.String(40), default='')
    bank_iban = db.Column(db.String(40), default='')           # SA....

    # إعدادات النشاط الخاصة (JSON مرن حسب كل نوع نشاط)
    activity_data = db.Column(db.JSON, default=dict)

    # إعدادات عامة (JSON)
    settings = db.Column(db.JSON, default=dict)

    # تواريخ
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow,
        onupdate=datetime.utcnow, nullable=False
    )

    # علاقات
    activity = db.relationship('Activity', back_populates='tenants')
    users = db.relationship('TenantUser', back_populates='tenant', cascade='all, delete-orphan', lazy='dynamic')
    subscription = db.relationship('Subscription', back_populates='tenant', uselist=False, cascade='all, delete-orphan')
    conversations = db.relationship('Conversation', back_populates='tenant', cascade='all, delete-orphan', lazy='dynamic')

    def __repr__(self):
        return f'<Tenant {self.slug} - {self.business_name}>'

    @property
    def owner(self):
        """المستخدم الذي دوره owner."""
        return self.users.filter_by(role='owner').first()

    @property
    def chat_url(self):
        from flask import current_app
        return f"{current_app.config['SITE_URL']}/c/{self.slug}"

    # ============================================================
    # الفنادق: نمط الحجز (شهري بحت / يومي يشمل الشهري)
    # تخزين في activity_data['hotel_mode'] = 'daily' | 'monthly'
    #   - daily   : حجز يومي + يدعم الشهري كخيار إضافي (الفنادق العادية)
    #   - monthly : إيجار شهري فقط (شقق سكنية بعقود رسمية)
    # القيم القديمة 'both' تُعامَل كـ 'daily' (تشمل النمطين).
    # ============================================================
    @property
    def hotel_mode(self) -> str:
        ad = self.activity_data or {}
        mode = (ad.get('hotel_mode') or 'daily').strip().lower()
        if mode == 'both':  # توافق رجعي مع البيانات السابقة
            mode = 'daily'
        if mode not in ('daily', 'monthly'):
            mode = 'daily'
        return mode

    @property
    def hotel_supports_daily(self) -> bool:
        """الإيجار اليومي مسموح فقط في نمط daily."""
        return self.hotel_mode == 'daily'

    @property
    def hotel_supports_monthly(self) -> bool:
        """الإيجار الشهري مسموح في كلا النمطين (يومي يشمل الشهري + monthly)."""
        return True

    @property
    def hotel_supports_contracts(self) -> bool:
        """العقود الإلكترونية الرسمية مرتبطة بالإيجار الشهري — متاحة في كلا النمطين."""
        return True

    def to_dict(self):
        return {
            'id': self.id,
            'slug': self.slug,
            'business_name': self.business_name,
            'owner_email': self.owner_email,
            'activity_id': self.activity_id,
            'plan_id': self.plan_id,
            'status': self.status,
            'setup_completed': self.setup_completed,
            'chat_url': self.chat_url,
            'created_at': self.created_at.isoformat(),
        }

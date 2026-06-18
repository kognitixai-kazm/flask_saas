"""
app/models/tenant_wallet.py — محفظة التاجر.

كل تاجر له رصيد بالريال.
- شحن الرصيد: TopUp (دفع من التاجر للمنصة)
- خصم تلقائي: عند كل رسالة/خدمة
- تنبيه عند انخفاض الرصيد
- إيقاف الخدمة عند نفاد الرصيد
"""
from datetime import datetime
from ..extensions import db


class TenantWallet(db.Model):
    """رصيد التاجر."""
    __tablename__ = 'tenant_wallets'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, unique=True, index=True)

    # الرصيد الحالي
    balance = db.Column(db.Numeric(10, 4), default=0.0)

    # إجمالي ما تم شحنه (لإحصائيات)
    total_topped_up = db.Column(db.Numeric(10, 4), default=0.0)

    # إجمالي ما تم استهلاكه
    total_spent = db.Column(db.Numeric(10, 4), default=0.0)

    # الحد الأدنى للتنبيه (افتراضي: 10 ر.س)
    low_balance_threshold = db.Column(db.Numeric(10, 4), default=10.0)

    # الحد الأدنى للإيقاف التلقائي (افتراضي: 0)
    auto_stop_threshold = db.Column(db.Numeric(10, 4), default=0.0)

    # تنبيه أُرسل أم لا
    low_balance_alerted = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = db.relationship('Tenant', backref=db.backref('wallet', uselist=False, cascade='all, delete-orphan'))

    @property
    def is_low(self):
        return float(self.balance) <= float(self.low_balance_threshold)

    @property
    def can_use_service(self):
        return float(self.balance) > float(self.auto_stop_threshold)

    def deduct(self, amount: float, reason: str = '') -> bool:
        """خصم مبلغ من الرصيد."""
        amt = float(amount)
        current = float(self.balance)

        if current < amt:
            return False  # رصيد غير كافٍ

        self.balance = current - amt
        self.total_spent = float(self.total_spent or 0) + amt
        self.updated_at = datetime.utcnow()

        # إعادة تفعيل التنبيه لو الرصيد قل
        if self.is_low and not self.low_balance_alerted:
            # هنا يمكن إرسال إيميل/رسالة
            self.low_balance_alerted = True
        return True

    def topup(self, amount: float, payment_ref: str = ''):
        """شحن الرصيد."""
        amt = float(amount)
        self.balance = float(self.balance or 0) + amt
        self.total_topped_up = float(self.total_topped_up or 0) + amt
        self.low_balance_alerted = False  # إعادة ضبط التنبيه
        self.updated_at = datetime.utcnow()

        # تسجيل العملية
        topup = WalletTopUp(
            tenant_id=self.tenant_id,
            amount=amt,
            payment_ref=payment_ref,
            balance_after=float(self.balance),
        )
        db.session.add(topup)

    @staticmethod
    def get_or_create(tenant_id: int):
        wallet = TenantWallet.query.filter_by(tenant_id=tenant_id).first()
        if not wallet:
            wallet = TenantWallet(tenant_id=tenant_id, balance=0.0)
            db.session.add(wallet)
            db.session.flush()
        return wallet


class WalletTopUp(db.Model):
    """سجل عمليات الشحن."""
    __tablename__ = 'wallet_topups'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)

    amount = db.Column(db.Numeric(10, 4), nullable=False)
    balance_after = db.Column(db.Numeric(10, 4), default=0.0)

    payment_ref = db.Column(db.String(200), default='')
    payment_method = db.Column(db.String(50), default='')  # moyasar | tap | manual
    status = db.Column(db.String(30), default='completed')  # pending | completed | failed | refunded

    notes = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    tenant = db.relationship('Tenant', backref=db.backref(
        'topups',
        lazy='dynamic',
        cascade='all, delete-orphan',
    ))

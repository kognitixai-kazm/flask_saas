"""
app/models/contract.py — العقود الموقّعة من العملاء.

كل عقد يمر بمراحل:
1. draft → جمع البيانات من العميل
2. pending_payment → بانتظار الدفع
3. paid → تم الدفع
4. signed → العقد جاهز/تم توليده
5. sent → أُرسل للعميل والتاجر
6. cancelled / expired
"""
from datetime import datetime
from ..extensions import db


class Contract(db.Model):
    """عقد بين عميل ومنشأة."""
    __tablename__ = 'contracts'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    template_id = db.Column(db.Integer, db.ForeignKey('contract_templates.id'), nullable=False)

    # ربط بمحادثة (لو من شات)
    conversation_id = db.Column(db.Integer, db.ForeignKey('conversations.id', ondelete='SET NULL'), nullable=True)

    # الوحدة (شقة/غرفة) المُتّفق عليها — اختياري
    unit_id = db.Column(db.Integer, nullable=True, index=True)

    # ========== رقم العقد ==========
    contract_number = db.Column(db.String(50), unique=True, index=True)

    # ========== بيانات العميل ==========
    customer_name = db.Column(db.String(200), default='')
    customer_phone = db.Column(db.String(30), default='')
    customer_email = db.Column(db.String(255), default='')
    customer_id_number = db.Column(db.String(50), default='')

    # كل البيانات اللي جمعها البوت (JSON)
    # {"full_name": "...", "id_number": "...", "id_image_front": "https://...", ...}
    field_values = db.Column(db.JSON, default=dict)

    # ========== الحالة ==========
    # draft | pending_payment | paid | signed | sent | cancelled | expired
    status = db.Column(db.String(30), default='draft', index=True)

    # ========== الدفع ==========
    payment_amount = db.Column(db.Numeric(10, 2), default=0)
    payment_paid = db.Column(db.Numeric(10, 2), default=0)
    payment_status = db.Column(db.String(30), default='pending')  # pending | paid | partial | refunded
    payment_reference = db.Column(db.String(200), default='')
    # online | bank_transfer
    payment_method = db.Column(db.String(50), default='')

    # ====== تحويل بنكي (موافقة يدوية من التاجر) ======
    bank_transfer_proof_url = db.Column(db.String(500), default='')
    bank_transfer_approved_by = db.Column(db.Integer, nullable=True)
    bank_transfer_approved_at = db.Column(db.DateTime, nullable=True)
    bank_transfer_rejected_at = db.Column(db.DateTime, nullable=True)
    bank_transfer_note = db.Column(db.Text, default='')

    # ========== المستندات ==========
    # رابط PDF العقد النهائي (في Cloudinary)
    contract_pdf_url = db.Column(db.String(500), default='')

    # رابط API الخارجي (لو استخدم نظام التاجر)
    external_contract_id = db.Column(db.String(200), default='')
    external_contract_url = db.Column(db.String(500), default='')

    # ========== التواريخ ==========
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    paid_at = db.Column(db.DateTime, nullable=True)
    signed_at = db.Column(db.DateTime, nullable=True)
    sent_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)

    # ============ علاقات ============
    tenant = db.relationship('Tenant', backref=db.backref(
        'contracts', lazy='dynamic', cascade='all, delete-orphan'))
    template = db.relationship('ContractTemplate', backref=db.backref('contracts', lazy='dynamic'))

    STATUS_LABELS = {
        'draft': '📝 مسودة',
        'pending_payment': '⏳ بانتظار الدفع',
        'awaiting_approval': '🔍 بانتظار التحقق من التحويل',
        'paid': '💰 مدفوع',
        'signed': '✍️ موقّع',
        'sent': '✅ مُرسل',
        'cancelled': '❌ ملغي',
        'expired': '⏰ منتهي',
        'rejected': '🚫 رُفض التحويل',
    }

    @property
    def status_label(self):
        return self.STATUS_LABELS.get(self.status, self.status)

    def generate_contract_number(self):
        """توليد رقم عقد فريد."""
        if self.contract_number:
            return self.contract_number
        from datetime import datetime as dt
        now = dt.utcnow()
        suffix = f'{self.tenant_id}-{now.strftime("%Y%m%d")}-{self.id or 0:04d}'
        self.contract_number = f'CON-{suffix}'
        return self.contract_number

    def __repr__(self):
        return f'<Contract {self.contract_number or self.id} status={self.status}>'

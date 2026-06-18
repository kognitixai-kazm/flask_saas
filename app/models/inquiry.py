"""
app/models/inquiry.py — استفسارات الزوار.
يُنشأ عندما الشات لا يجد إجابة → يُرسل إيميل لصاحب النشاط → يرد من لوحة التحكم.
"""
from datetime import datetime
from ..extensions import db


class Inquiry(db.Model):
    """استفسار من زائر لم يجد إجابة في الشات."""
    __tablename__ = 'inquiries'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True, index=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('conversations.id'), nullable=True)

    # بيانات الزائر
    visitor_id = db.Column(db.String(64), default='')
    visitor_name = db.Column(db.String(200), default='')
    visitor_phone = db.Column(db.String(30), default='')
    visitor_email = db.Column(db.String(255), default='')

    # السؤال
    question = db.Column(db.Text, nullable=False)

    # general | complaint (لتصفية الشكاوى في لوحة التحكم)
    inquiry_kind = db.Column(db.String(20), nullable=False, default='general', index=True)
    # staff | housekeeping | noise | pricing | booking | food | service | other
    complaint_category = db.Column(db.String(40), nullable=False, default='', index=True)

    # الرد من صاحب النشاط
    answer = db.Column(db.Text, default='')
    answered_by = db.Column(db.String(100), default='')

    # الحالة: new | pending | answered | closed
    status = db.Column(db.String(20), default='new', nullable=False, index=True)

    # هل تم إرسال إيميل لصاحب النشاط
    email_sent = db.Column(db.Boolean, default=False)
    email_sent_to = db.Column(db.String(255), default='')

    # هل تم إبلاغ الزائر بالرد
    visitor_notified = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    answered_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # علاقات
    tenant = db.relationship('Tenant', backref=db.backref('inquiries', lazy='dynamic'))
    branch = db.relationship('Branch', back_populates='inquiries')

    STATUS_LABELS = {
        'new': 'جديد', 'pending': 'بانتظار الرد',
        'answered': 'تم الرد', 'closed': 'مغلق'
    }

    COMPLAINT_CATEGORY_LABELS_AR = {
        'staff': 'موظفين / خدمة غرف',
        'housekeeping': 'نظافة',
        'noise': 'ضجيج أو إزعاج',
        'pricing': 'أسعار أو فوترة',
        'booking': 'حجز أو مواعيد',
        'food': 'طعام أو جودة',
        'service': 'خدمة أو معاملة',
        'other': 'أخرى',
    }

    @property
    def status_label(self):
        return self.STATUS_LABELS.get(self.status, self.status)

    @property
    def complaint_category_label_ar(self):
        if (self.inquiry_kind or '') != 'complaint':
            return ''
        c = (self.complaint_category or '').strip() or 'other'
        return self.COMPLAINT_CATEGORY_LABELS_AR.get(c, c)

    def __repr__(self):
        return f'<Inquiry {self.id} tenant={self.tenant_id} status={self.status}>'

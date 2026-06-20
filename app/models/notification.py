"""
app/models/notification.py — نظام الإشعارات (Notification)
يدعم إشعارات التاجر والسوبر أدمن مع حالة القراءة.
"""
from datetime import datetime
from ..extensions import db


class Notification(db.Model):
    """إشعار واحد لمستخدم (تاجر أو سوبر أدمن)."""
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)

    # نوع المستلم: 'tenant' أو 'admin'
    recipient_type = db.Column(db.String(20), nullable=False, index=True)

    # معرّف المستلم (tenant_id أو super_admin_id)
    recipient_id = db.Column(db.Integer, nullable=False, index=True)

    # نوع الإشعار: booking, inquiry, complaint, new_tenant, contract, system
    category = db.Column(db.String(30), nullable=False, default='system', index=True)

    # العنوان والمحتوى
    title = db.Column(db.String(300), nullable=False)
    body = db.Column(db.Text, default='')

    # رابط مباشر (اختياري — ينقل المستخدم للصفحة المعنية)
    action_url = db.Column(db.String(500), default='')

    # أيقونة (إيموجي)
    icon = db.Column(db.String(10), default='🔔')

    # حالة القراءة
    is_read = db.Column(db.Boolean, default=False, nullable=False, index=True)

    # تواريخ
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    read_at = db.Column(db.DateTime, nullable=True)

    def mark_read(self):
        self.is_read = True
        self.read_at = datetime.utcnow()

    def to_dict(self):
        return {
            'id': self.id,
            'category': self.category,
            'title': self.title,
            'body': self.body,
            'action_url': self.action_url,
            'icon': self.icon,
            'is_read': self.is_read,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'time_ago': self._time_ago(),
        }

    def _time_ago(self):
        """نص زمني بسيط (منذ X دقائق/ساعات)."""
        if not self.created_at:
            return ''
        diff = datetime.utcnow() - self.created_at
        minutes = int(diff.total_seconds() / 60)
        if minutes < 1:
            return 'الآن'
        if minutes < 60:
            return f'منذ {minutes} دقيقة'
        hours = minutes // 60
        if hours < 24:
            return f'منذ {hours} ساعة'
        days = hours // 24
        return f'منذ {days} يوم'

    def __repr__(self):
        return f'<Notification {self.id} {self.category} to={self.recipient_type}:{self.recipient_id}>'

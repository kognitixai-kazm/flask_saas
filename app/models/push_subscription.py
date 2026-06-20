"""
app/models/push_subscription.py — اشتراكات Web Push Notifications
يخزّن بيانات اشتراك المتصفح لإرسال الإشعارات في الخلفية.
"""
from datetime import datetime
from ..extensions import db


class PushSubscription(db.Model):
    """اشتراك جهاز واحد في Web Push Notifications."""
    __tablename__ = 'push_subscriptions'

    id = db.Column(db.Integer, primary_key=True)

    # نوع المستخدم: 'tenant' أو 'admin'
    user_type = db.Column(db.String(20), nullable=False, index=True)

    # معرّف المستخدم (tenant_id أو super_admin_id)
    user_id = db.Column(db.Integer, nullable=False, index=True)

    # بيانات الاشتراك من المتصفح (JSON)
    endpoint = db.Column(db.Text, nullable=False)
    p256dh_key = db.Column(db.Text, nullable=False)
    auth_key = db.Column(db.Text, nullable=False)

    # معلومات الجهاز (اختياري)
    user_agent = db.Column(db.String(500), default='')

    # هل الاشتراك نشط
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_subscription_info(self):
        """إرجاع البيانات بالتنسيق المطلوب لمكتبة pywebpush."""
        return {
            'endpoint': self.endpoint,
            'keys': {
                'p256dh': self.p256dh_key,
                'auth': self.auth_key,
            }
        }

    def __repr__(self):
        return f'<PushSubscription {self.id} {self.user_type}:{self.user_id}>'

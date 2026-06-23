"""
app/models/subscription.py — اشتراك المستأجر في باقة
"""
from datetime import datetime, timedelta
from ..extensions import db


class Subscription(db.Model):
    """اشتراك tenant في plan."""
    __tablename__ = 'subscriptions'

    id = db.Column(db.Integer, primary_key=True)

    tenant_id = db.Column(
        db.Integer, db.ForeignKey('tenants.id'),
        nullable=False, unique=True, index=True
    )
    plan_id = db.Column(
        db.Integer, db.ForeignKey('plans.id'),
        nullable=False, index=True
    )

    # trial, active, past_due, cancelled
    status = db.Column(db.String(20), default='trial', nullable=False, index=True)

    started_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    ends_at = db.Column(db.DateTime)
    trial_ends_at = db.Column(db.DateTime)

    auto_renew = db.Column(db.Boolean, default=True, nullable=False)

    # عدّاد استخدام الشهر الحالي
    chats_used_this_month = db.Column(db.Integer, default=0, nullable=False)
    # طلبات الرد عبر الذكاء الاصطناعي (احتياطي الشات) — تُعاد شهرياً مع usage_reset_date
    ai_calls_this_month = db.Column(db.Integer, default=0, nullable=False)
    usage_reset_date = db.Column(db.Date, default=lambda: datetime.utcnow().date())

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow,
        onupdate=datetime.utcnow, nullable=False
    )

    # علاقات
    tenant = db.relationship('Tenant', back_populates='subscription')
    plan = db.relationship('Plan', back_populates='subscriptions')

    def __repr__(self):
        return f'<Subscription tenant={self.tenant_id} plan={self.plan_id} status={self.status}>'

    @property
    def is_active(self):
        """هل الاشتراك فعّال حالياً."""
        self.check_limits_and_update_status()
        if self.status not in ('active', 'trial'):
            return False
        if self.ends_at and self.ends_at < datetime.utcnow():
            return False
        return True

    def check_limits_and_update_status(self):
        """تحديث الحالة إذا انتهى الاشتراك أو تجاوز الحد التجريبي."""
        changed = False
        if self.status in ('trial', 'active'):
            if self.ends_at and self.ends_at < datetime.utcnow():
                self.status = 'past_due'
                changed = True
        
        if self.status == 'trial':
            total_usage = (self.chats_used_this_month or 0) + (self.ai_calls_this_month or 0)
            if total_usage >= 500:
                self.status = 'past_due'
                changed = True
        
        if changed:
            db.session.add(self)
            # Not committing here to avoid breaking transactions, caller should commit or flush


    @property
    def days_remaining(self):
        if not self.ends_at:
            return None
        delta = self.ends_at - datetime.utcnow()
        return max(0, delta.days)

    def can_send_chat(self):
        """هل يستطيع إرسال رسالة شات جديدة."""
        if not self.is_active:
            return False
        
        # مفتوح مؤقتاً للاختبارات والإصلاحات بناءً على طلبك
        return True
        
        # if self.plan is None:
        #     return False
        # # Use limits relation if available
        # limit = self.plan.limits.max_whatsapp_msgs if self.plan.limits else 0
        # return self.chats_used_this_month < limit

    def increment_chat_usage(self, count=1):
        """زيادة العدّاد + إعادة تعيين شهرية."""
        today = datetime.utcnow().date()
        if today.month != self.usage_reset_date.month or today.year != self.usage_reset_date.year:
            self.chats_used_this_month = 0
            self.ai_calls_this_month = 0
            self.usage_reset_date = today
        self.chats_used_this_month += count

    def increment_ai_calls(self, count=1):
        """زيادة عدّاد طلبات الـ AI مع إعادة تعيين شهرية."""
        today = datetime.utcnow().date()
        if today.month != self.usage_reset_date.month or today.year != self.usage_reset_date.year:
            self.chats_used_this_month = 0
            self.ai_calls_this_month = 0
            self.usage_reset_date = today
        self.ai_calls_this_month = int(self.ai_calls_this_month or 0) + count

    def to_dict(self):
        return {
            'id': self.id,
            'tenant_id': self.tenant_id,
            'plan_id': self.plan_id,
            'status': self.status,
            'is_active': self.is_active,
            'days_remaining': self.days_remaining,
            'chats_used_this_month': self.chats_used_this_month,
            'ai_calls_this_month': self.ai_calls_this_month,
            'max_chats_per_month': self.plan.limits.max_whatsapp_msgs if self.plan and self.plan.limits else 0,
            'started_at': self.started_at.isoformat(),
            'ends_at': self.ends_at.isoformat() if self.ends_at else None,
        }

"""
app/models/plan.py — باقات الاشتراك والنماذج المرتبطة بها
"""
from datetime import datetime
from ..extensions import db

class Plan(db.Model):
    """باقة اشتراك (Basic, Pro, Enterprise...)."""
    __tablename__ = 'plans'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False, index=True)

    name_ar = db.Column(db.String(100), nullable=False)
    name_en = db.Column(db.String(100), nullable=False)
    description_ar = db.Column(db.Text, default='')
    description_en = db.Column(db.Text, default='')

    # عرض وحالة
    status = db.Column(db.String(20), default='draft', nullable=False) # active, inactive, draft, archived
    is_popular = db.Column(db.Boolean, default=False, nullable=False)
    badge_color = db.Column(db.String(20), default='')
    badge_text = db.Column(db.String(50), default='')
    sort_order = db.Column(db.Integer, default=0)

    # تجربة مجانية
    trial_days = db.Column(db.Integer, default=14)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow,
        onupdate=datetime.utcnow, nullable=False
    )

    # علاقات
    subscriptions = db.relationship('Subscription', back_populates='plan', lazy='dynamic')
    pricing = db.relationship('PlanPricing', back_populates='plan', uselist=False, cascade="all, delete-orphan")
    limits = db.relationship('PlanLimit', back_populates='plan', uselist=False, cascade="all, delete-orphan")
    modules = db.relationship('PlanModule', back_populates='plan', cascade="all, delete-orphan")
    agents = db.relationship('PlanAgent', back_populates='plan', cascade="all, delete-orphan")
    integrations = db.relationship('PlanIntegration', back_populates='plan', cascade="all, delete-orphan")
    permissions = db.relationship('PlanPermission', back_populates='plan', cascade="all, delete-orphan")

    # Helper properties for backwards compatibility during migration
    @property
    def price_monthly(self):
        return self.pricing.price_monthly if self.pricing else 0

    @property
    def price_yearly(self):
        return self.pricing.price_yearly if self.pricing else 0

    @property
    def currency(self):
        return self.pricing.currency if self.pricing else 'SAR'

    @property
    def is_active(self):
        return self.status == 'active'

    @property
    def description(self):
        return self.description_ar # default fallback

    @property
    def max_chats_per_month(self):
        # Fallback to chat agent monthly usage limit
        chat_agent = next((a for a in self.agents if a.agent_type == 'chat'), None)
        return chat_agent.monthly_usage_limit if chat_agent else 0

    @property
    def max_users(self):
        return self.limits.max_users if self.limits else 1

    @property
    def max_branches(self):
        return self.limits.max_branches if self.limits else 1

    def has_feature(self, feature_key: str) -> bool:
        """هل الميزة مفعّلة في هذه الباقة؟ (Backwards compatibility)"""
        # Check permissions first
        for p in self.permissions:
            if p.feature_key == feature_key and p.visibility == 'visible':
                return True
        # Check modules
        for m in self.modules:
            if m.module_name == feature_key and m.is_enabled:
                return True
        # Check integrations
        for i in self.integrations:
            if i.integration_name == feature_key and i.is_enabled:
                return True
        return False

    def __repr__(self):
        return f'<Plan {self.code}>'

class PlanPricing(db.Model):
    __tablename__ = 'plan_pricing'
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plans.id'), nullable=False, unique=True)
    
    price_monthly = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    price_yearly = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    currency = db.Column(db.String(10), default='SAR', nullable=False)
    stripe_price_id_monthly = db.Column(db.String(100), nullable=True)
    stripe_price_id_yearly = db.Column(db.String(100), nullable=True)

    plan = db.relationship('Plan', back_populates='pricing')

class PlanLimit(db.Model):
    __tablename__ = 'plan_limits'
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plans.id'), nullable=False, unique=True)

    max_branches = db.Column(db.Integer, default=1, nullable=False)
    max_users = db.Column(db.Integer, default=1, nullable=False)
    max_employees = db.Column(db.Integer, default=1, nullable=False)
    max_clients = db.Column(db.Integer, default=0, nullable=False)
    
    max_whatsapp_msgs = db.Column(db.Integer, default=0, nullable=False)
    max_sms = db.Column(db.Integer, default=0, nullable=False)
    max_emails = db.Column(db.Integer, default=0, nullable=False)
    max_push_notifications = db.Column(db.Integer, default=0, nullable=False)
    
    max_contracts_per_month = db.Column(db.Integer, default=0, nullable=False)
    storage_limit_gb = db.Column(db.Integer, default=1, nullable=False)

    plan = db.relationship('Plan', back_populates='limits')

class PlanModule(db.Model):
    __tablename__ = 'plan_modules'
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plans.id'), nullable=False)
    module_name = db.Column(db.String(50), nullable=False)
    is_enabled = db.Column(db.Boolean, default=False, nullable=False)

    plan = db.relationship('Plan', back_populates='modules')

class PlanAgent(db.Model):
    __tablename__ = 'plan_agents'
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plans.id'), nullable=False)
    agent_type = db.Column(db.String(50), nullable=False)
    is_enabled = db.Column(db.Boolean, default=False, nullable=False)
    
    monthly_usage_limit = db.Column(db.Integer, default=0, nullable=False)
    max_conversations = db.Column(db.Integer, default=0, nullable=False)
    max_voice_calls = db.Column(db.Integer, default=0, nullable=False)

    plan = db.relationship('Plan', back_populates='agents')

class PlanIntegration(db.Model):
    __tablename__ = 'plan_integrations'
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plans.id'), nullable=False)
    integration_name = db.Column(db.String(50), nullable=False)
    is_enabled = db.Column(db.Boolean, default=False, nullable=False)

    plan = db.relationship('Plan', back_populates='integrations')

class PlanPermission(db.Model):
    __tablename__ = 'plan_permissions'
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plans.id'), nullable=False)
    feature_key = db.Column(db.String(100), nullable=False)
    visibility = db.Column(db.String(20), default='visible', nullable=False) # visible, hidden, coming_soon

    plan = db.relationship('Plan', back_populates='permissions')

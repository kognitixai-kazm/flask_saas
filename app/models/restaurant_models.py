"""
app/models/restaurant_models.py — جداول نشاط المطاعم والكافيهات.
"""
from datetime import datetime
from ..extensions import db


class MenuCategory(db.Model):
    """تصنيف قائمة الطعام (مشروبات ساخنة، وجبات رئيسية...)."""
    __tablename__ = 'restaurant_categories'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)

    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, default='')
    icon = db.Column(db.String(10), default='')
    sort_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    items = db.relationship('MenuItem', back_populates='category', cascade='all, delete-orphan', lazy='dynamic')

    def __repr__(self):
        return f'<MenuCategory {self.name} tenant={self.tenant_id}>'


class MenuItem(db.Model):
    """صنف في المنيو."""
    __tablename__ = 'restaurant_items'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey('restaurant_categories.id'), nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True, index=True)

    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default='')
    price = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    discount_price = db.Column(db.Numeric(10, 2), nullable=True)

    ingredients = db.Column(db.Text, default='')
    calories = db.Column(db.Integer, nullable=True)
    prep_time_min = db.Column(db.Integer, nullable=True)

    is_spicy = db.Column(db.Boolean, default=False)
    is_vegetarian = db.Column(db.Boolean, default=False)
    is_popular = db.Column(db.Boolean, default=False)
    is_available = db.Column(db.Boolean, default=True, index=True)

    # روابط صور الصنف (تُرفَع لـ Cloudinary أو محلياً كـ fallback)
    images = db.Column(db.JSON, default=list)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    category = db.relationship('MenuCategory', back_populates='items')
    branch = db.relationship('Branch', back_populates='menu_items')

    @property
    def final_price(self):
        return self.discount_price if self.discount_price else self.price


class RestaurantService(db.Model):
    """خدمة مطعم (توصيل، حجز، طلب مسبق...)."""
    __tablename__ = 'restaurant_services'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)

    # delivery | reservation | pre_order | dine_in | takeaway
    service_type = db.Column(db.String(30), nullable=False)
    description = db.Column(db.Text, default='')

    delivery_fee = db.Column(db.Numeric(8, 2), default=0)
    min_order = db.Column(db.Numeric(8, 2), default=0)
    delivery_areas = db.Column(db.Text, default='')

    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    SERVICE_LABELS = {
        'delivery': 'توصيل', 'reservation': 'حجز طاولة',
        'pre_order': 'طلب مسبق', 'dine_in': 'أكل في المطعم', 'takeaway': 'سفري'
    }

    @property
    def type_label(self):
        return self.SERVICE_LABELS.get(self.service_type, self.service_type)

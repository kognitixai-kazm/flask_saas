"""
app/models/activity.py — أنواع الأنشطة التجارية
يُسجّل تلقائياً من مجلدات activities/* (مع manifest.json)
"""
from datetime import datetime
from ..extensions import db


class Activity(db.Model):
    """نوع نشاط تجاري (فندق، مطعم، عيادة...)."""
    __tablename__ = 'activities'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False, index=True)  # hotel, restaurant...

    name_ar = db.Column(db.String(100), nullable=False)
    name_en = db.Column(db.String(100), nullable=False)
    icon = db.Column(db.String(10), default='🏢')
    description = db.Column(db.Text, default='')

    # مسار مجلد النشاط (app/activities/<code>)
    template_path = db.Column(db.String(255), default='')

    # intents supported (JSON list)
    intents = db.Column(db.JSON, default=list)

    # الحقول المطلوبة للإعداد (JSON list of field definitions)
    required_fields = db.Column(db.JSON, default=list)

    is_active = db.Column(db.Boolean, default=True, nullable=False)
    sort_order = db.Column(db.Integer, default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow,
        onupdate=datetime.utcnow, nullable=False
    )

    # علاقات
    tenants = db.relationship('Tenant', back_populates='activity', lazy='dynamic')

    def __repr__(self):
        return f'<Activity {self.code}>'

    def to_dict(self):
        return {
            'id': self.id,
            'code': self.code,
            'name_ar': self.name_ar,
            'name_en': self.name_en,
            'icon': self.icon,
            'description': self.description,
            'is_active': self.is_active,
        }

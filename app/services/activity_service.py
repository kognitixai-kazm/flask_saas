"""
app/services/activity_service.py — إدارة أنواع الأنشطة + تسجيل يدوي.
مبسّط الآن: نسجّل hotel + restaurant يدوياً.
لاحقاً: auto-scan من مجلدات activities/ مع manifest.json.
"""
import json
from pathlib import Path
from flask import current_app

from app.extensions import db
from app.models.activity import Activity


class ActivityService:

    @staticmethod
    def seed_defaults():
        """تسجيل الأنشطة الأولية (فندق + مطعم)."""
        defaults = [
            {
                'code': 'hotel',
                'name_ar': 'فندق',
                'name_en': 'Hotel',
                'icon': '🏨',
                'description': 'إدارة الحجوزات والاستفسارات الفندقية',
                'template_path': 'activities/hotel',
                'intents': ['booking', 'availability', 'pricing', 'amenities', 'complaints'],
                'required_fields': [
                    {'key': 'rooms_count', 'label_ar': 'عدد الغرف', 'type': 'number', 'required': True},
                    {'key': 'floors_count', 'label_ar': 'عدد الطوابق', 'type': 'number', 'required': False},
                    {'key': 'checkin_time', 'label_ar': 'وقت الدخول', 'type': 'time', 'required': False},
                    {'key': 'checkout_time', 'label_ar': 'وقت الخروج', 'type': 'time', 'required': False},
                    {'key': 'amenities', 'label_ar': 'المرافق', 'type': 'multiselect', 'required': False},
                ],
                'sort_order': 1,
            },
            {
                'code': 'restaurant',
                'name_ar': 'مطعم / كافيه',
                'name_en': 'Restaurant / Cafe',
                'icon': '🍽️',
                'description': 'إدارة المنيو والطلبات والحجوزات',
                'template_path': 'activities/restaurant',
                'intents': ['menu', 'ordering', 'reservation', 'delivery', 'complaints'],
                'required_fields': [
                    {'key': 'cuisine_type', 'label_ar': 'نوع المطبخ', 'type': 'text', 'required': False},
                    {'key': 'seating_capacity', 'label_ar': 'سعة الجلوس', 'type': 'number', 'required': False},
                    {'key': 'delivery_available', 'label_ar': 'يوجد توصيل', 'type': 'boolean', 'required': False},
                ],
                'sort_order': 2,
            },
        ]

        for data in defaults:
            if not Activity.query.filter_by(code=data['code']).first():
                activity = Activity(**data)
                db.session.add(activity)

        db.session.commit()

    @staticmethod
    def get_active_activities():
        """الأنشطة المتاحة للتسجيل."""
        return Activity.query.filter_by(is_active=True).order_by(Activity.sort_order).all()

    @staticmethod
    def get_activity_by_code(code: str) -> Activity | None:
        return Activity.query.filter_by(code=code).first()

    @staticmethod
    def load_handler(activity_code: str):
        """
        تحميل handler النشاط.
        حالياً: import يدوي. لاحقاً: dynamic import من manifest.json.
        """
        handlers = {}

        try:
            from app.activities.hotel.handler import HotelHandler
            handlers['hotel'] = HotelHandler()
        except ImportError:
            pass

        try:
            from app.activities.restaurant.handler import RestaurantHandler
            handlers['restaurant'] = RestaurantHandler()
        except ImportError:
            pass

        return handlers.get(activity_code)

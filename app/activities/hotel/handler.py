"""
app/activities/hotel/handler.py — منطق نشاط الفندق.
يوفّر:
  - get_system_prompt(): تعليمات AI المخصصة
  - get_dashboard_data(): بيانات للوحة التحكم
  - validate_settings(): تحقق من البيانات
"""


class HotelHandler:
    """معالج نشاط الفنادق."""

    def get_system_prompt(self, tenant) -> str:
        """بناء تعليمات AI خاصة بالفنادق."""
        data = tenant.activity_data or {}

        prompt_parts = [
            "أنت موظف استقبال محترف في فندق. مهامك:",
            "- الإجابة عن استفسارات الغرف والأجنحة والشقق",
            "- ذكر الأسعار والتوفر عند السؤال",
            "- تقديم معلومات عن الخدمات المتاحة (مسبح، واي فاي، مواقف...)",
            "- مساعدة العميل في التواصل مع الفرع المناسب",
            "- استقبال الشكاوى والاقتراحات بلباقة",
            "- **مهم جداً:** تحدث مع العميل بنفس اللغة التي يبدأ بها المحادثة (مثلاً إذا تحدث الإنجليزية، رد بالإنجليزية).",
            "- عند كتابة ملخص الحجز أو تفاصيله للتاجر، اكتبه دائماً باللغة العربية لتسهيل قراءته في لوحة التحكم.",
            "",
        ]

        # بيانات الفندق
        prompt_parts.append("=== بيانات الفندق ===")

        if data.get('rooms_count'):
            prompt_parts.append(f"عدد الغرف: {data['rooms_count']}")
        if data.get('floors_count'):
            prompt_parts.append(f"عدد الطوابق: {data['floors_count']}")
        if data.get('star_rating'):
            prompt_parts.append(f"التصنيف: {data['star_rating']} نجوم")
        if data.get('checkin_time'):
            prompt_parts.append(f"وقت الدخول: {data['checkin_time']}")
        if data.get('checkout_time'):
            prompt_parts.append(f"وقت الخروج: {data['checkout_time']}")
        if data.get('amenities'):
            prompt_parts.append(f"المرافق: {data['amenities']}")
        if data.get('address'):
            prompt_parts.append(f"العنوان: {data['address']}")
        if data.get('phone'):
            prompt_parts.append(f"هاتف الحجوزات: {data['phone']}")
        if data.get('email'):
            prompt_parts.append(f"بريد الحجوزات: {data['email']}")
        if data.get('website'):
            prompt_parts.append(f"الموقع: {data['website']}")

        return "\n".join(prompt_parts)

    def get_dashboard_data(self, tenant) -> dict:
        """بيانات إضافية للوحة التحكم."""
        data = tenant.activity_data or {}
        return {
            'rooms_count': data.get('rooms_count', 0),
            'floors_count': data.get('floors_count', 0),
            'star_rating': data.get('star_rating', 0),
            'amenities': data.get('amenities', ''),
            'activity_sections': [
                {'title': 'الغرف والوحدات', 'icon': '🛏️', 'url': '#rooms'},
                {'title': 'الخدمات', 'icon': '🛎️', 'url': '#services'},
                {'title': 'الشكاوى', 'icon': '📋', 'url': '#complaints'},
            ],
        }

    def validate_settings(self, data: dict) -> list:
        """تحقق من صحة بيانات الإعداد. يرجع قائمة أخطاء."""
        errors = []
        rooms = data.get('rooms_count')
        if rooms:
            try:
                int(rooms)
            except ValueError:
                errors.append('عدد الغرف يجب أن يكون رقماً')
        return errors

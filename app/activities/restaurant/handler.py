"""
app/activities/restaurant/handler.py — منطق نشاط المطاعم والكافيهات.
"""


class RestaurantHandler:
    """معالج نشاط المطاعم والكافيهات."""

    def get_system_prompt(self, tenant) -> str:
        data = tenant.activity_data or {}

        prompt_parts = [
            "أنت مضيف ودود في مطعم / كافيه. مهامك:",
            "- تقديم قائمة الطعام والأصناف المتوفرة مع الأسعار",
            "- مساعدة العميل في اختيار الطلب",
            "- معلومات عن حجز الطاولات",
            "- معلومات عن التوصيل والطلب المسبق",
            "- استقبال الشكاوى والملاحظات بلباقة",
            "",
            "=== بيانات المطعم ===",
        ]

        if data.get('cuisine_type'):
            prompt_parts.append(f"نوع المطبخ: {data['cuisine_type']}")
        if data.get('seating_capacity'):
            prompt_parts.append(f"سعة الجلوس: {data['seating_capacity']} شخص")
        if data.get('delivery_available'):
            prompt_parts.append(f"التوصيل: متاح")
            if data.get('delivery_phone'):
                prompt_parts.append(f"رقم التوصيل: {data['delivery_phone']}")
        if data.get('opening_time') and data.get('closing_time'):
            prompt_parts.append(f"ساعات العمل: {data['opening_time']} - {data['closing_time']}")
        if data.get('address'):
            prompt_parts.append(f"العنوان: {data['address']}")
        if data.get('phone'):
            prompt_parts.append(f"الهاتف: {data['phone']}")
        if data.get('menu_description'):
            prompt_parts.append(f"\nقائمة الطعام:\n{data['menu_description']}")

        return "\n".join(prompt_parts)

    def get_dashboard_data(self, tenant) -> dict:
        data = tenant.activity_data or {}
        return {
            'cuisine_type': data.get('cuisine_type', ''),
            'seating_capacity': data.get('seating_capacity', 0),
            'delivery_available': data.get('delivery_available', False),
            'activity_sections': [
                {'title': 'المنيو', 'icon': '📋', 'url': '#menu'},
                {'title': 'الطلبات', 'icon': '🛍️', 'url': '#orders'},
                {'title': 'الحجوزات', 'icon': '📅', 'url': '#reservations'},
            ],
        }

    def validate_settings(self, data: dict) -> list:
        errors = []
        cap = data.get('seating_capacity')
        if cap:
            try:
                int(cap)
            except ValueError:
                errors.append('سعة الجلوس يجب أن تكون رقماً')
        return errors

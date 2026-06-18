"""
app/services/db_search_service.py — بحث ذكي في بيانات التاجر.

يستخدم PostgreSQL ILIKE (case-insensitive) + ترجيح كلمات.

عند طلب العميل عن منتج (غرفة/شقة/صنف):
1. استخراج الكلمات المهمة من الرسالة
2. البحث في DB عن مطابقات
3. إرجاع أنسب 3-5 نتائج بصورها
"""
import re
from typing import List, Dict
from flask import current_app

from app.extensions import db


class DBSearchService:
    """بحث في بيانات التاجر."""

    # كلمات يتم تجاهلها (شيوعها العالي يضرّ الترجيح)
    STOP_WORDS = {
        'في', 'من', 'على', 'الى', 'إلى', 'عن', 'هل', 'هو', 'هي',
        'ان', 'أن', 'لا', 'ما', 'يا', 'و', 'او', 'أو', 'بس',
        'كيف', 'وين', 'فين', 'ليش', 'متى', 'شو', 'وش', 'ايش', 'إيش',
        'كم', 'عدد', 'لكم', 'لي', 'لك', 'له', 'لها',
        'ابغى', 'ابي', 'أبي', 'أبغى', 'عايز', 'عاوز', 'محتاج',
        'تبي', 'تبغى', 'تحب', 'احب',
        'فيه', 'فيها', 'عندكم', 'عندك', 'عندنا',
        'هاي', 'هذي', 'هذا', 'ذي', 'هذه', 'ذلك',
        'الي', 'اللي', 'التي', 'الذي',
        'كذا', 'كذلك', 'هكذا', 'مثل', 'زي',
        'قبل', 'بعد', 'مع', 'بدون',
    }

    @staticmethod
    def extract_keywords(message: str) -> List[str]:
        """استخراج الكلمات المفيدة من الرسالة."""
        if not message:
            return []

        text = message.lower()
        # توحيد العربية
        text = re.sub(r'[إأآا]', 'ا', text)
        text = re.sub(r'ة', 'ه', text)
        text = re.sub(r'ى', 'ي', text)
        # حذف الترقيم
        text = re.sub(r'[؟?!.,،؛:()…\-_\"\'\[\]{}]', ' ', text)
        # حذف الإيموجي
        text = re.sub(r'[\U0001F300-\U0001F9FF]', ' ', text)

        words = text.split()
        keywords = [w for w in words if len(w) >= 2 and w not in DBSearchService.STOP_WORDS]

        # حذف الأرقام إذا أكثر من 4 أرقام (لأنها غالباً phone/id)
        keywords = [w for w in keywords if not (w.isdigit() and len(w) > 4)]

        return keywords[:10]  # أقصى 10 كلمات

    # ========================================
    # البحث في الوحدات الفندقية
    # ========================================
    @staticmethod
    def search_hotel_units(tenant_id: int, message: str, limit: int = 5) -> List[Dict]:
        """
        بحث في الوحدات الفندقية.

        Returns:
            [{ 'id', 'name', 'description', 'price', 'images', 'score' }, ...]
        """
        from app.models.hotel_models import Unit

        keywords = DBSearchService.extract_keywords(message)
        if not keywords:
            return []

        # نبني query — نبحث في أكثر من حقل
        units = Unit.query.filter_by(tenant_id=tenant_id, is_available=True).all()

        scored = []
        for unit in units:
            score = DBSearchService._score_unit(unit, keywords, message)
            if score > 0:
                scored.append((score, unit))

        # ترتيب تنازلي
        scored.sort(key=lambda x: -x[0])

        results = []
        for score, unit in scored[:limit]:
            results.append({
                'id': unit.id,
                'unit_number': unit.unit_number,
                'unit_type': unit.unit_type,
                'description': unit.description or '',
                'bedrooms': unit.bedrooms_count,
                'living_rooms': unit.living_rooms,
                'bathrooms': unit.bathrooms_count,
                'max_guests': unit.max_guests,
                'daily_price': float(unit.daily_price or 0),
                'monthly_price': float(unit.monthly_price or 0),
                'images': unit.images or [],
                'amenities': unit.amenities or '',
                'score': score,
            })

        return results

    @staticmethod
    def _score_unit(unit, keywords: List[str], full_message: str) -> int:
        """حساب درجة المطابقة لوحدة فندقية."""
        score = 0
        msg_lower = full_message.lower()

        # نص قابل للبحث
        searchable = ' '.join([
            unit.unit_type or '',
            unit.unit_number or '',
            unit.description or '',
            unit.amenities or '',
            unit.extra_rooms or '',
        ]).lower()

        # توحيد الحروف
        searchable = re.sub(r'[إأآا]', 'ا', searchable)
        searchable = re.sub(r'ة', 'ه', searchable)

        # نقاط على كل كلمة مفتاحية
        for kw in keywords:
            if kw in searchable:
                score += 3

        # كلمات أنواع وحدات
        type_aliases = {
            'room': ['غرفه', 'غرفة', 'حجره', 'حجرة', 'اوضه', 'أوضة'],
            'apartment': ['شقه', 'شقة', 'استوديو'],
            'suite': ['جناح', 'سويت'],
            'villa': ['فيلا', 'فلة'],
        }
        unit_type = (unit.unit_type or '').lower()
        for ut, aliases in type_aliases.items():
            if unit_type == ut:
                for alias in aliases:
                    if alias in msg_lower:
                        score += 5
                        break

        # ميزانية (لو ذكر رقم في الرسالة)
        budget_match = re.search(r'(\d{2,5})', full_message)
        if budget_match:
            try:
                budget = int(budget_match.group(1))
                price = float(unit.daily_price or 0)
                if 0 < price <= budget:
                    score += 4  # في الميزانية
                elif budget > 0 and abs(price - budget) / budget < 0.2:
                    score += 2  # قريب
            except (ValueError, ZeroDivisionError):
                pass

        # عدد الأشخاص
        guests_match = re.search(r'(\d+)\s*(شخص|اشخاص|أشخاص|نفر|انفار|أفراد)', full_message)
        if guests_match:
            try:
                wanted = int(guests_match.group(1))
                if unit.max_guests and unit.max_guests >= wanted:
                    score += 3
            except ValueError:
                pass

        return score

    # ========================================
    # البحث في أصناف المنيو
    # ========================================
    @staticmethod
    def search_menu_items(tenant_id: int, message: str, limit: int = 5) -> List[Dict]:
        """بحث في أصناف المنيو."""
        from app.models.restaurant_models import MenuItem, MenuCategory

        keywords = DBSearchService.extract_keywords(message)
        if not keywords:
            return []

        items = MenuItem.query.filter_by(tenant_id=tenant_id, is_available=True).all()

        scored = []
        for item in items:
            score = DBSearchService._score_menu_item(item, keywords, message)
            if score > 0:
                scored.append((score, item))

        scored.sort(key=lambda x: -x[0])

        results = []
        for score, item in scored[:limit]:
            cat_name = ''
            if item.category_id:
                cat = MenuCategory.query.get(item.category_id)
                if cat:
                    cat_name = cat.name
            results.append({
                'id': item.id,
                'name': item.name,
                'description': item.description or '',
                'category': cat_name,
                'price': float(item.price or 0),
                'discount_price': float(item.discount_price or 0) if item.discount_price else None,
                'final_price': float(getattr(item, 'final_price', None) or item.price or 0),
                'image': item.image_url or '',
                'is_popular': item.is_popular,
                'is_spicy': item.is_spicy,
                'is_vegetarian': item.is_vegetarian,
                'score': score,
            })

        return results

    @staticmethod
    def _score_menu_item(item, keywords: List[str], full_message: str) -> int:
        """حساب درجة المطابقة لصنف منيو."""
        score = 0

        searchable = ' '.join([
            item.name or '',
            item.description or '',
        ]).lower()
        searchable = re.sub(r'[إأآا]', 'ا', searchable)
        searchable = re.sub(r'ة', 'ه', searchable)

        for kw in keywords:
            if kw in searchable:
                score += 3

        # boost للأصناف المميزة
        if item.is_popular:
            score += 1

        return score

    # ========================================
    # البحث الذكي العام (يحدد النوع تلقائياً)
    # ========================================
    @staticmethod
    def smart_search(tenant_id: int, activity_code: str, message: str) -> List[Dict]:
        """بحث ذكي حسب نوع النشاط."""
        if activity_code == 'hotel':
            return DBSearchService.search_hotel_units(tenant_id, message)
        elif activity_code == 'restaurant':
            return DBSearchService.search_menu_items(tenant_id, message)
        return []

    # ========================================
    # تنسيق النتائج كرد للشات
    # ========================================
    @staticmethod
    def format_hotel_results_as_reply(results: List[Dict], business_name: str) -> Dict:
        """تنسيق نتائج الفنادق كرد + صور."""
        if not results:
            return {'text': '', 'images': []}

        lines = [f'لقيت لك {len(results)} خيار مناسب في {business_name}:\n']
        all_images = []

        for i, r in enumerate(results, 1):
            type_ar = {
                'room': 'غرفة',
                'apartment': 'شقة',
                'suite': 'جناح',
                'villa': 'فيلا',
            }.get(r['unit_type'], r['unit_type'])

            line = f"\n*{i}. {type_ar} {r['unit_number']}*"
            if r['bedrooms']:
                line += f" ({r['bedrooms']} غرف نوم"
                if r['max_guests']:
                    line += f" - تتسع لـ {r['max_guests']} ضيوف"
                line += ")"

            if r['daily_price']:
                line += f"\n💰 يومي: {r['daily_price']:.0f} ر.س"
            if r['monthly_price']:
                line += f" / شهري: {r['monthly_price']:.0f} ر.س"

            if r['description']:
                line += f"\n{r['description'][:120]}"

            lines.append(line)

            # نأخذ أول صورة من كل وحدة
            if r['images']:
                first_img = r['images'][0]
                if first_img:
                    all_images.append(first_img)

        lines.append('\n\n💡 أيهم يناسبك؟ اكتب رقم الخيار أو اسأل عن أي تفاصيل.')

        return {
            'text': '\n'.join(lines),
            'images': all_images[:5],  # أقصى 5 صور
        }

    @staticmethod
    def format_menu_results_as_reply(results: List[Dict], business_name: str) -> Dict:
        """تنسيق نتائج المنيو كرد + صور."""
        if not results:
            return {'text': '', 'images': []}

        lines = [f'لقيت لك {len(results)} صنف في {business_name}:\n']
        all_images = []

        for i, r in enumerate(results, 1):
            line = f"\n*{i}. {r['name']}*"
            if r['category']:
                line += f" — {r['category']}"

            if r['discount_price']:
                line += f"\n💰 ~~{r['price']:.0f}~~ {r['discount_price']:.0f} ر.س (عرض!)"
            else:
                line += f"\n💰 {r['price']:.0f} ر.س"

            tags = []
            if r['is_popular']:
                tags.append('⭐ مميز')
            if r['is_spicy']:
                tags.append('🌶️ حار')
            if r['is_vegetarian']:
                tags.append('🥬 نباتي')
            if tags:
                line += '\n' + ' / '.join(tags)

            if r['description']:
                line += f"\n{r['description'][:100]}"

            lines.append(line)

            if r['image']:
                all_images.append(r['image'])

        lines.append('\n\n💡 أي صنف عجبك؟')

        return {
            'text': '\n'.join(lines),
            'images': all_images[:5],
        }

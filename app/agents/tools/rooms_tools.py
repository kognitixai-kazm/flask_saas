"""
app/agents/tools/rooms_tools.py — أدوات البحث عن الغرف والوحدات الفندقية.

يستخدمها وكيل الاستقبال للبحث عن الغرف المتاحة وعرضها للعملاء.
"""
from langchain_core.tools import tool
from typing import Optional


@tool
def search_available_rooms(
    tenant_id: int,
    unit_type: str = '',
    max_price: float = 0,
    min_bedrooms: int = 0,
    branch_id: int = 0,
) -> str:
    """البحث عن الغرف والشقق المتاحة للإيجار.
    استخدم هذه الأداة عندما يسأل العميل عن الغرف المتاحة أو الأسعار.

    Args:
        tenant_id: معرف التاجر (المنشأة)
        unit_type: نوع الوحدة (apartment=شقة, room=غرفة, suite=جناح, villa=فيلا) — اتركه فارغاً لكل الأنواع
        max_price: الحد الأقصى للسعر الشهري (0 = بدون حد)
        min_bedrooms: أقل عدد غرف نوم مطلوب
        branch_id: معرف الفرع (0 = كل الفروع)
    """
    from app.models.hotel_models import Unit
    from app.models.branch import Branch

    query = Unit.query.filter_by(tenant_id=tenant_id, is_available=True)
    query = query.filter(Unit.status == 'available')

    if unit_type:
        ut = unit_type.lower().strip()
        if ut in ['شقة', 'شقه', 'apartment', 'شقق']:
            ut = 'apartment'
        elif ut in ['غرفة', 'غرفه', 'room', 'غرف']:
            ut = 'room'
        elif ut in ['جناح', 'suite', 'اجنحة', 'أجنحة']:
            ut = 'suite'
        elif ut in ['فيلا', 'villa', 'فلل']:
            ut = 'villa'
        query = query.filter_by(unit_type=ut)
    if max_price > 0:
        query = query.filter(Unit.monthly_price <= max_price)
    if min_bedrooms > 0:
        query = query.filter(Unit.bedrooms_count >= min_bedrooms)
    if branch_id > 0:
        query = query.filter_by(branch_id=branch_id)

    units = query.order_by(Unit.monthly_price.asc()).limit(10).all()

    if not units:
        return 'لا توجد وحدات متاحة حالياً تطابق المعايير المطلوبة.'

    results = []
    for u in units:
        # جلب اسم الفرع
        branch = Branch.query.get(u.branch_id)
        branch_name = branch.name if branch else ''

        images_text = ''
        if u.images and isinstance(u.images, list) and len(u.images) > 0:
            images_text = f' | صور: {u.images[0]}'

        amenities_text = ''
        if u.amenities:
            amenities_text = f' | المرافق: {u.amenities[:100]}'

        results.append(
            f'• {u.type_label} رقم {u.unit_number}'
            f'{" - " + u.title if u.title else ""}'
            f' | {u.bedrooms_count} غرف نوم, {u.bathrooms_count} حمام'
            f' | السعر الشهري: {u.monthly_price} ر.س'
            f'{" | يومي: " + str(u.daily_price) + " ر.س" if float(u.daily_price or 0) > 0 else ""}'
            f' | الطاقة: {u.max_guests} أشخاص'
            f'{" | فرع: " + branch_name if branch_name else ""}'
            f'{amenities_text}{images_text}'
            f' [unit_id={u.id}]'
        )

    return f'الوحدات المتاحة ({len(results)}):\n' + '\n'.join(results)


@tool
def get_room_details(tenant_id: int, unit_id: int) -> str:
    """جلب تفاصيل وحدة محددة بمعرفها.
    استخدم هذه الأداة عندما يريد العميل تفاصيل أكثر عن غرفة معينة.

    Args:
        tenant_id: معرف التاجر
        unit_id: معرف الوحدة
    """
    from app.models.hotel_models import Unit
    from app.models.branch import Branch

    unit = Unit.query.filter_by(id=unit_id, tenant_id=tenant_id).first()
    if not unit:
        return 'لم يتم العثور على هذه الوحدة.'

    branch = Branch.query.get(unit.branch_id)

    details = f"""تفاصيل {unit.type_label} رقم {unit.unit_number}:
• النوع: {unit.type_label}
• العنوان: {unit.title or 'غير محدد'}
• الوصف: {unit.description or 'غير متوفر'}
• غرف النوم: {unit.bedrooms_count}
• الصالات: {unit.living_rooms}
• الحمامات: {unit.bathrooms_count}
• المطابخ: {unit.kitchens}
• المساحة: {unit.area_sqm or 'غير محددة'} م²
• الطاقة الاستيعابية: {unit.max_guests} أشخاص
• السعر الشهري: {unit.monthly_price} ر.س
• السعر اليومي: {unit.daily_price} ر.س
• الحالة: {unit.status_label}
• الفرع: {branch.name if branch else 'غير محدد'}
• المرافق: {unit.amenities or 'غير محددة'}"""

    if unit.images and isinstance(unit.images, list):
        details += f'\n• الصور: {", ".join(unit.images[:5])}'

    if unit.image_360_link:
        details += f'\n• جولة 360°: {unit.image_360_link}'

    return details


@tool
def lock_unit_selection(tenant_id: int, unit_id: int = 0, unit_number: str = '') -> str:
    """تثبيت الوحدة المختارة بعد موافقة العميل عليها لمنع تغييرها بالخطأ.
    استخدم هذه الأداة **فوراً** بعد أن يوافق العميل على وحدة معينة، وقبل أن تطلب منه البيانات أو ملخص الحجز.

    Args:
        tenant_id: معرف التاجر
        unit_id: معرف الوحدة التي اختارها العميل (الأولوية له)
        unit_number: رقم الوحدة التي اختارها العميل (استخدمه إذا لم تكن متأكداً من unit_id)
    """
    from flask import g
    from app.models.conversation import Conversation
    from app.models.hotel_models import Unit
    from app.extensions import db

    conv_id = getattr(g, 'active_conversation_id', None)
    if not conv_id:
        return 'تم التثبيت (بدون جلسة نشطة).'

    conv = Conversation.query.get(conv_id)
    if not conv:
        return 'المحادثة غير موجودة.'

    unit = None
    if unit_id > 0:
        unit = Unit.query.filter_by(id=unit_id, tenant_id=tenant_id).first()
    
    if not unit and unit_number:
        # إذا أرسل الذكاء الاصطناعي الخيار (مثلاً 2) على أنه unit_id بالخطأ،
        # يمكننا محاولة البحث برقم الوحدة
        unit = Unit.query.filter_by(unit_number=str(unit_number).strip(), tenant_id=tenant_id).first()

    if not unit:
        # Fallback in case unit_id was accidentally a sequential number and unit_number was not provided
        if unit_id > 0 and unit_id < 100:
            return 'تنبيه: يبدو أنك أرسلت رقم الخيار (1 أو 2) بدلاً من unit_id الفعلي أو رقم الشقة. يرجى تمرير رقم الشقة الفعلي في parameter `unit_number`.'
        return 'الوحدة غير موجودة.'

    if not unit.is_available or unit.status != 'available':
        return 'هذه الوحدة لم تعد متاحة حالياً. يرجى البحث عن وحدة أخرى.'

    ex = dict(conv.extra_data or {})
    if 'booking_state' not in ex:
        ex['booking_state'] = {}
    
    ex['booking_state']['selected_unit_id'] = unit.id
    conv.extra_data = ex
    db.session.commit()

    return f'تم تثبيت الوحدة {unit.type_label} رقم {unit.unit_number} بنجاح في الجلسة. لا تقم بتغييرها.'


@tool
def get_branches_list(tenant_id: int) -> str:
    """جلب قائمة الفروع المتاحة للمنشأة.
    استخدم هذه الأداة عندما يسأل العميل عن الفروع أو المواقع.

    Args:
        tenant_id: معرف التاجر
    """
    from app.models.branch import Branch

    branches = Branch.query.filter_by(
        tenant_id=tenant_id, is_active=True
    ).all()

    if not branches:
        return 'لا توجد فروع مسجلة حالياً.'

    results = []
    for b in branches:
        units_count = b.units.filter_by(is_available=True).count() if hasattr(b, 'units') else 0
        results.append(
            f'• {b.name}'
            f'{" — " + b.address if hasattr(b, "address") and b.address else ""}'
            f' | {units_count} وحدة متاحة'
            f' [branch_id={b.id}]'
        )

    return f'الفروع ({len(results)}):\n' + '\n'.join(results)

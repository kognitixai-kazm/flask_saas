"""
app/agents/tools/analytics_tools.py — أدوات التحليلات المالية والإدارية.

يستخدمها وكيل المدير (Manager Agent) كشريط بحث ذكي
لاستخراج البيانات والتقارير المالية مباشرة.
"""
from langchain_core.tools import tool


@tool
def get_financial_summary(tenant_id: int, days: int = 30) -> str:
    """جلب ملخص مالي شامل للمنشأة.
    استخدم هذه الأداة عندما يسأل صاحب المنشأة عن الأرباح أو الأداء المالي.

    Args:
        tenant_id: معرف التاجر
        days: عدد الأيام (30 = الشهر الحالي، 90 = آخر 3 أشهر)
    """
    from datetime import datetime, timedelta
    from sqlalchemy import func
    from app.extensions import db
    from app.models.message_usage import MessageUsage
    from app.models.contract import Contract
    from app.models.booking import Booking
    from app.models.tenant_wallet import TenantWallet

    since = datetime.utcnow() - timedelta(days=days)

    # ===== إيرادات العقود =====
    contracts = Contract.query.filter(
        Contract.tenant_id == tenant_id,
        Contract.created_at >= since,
    ).all()

    paid_contracts = [c for c in contracts if c.payment_status == 'paid']
    pending_contracts = [c for c in contracts if c.payment_status == 'pending']
    total_contract_revenue = sum(float(c.payment_paid or 0) for c in paid_contracts)
    total_pending = sum(float(c.payment_amount or 0) for c in pending_contracts)

    # ===== إيرادات الحجوزات =====
    bookings = Booking.query.filter(
        Booking.tenant_id == tenant_id,
        Booking.created_at >= since,
    ).all()

    confirmed_bookings = [b for b in bookings if b.status == 'confirmed']
    paid_bookings = [b for b in bookings if b.is_paid]
    total_booking_revenue = sum(float(b.total_amount or 0) for b in paid_bookings)

    # ===== استهلاك خدمات المنصة =====
    usage_summary = MessageUsage.tenant_summary(tenant_id, days=days)
    total_platform_cost = sum(item['total_spent'] for item in usage_summary)

    # ===== المصاريف =====
    try:
        from app.models.accounting import Expense
        expenses = Expense.query.filter(
            Expense.tenant_id == tenant_id,
            Expense.expense_date >= since.date(),
        ).all()
        total_expenses = sum(float(e.amount or 0) for e in expenses)
        expense_categories = {}
        for e in expenses:
            cat = e.category or 'أخرى'
            expense_categories[cat] = expense_categories.get(cat, 0) + float(e.amount or 0)
    except Exception:
        total_expenses = 0
        expense_categories = {}

    # ===== رصيد المحفظة =====
    wallet = TenantWallet.get_or_create(tenant_id)

    # ===== صافي الأرباح =====
    total_revenue = total_contract_revenue + total_booking_revenue
    net_profit = total_revenue - total_expenses - total_platform_cost

    report = f"""📊 التقرير المالي — آخر {days} يوم:

💰 الإيرادات:
• إيرادات العقود (مدفوعة): {total_contract_revenue:,.2f} ر.س ({len(paid_contracts)} عقد)
• إيرادات الحجوزات: {total_booking_revenue:,.2f} ر.س ({len(paid_bookings)} حجز)
• إجمالي الإيرادات: {total_revenue:,.2f} ر.س

⏳ مبالغ معلقة:
• عقود بانتظار الدفع: {total_pending:,.2f} ر.س ({len(pending_contracts)} عقد)

📤 المصاريف:
• مصاريف تشغيلية: {total_expenses:,.2f} ر.س
• تكلفة خدمات المنصة (AI + واتساب): {total_platform_cost:,.2f} ر.س"""

    if expense_categories:
        report += '\n• تفاصيل المصاريف:'
        for cat, amount in sorted(expense_categories.items(), key=lambda x: -x[1]):
            report += f'\n  - {cat}: {amount:,.2f} ر.س'

    report += f"""

📈 صافي الربح: {net_profit:,.2f} ر.س

💳 رصيد المحفظة: {float(wallet.balance):,.2f} ر.س

📋 ملخص:
• عقود جديدة: {len(contracts)}
• حجوزات جديدة: {len(bookings)}
• حجوزات مؤكدة: {len(confirmed_bookings)}"""

    return report


@tool
def get_occupancy_rate(tenant_id: int) -> str:
    """حساب نسبة الإشغال الحالية للمنشأة.
    استخدم هذه الأداة عندما يسأل صاحب المنشأة عن نسبة الإشغال.

    Args:
        tenant_id: معرف التاجر
    """
    from app.models.hotel_models import Unit

    all_units = Unit.query.filter_by(tenant_id=tenant_id).all()
    if not all_units:
        return 'لا توجد وحدات مسجلة في المنشأة.'

    # فلترة الوحدات القابلة للإيجار (استبعاد المستودعات والمكاتب)
    rentable = [u for u in all_units if u.status not in ('storage', 'office')]
    booked = [u for u in rentable if u.status == 'booked']
    available = [u for u in rentable if u.status == 'available']
    maintenance = [u for u in rentable if u.status == 'maintenance']

    total = len(rentable)
    occupancy = (len(booked) / total * 100) if total > 0 else 0

    # تفصيل حسب النوع
    type_breakdown = {}
    for u in all_units:
        t = u.type_label
        if t not in type_breakdown:
            type_breakdown[t] = {'total': 0, 'booked': 0, 'available': 0}
        type_breakdown[t]['total'] += 1
        if u.status == 'booked':
            type_breakdown[t]['booked'] += 1
        elif u.status == 'available':
            type_breakdown[t]['available'] += 1

    report = f"""🏨 نسبة الإشغال الحالية:

📊 الإجمالي: {occupancy:.1f}%
• إجمالي الوحدات القابلة للإيجار: {total}
• مؤجرة/محجوزة: {len(booked)}
• متاحة: {len(available)}
• صيانة: {len(maintenance)}

📋 تفصيل حسب النوع:"""

    for type_name, data in type_breakdown.items():
        rate = (data['booked'] / data['total'] * 100) if data['total'] > 0 else 0
        report += f"\n• {type_name}: {data['booked']}/{data['total']} ({rate:.0f}%)"

    return report


@tool
def get_usage_analytics(tenant_id: int, days: int = 30) -> str:
    """جلب تحليلات استخدام خدمات المنصة (AI، واتساب، صور).
    استخدم هذه الأداة عندما يريد التاجر معرفة استهلاكه للخدمات.

    Args:
        tenant_id: معرف التاجر
        days: عدد الأيام
    """
    from app.models.message_usage import MessageUsage
    from app.services.pricing_service import PricingService

    summary = MessageUsage.tenant_summary(tenant_id, days=days)
    balance_info = PricingService.get_tenant_balance(tenant_id)

    if not summary:
        return f'لا يوجد استخدام مسجل خلال آخر {days} يوم.'

    service_labels = {
        'ai_message': '🤖 رسائل AI',
        'text_message': '💬 رسائل نصية',
        'whatsapp_message': '📱 رسائل واتساب',
        'image_send': '🖼️ إرسال صور',
        'image_process': '🔍 معالجة صور',
        'audio_send': '🔊 إرسال صوت',
        'audio_process': '🎤 معالجة صوت',
    }

    report = f'📊 تحليلات الاستخدام — آخر {days} يوم:\n\n'

    total_count = 0
    total_spent = 0.0
    for item in summary:
        label = service_labels.get(item['service_type'], item['service_type'])
        report += f"• {label}: {item['count']} عملية — {item['total_spent']:.2f} ر.س\n"
        total_count += item['count']
        total_spent += item['total_spent']

    report += f'\n📈 الإجمالي: {total_count} عملية — {total_spent:.2f} ر.س'
    report += f"\n💳 الرصيد المتبقي: {balance_info['balance']:.2f} ر.س"

    if balance_info['is_low']:
        report += '\n⚠️ تنبيه: الرصيد منخفض! يرجى شحن المحفظة.'

    return report


@tool
def get_monthly_comparison(tenant_id: int) -> str:
    """مقارنة أداء الشهر الحالي بالشهر السابق.
    استخدم هذه الأداة عندما يسأل التاجر عن تطور الأداء.

    Args:
        tenant_id: معرف التاجر
    """
    from datetime import datetime, timedelta
    from app.models.contract import Contract
    from app.models.booking import Booking

    now = datetime.utcnow()
    this_month_start = now.replace(day=1, hour=0, minute=0, second=0)
    last_month_start = (this_month_start - timedelta(days=1)).replace(day=1)

    # عقود الشهر الحالي
    this_contracts = Contract.query.filter(
        Contract.tenant_id == tenant_id,
        Contract.created_at >= this_month_start,
    ).all()
    this_revenue = sum(
        float(c.payment_paid or 0)
        for c in this_contracts if c.payment_status == 'paid'
    )

    # عقود الشهر السابق
    last_contracts = Contract.query.filter(
        Contract.tenant_id == tenant_id,
        Contract.created_at >= last_month_start,
        Contract.created_at < this_month_start,
    ).all()
    last_revenue = sum(
        float(c.payment_paid or 0)
        for c in last_contracts if c.payment_status == 'paid'
    )

    # حجوزات
    this_bookings = Booking.query.filter(
        Booking.tenant_id == tenant_id,
        Booking.created_at >= this_month_start,
    ).count()
    last_bookings = Booking.query.filter(
        Booking.tenant_id == tenant_id,
        Booking.created_at >= last_month_start,
        Booking.created_at < this_month_start,
    ).count()

    # حساب التغيير
    def calc_change(current, previous):
        if previous == 0:
            return '+100%' if current > 0 else '0%'
        change = ((current - previous) / previous) * 100
        sign = '+' if change > 0 else ''
        return f'{sign}{change:.1f}%'

    report = f"""📊 مقارنة شهرية:

💰 الإيرادات:
• الشهر الحالي: {this_revenue:,.2f} ر.س
• الشهر السابق: {last_revenue:,.2f} ر.س
• التغيير: {calc_change(this_revenue, last_revenue)}

📝 العقود:
• الشهر الحالي: {len(this_contracts)} عقد
• الشهر السابق: {len(last_contracts)} عقد
• التغيير: {calc_change(len(this_contracts), len(last_contracts))}

🏨 الحجوزات:
• الشهر الحالي: {this_bookings} حجز
• الشهر السابق: {last_bookings} حجز
• التغيير: {calc_change(this_bookings, last_bookings)}"""

    return report


@tool
def get_recent_inquiries(tenant_id: int, status: str = 'new', days: int = 7) -> str:
    """جلب أحدث الطلبات والشكاوى من النزلاء.
    استخدم هذه الأداة عندما يسأل صاحب المنشأة عن شكاوى أو طلبات العملاء الحالية.

    Args:
        tenant_id: معرف التاجر
        status: حالة الطلب (new=جديد، pending=قيد المعالجة، answered=تم الرد، closed=مغلق). استخدم 'all' لجلب الكل.
        days: عدد الأيام السابقة للبحث (الافتراضي 7 أيام)
    """
    from datetime import datetime, timedelta
    from app.models.inquiry import Inquiry
    from app.models.branch import Branch

    since = datetime.utcnow() - timedelta(days=days)
    
    query = Inquiry.query.filter(
        Inquiry.tenant_id == tenant_id,
        Inquiry.created_at >= since
    )

    if status and status != 'all':
        query = query.filter(Inquiry.status == status)

    inquiries = query.order_by(Inquiry.created_at.desc()).limit(20).all()

    if not inquiries:
        return f'لا توجد طلبات أو شكاوى مسجلة بحالة "{status}" خلال {days} أيام الماضية.'

    report = f'📋 أحدث الطلبات والشكاوى ({len(inquiries)}):\n\n'
    
    for inq in inquiries:
        branch_name = ''
        if inq.branch_id:
            b = Branch.query.get(inq.branch_id)
            branch_name = f' - فرع: {b.name}' if b else ''
            
        unit_info = f' - وحدة: {inq.unit_number}' if inq.unit_number else ''
        
        kind_label = '🔴 شكوى' if inq.kind == 'complaint' else '🔵 استفسار/طلب'
        
        report += (
            f'{kind_label} [{inq.category_label}]\n'
            f'• العميل: {inq.visitor_name} {branch_name}{unit_info}\n'
            f'• الرسالة: {inq.question}\n'
            f'• الحالة: {inq.status_label}\n'
            f'• التاريخ: {inq.created_at.strftime("%Y-%m-%d %H:%M")}\n'
            f'---\n'
        )

    return report

"""
app/agents/tools/contract_tools.py — أدوات إدارة العقود.

يستخدمها وكيل الاستقبال لإنشاء مسودات العقود وإرسالها.
"""
from langchain_core.tools import tool
from typing import Optional


@tool
def create_draft_contract(
    tenant_id: int,
    customer_name: str,
    customer_phone: str,
    customer_id_number: str = '',
    customer_email: str = '',
    unit_id: int = 0,
    duration_months: int = 1,
    check_in_date: str = '',
    conversation_id: int = 0,
) -> str:
    """إنشاء مسودة عقد إيجار جديد.
    استخدم هذه الأداة بعد جمع بيانات العميل وموافقته على الحجز.

    Args:
        tenant_id: معرف التاجر
        customer_name: اسم العميل الكامل
        customer_phone: رقم هاتف العميل
        customer_id_number: رقم الهوية (اختياري)
        customer_email: البريد الإلكتروني (اختياري)
        unit_id: معرف الوحدة المختارة
        duration_months: مدة الإيجار بالأشهر
        check_in_date: تاريخ الدخول (YYYY-MM-DD)
        conversation_id: معرف المحادثة (لربط العقد بالمحادثة)
    """
    from datetime import datetime, timedelta
    from app.extensions import db
    from app.models.contract import Contract
    from app.models.contract_template import ContractTemplate
    from app.models.hotel_models import Unit

    # التحقق من الوحدة
    if unit_id:
        unit = Unit.query.filter_by(id=unit_id, tenant_id=tenant_id).first()
        if not unit:
            return 'لم يتم العثور على الوحدة المحددة.'
        if not unit.is_available or unit.status != 'available':
            return f'الوحدة رقم {unit.unit_number} غير متاحة حالياً (الحالة: {unit.status_label}).'
        monthly_price = float(unit.monthly_price or 0)
    else:
        monthly_price = 0

    # البحث عن قالب عقد
    template = ContractTemplate.query.filter_by(
        tenant_id=tenant_id, is_active=True
    ).first()

    if not template:
        return 'لا يوجد قالب عقد مفعّل. يرجى التواصل مع الإدارة لتفعيل قوالب العقود.'

    # حساب التواريخ
    if check_in_date:
        try:
            ci_date = datetime.strptime(check_in_date, '%Y-%m-%d')
        except ValueError:
            ci_date = datetime.utcnow()
    else:
        ci_date = datetime.utcnow()

    co_date = ci_date + timedelta(days=duration_months * 30)
    total_amount = monthly_price * duration_months

    # إنشاء العقد
    contract = Contract(
        tenant_id=tenant_id,
        template_id=template.id,
        conversation_id=conversation_id or None,
        unit_id=unit_id or None,
        customer_name=customer_name,
        customer_phone=customer_phone,
        customer_email=customer_email,
        customer_id_number=customer_id_number,
        status='draft',
        payment_amount=total_amount,
        payment_status='pending',
        field_values={
            'full_name': customer_name,
            'phone': customer_phone,
            'id_number': customer_id_number,
            'email': customer_email,
            'check_in_date': ci_date.strftime('%Y-%m-%d'),
            'check_out_date': co_date.strftime('%Y-%m-%d'),
            'duration': str(duration_months),
            'monthly_price': str(monthly_price),
            'total_amount': str(total_amount),
        },
    )
    db.session.add(contract)
    db.session.flush()
    contract.generate_contract_number()
    db.session.commit()

    return (
        f'✅ تم إنشاء مسودة عقد بنجاح!\n'
        f'• رقم العقد: {contract.contract_number}\n'
        f'• العميل: {customer_name}\n'
        f'• المدة: {duration_months} شهر\n'
        f'• الإيجار الشهري: {monthly_price} ر.س\n'
        f'• الإجمالي: {total_amount} ر.س\n'
        f'• تاريخ الدخول: {ci_date.strftime("%Y-%m-%d")}\n'
        f'• تاريخ الخروج: {co_date.strftime("%Y-%m-%d")}\n'
        f'• الحالة: مسودة — بانتظار الدفع\n'
        f'[contract_id={contract.id}]'
    )


@tool
def get_contract_status(tenant_id: int, contract_number: str = '', contract_id: int = 0) -> str:
    """الاستعلام عن حالة عقد.
    استخدم هذه الأداة عندما يسأل العميل عن حالة عقده.

    Args:
        tenant_id: معرف التاجر
        contract_number: رقم العقد (مثل CON-1-20260615-0001)
        contract_id: معرف العقد (بديل عن رقم العقد)
    """
    from app.models.contract import Contract

    if contract_number:
        contract = Contract.query.filter_by(
            tenant_id=tenant_id,
            contract_number=contract_number,
        ).first()
    elif contract_id:
        contract = Contract.query.filter_by(
            tenant_id=tenant_id, id=contract_id,
        ).first()
    else:
        return 'يرجى تقديم رقم العقد أو معرفه.'

    if not contract:
        return 'لم يتم العثور على العقد.'

    fv = contract.field_values or {}

    return (
        f'حالة العقد {contract.contract_number}:\n'
        f'• العميل: {contract.customer_name}\n'
        f'• الحالة: {contract.status_label}\n'
        f'• حالة الدفع: {contract.payment_status}\n'
        f'• المبلغ: {contract.payment_amount} ر.س\n'
        f'• المدفوع: {contract.payment_paid} ر.س\n'
        f'• تاريخ الدخول: {fv.get("check_in_date", "غير محدد")}\n'
        f'• تاريخ الخروج: {fv.get("check_out_date", "غير محدد")}\n'
        f'• المدة: {fv.get("duration", "غير محددة")} شهر'
    )


@tool
def list_expiring_contracts(tenant_id: int, days_ahead: int = 7) -> str:
    """جلب العقود التي ستنتهي خلال فترة محددة.
    يستخدمها وكيل التحصيل لتحديد العملاء الذين يحتاجون متابعة.

    Args:
        tenant_id: معرف التاجر
        days_ahead: عدد الأيام المتبقية (افتراضي: 7 أيام)
    """
    from datetime import datetime, timedelta
    from app.models.contract import Contract

    now = datetime.utcnow()
    contracts = Contract.query.filter(
        Contract.tenant_id == tenant_id,
        Contract.status.in_(['draft', 'pending_payment', 'sent', 'signed']),
    ).all()

    expiring = []
    for c in contracts:
        fv = c.field_values or {}
        check_out = fv.get('check_out_date', '')
        check_in = fv.get('check_in_date', '')
        duration = fv.get('duration', '')

        if not check_out and check_in and duration:
            try:
                ci_date = datetime.strptime(check_in, '%Y-%m-%d')
                co_date = ci_date + timedelta(days=int(duration) * 30)
                check_out = co_date.strftime('%Y-%m-%d')
            except (ValueError, TypeError):
                continue

        if check_out:
            try:
                co_date = datetime.strptime(check_out, '%Y-%m-%d')
                days_left = (co_date - now).days

                if days_left <= days_ahead and c.payment_status != 'paid':
                    expiring.append({
                        'contract': c,
                        'days_left': days_left,
                        'check_out': check_out,
                    })
            except (ValueError, TypeError):
                continue

    if not expiring:
        return f'لا توجد عقود ستنتهي خلال {days_ahead} أيام.'

    expiring.sort(key=lambda x: x['days_left'])
    results = []
    for item in expiring:
        c = item['contract']
        results.append(
            f'• عقد {c.contract_number} — {c.customer_name}'
            f' | هاتف: {c.customer_phone}'
            f' | المبلغ: {c.payment_amount} ر.س'
            f' | ينتهي: {item["check_out"]}'
            f' | متبقي: {item["days_left"]} يوم'
            f' [contract_id={c.id}]'
        )

    return f'العقود المنتهية أو قريبة الانتهاء ({len(results)}):\n' + '\n'.join(results)

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
def process_booking_request(
    tenant_id: int,
    customer_name: str,
    customer_phone: str,
    unit_id: int,
    check_in_date: Optional[str] = None,
    duration_months: int = 1,
    payment_method: str = 'cash',
    customer_email: Optional[str] = None,
    conversation_id: int = 0
) -> str:
    """معالجة طلب الحجز كاملاً بعد استيفاء البيانات.
    استخدم هذه الأداة عندما يكتمل جمع بيانات الحجز (الوحدة، التواريخ، طريقة الدفع).

    Args:
        tenant_id: معرف التاجر
        customer_name: اسم العميل
        customer_phone: جوال العميل
        unit_id: معرف الوحدة
        check_in_date: تاريخ الدخول (YYYY-MM-DD)
        duration_months: مدة الإقامة بالأشهر (أو الليالي إذا كان الإيجار يومي)
        payment_method: طريقة الدفع المختارة (cash، transfer، أو online)
        conversation_id: معرف المحادثة
    """
    from datetime import datetime
    from app.extensions import db
    from app.models.hotel_models import Unit
    from app.models.booking import Booking
    from app.models.tenant import Tenant
    from app.agents.tools.payment_tools import generate_payment_link, get_tenant_bank_info

    unit = Unit.query.filter_by(id=unit_id, tenant_id=tenant_id).first()
    if not unit:
        return 'عذراً، لم يتم العثور على الوحدة المطلوبة.'
    if not unit.is_available or unit.status != 'available':
        return f'عذراً، الوحدة رقم {unit.unit_number} غير متاحة حالياً.'

    tenant = Tenant.query.get(tenant_id)
    pm = payment_method.lower().strip()

    # إنشاء سجل الحجز الأساسي
    booking = Booking(
        tenant_id=tenant_id,
        booking_number=Booking.generate_booking_number(),
        booking_type='hotel_room',
        customer_name=customer_name,
        customer_phone=customer_phone,
        conversation_id=conversation_id or None,
        status='new',
        unit_id=unit.id,
        branch_id=unit.branch_id,
        requested_unit_type=unit.unit_type,
        notes=f"طلب من الذكاء الاصطناعي - الدفع: {pm}",
    )
    
    try:
        ci_date = datetime.strptime(check_in_date, '%Y-%m-%d')
        booking.checkin_date = ci_date.date()
    except ValueError:
        pass

    db.session.add(booking)
    db.session.flush()

    response_lines = [f"تم تسجيل طلب الحجز بنجاح برقم {booking.booking_number} للوحدة {unit.unit_number}."]

    # إشعار التاجر بالحجز الجديد
    try:
        from app.utils.notification_service import NotificationService
        NotificationService.notify_tenant(
            tenant_id=tenant_id,
            category='booking',
            title=f'طلب حجز جديد #{booking.booking_number}',
            body=f'{customer_name} — طريقة الدفع: {pm}',
            action_url=f'/app/bookings/{booking.id}',
            icon='📅',
        )
    except Exception as e:
        import logging; logging.getLogger(__name__).warning(f'[Notification] booking notify error: {e}')

    if pm == 'cash':
        booking.status = 'confirmed' # حجز الكاش قد يُعتبر مؤكداً مبدئياً
        db.session.commit()
        response_lines.append("طريقة الدفع المختارة: كاش. تم تأكيد الحجز المبدئي، بانتظار وصولك.")
        return "\n".join(response_lines)
    
    # لخيارات transfer و online نقوم بإنشاء مسودة عقد
    draft_result = create_draft_contract.invoke({
        "tenant_id": tenant_id,
        "customer_name": customer_name,
        "customer_phone": customer_phone,
        "customer_email": customer_email or "",
        "unit_id": unit_id,
        "duration_months": duration_months,
        "check_in_date": check_in_date,
        "conversation_id": conversation_id,
    })
    
    # استخراج رقم العقد لو أمكن
    import re
    match = re.search(r'\[contract_id=(\d+)\]', draft_result)
    contract_id = int(match.group(1)) if match else 0
    
    if contract_id:
        from app.models.contract import Contract
        contract = Contract.query.get(contract_id)
        if contract:
            # تحديث العقد ليرتبط برقم الحجز بالملاحظات
            contract.notes = f"مرتبط بحجز رقم {booking.booking_number}"
    
    db.session.commit()
    
    if pm == 'transfer':
        bank_info = get_tenant_bank_info.invoke({"tenant_id": tenant_id})
        response_lines.append("لقد قمنا بإنشاء مسودة العقد، وبانتظار تأكيد الدفع.")
        response_lines.append(bank_info)
        response_lines.append("بمجرد إرسالك للإيصال واعتماده من الإدارة، سيصلك رابط لتوقيع العقد إلكترونياً، وبعد التوقيع ستحصل على نسختك المعتمدة مباشرة.")
    else:
        # online
        if tenant.payment_gateway_enabled:
            payment_link = generate_payment_link.invoke({
                "tenant_id": tenant_id,
                "contract_id": contract_id,
            })
            response_lines.append("لقد قمنا بإنشاء العقد. يرجى إتمام الدفع عبر الرابط التالي:")
            response_lines.append(payment_link)
            response_lines.append("بعد إتمام الدفع، سيصلك رابط لتوقيع العقد إلكترونياً واعتماده.")
        else:
            response_lines.append("عذراً، الدفع الإلكتروني غير مفعل حالياً. يرجى الدفع عبر التحويل البنكي:")
            bank_info = get_tenant_bank_info.invoke({"tenant_id": tenant_id})
            response_lines.append(bank_info)
            response_lines.append("بعد الاعتماد سيصلك رابط توقيع العقد.")

    return "\n".join(response_lines)


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

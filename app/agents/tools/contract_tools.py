"""
app/agents/tools/contract_tools.py — أدوات إدارة العقود.

يستخدمها وكيل الاستقبال لإنشاء مسودات العقود وإرسالها.

الإصلاحات المطبقة:
- #1: حفظ checkout_date في Booking
- #2: حساب duration_nights الصحيح
- #3: ربط Booking ↔ Contract عبر booking_id في field_values
- #4: إرسال رابط التوقيع للعميل في نهاية process_booking_request
- #5: الاستغناء عن payment_gateway_enabled (غير موجود في Tenant) والاعتماد على PaymentService مباشرة
- #6: تحديث حالة الوحدة إلى 'reserved' فور إنشاء الحجز (قبل تأكيد الدفع)
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
    check_in_date: str,
    duration_months: int,
    payment_method: str,
    conversation_id: int = 0,
    customer_email: str = '',
) -> str:
    """معالجة طلب الحجز كاملاً بعد استيفاء البيانات.
    استخدم هذه الأداة عندما يكتمل جمع بيانات الحجز (الوحدة، التواريخ، طريقة الدفع).

    Args:
        tenant_id: معرف التاجر
        customer_name: اسم العميل
        customer_phone: جوال العميل
        unit_id: معرف الوحدة
        check_in_date: تاريخ الدخول (YYYY-MM-DD)
        duration_months: مدة الإقامة بالأشهر (ضع 1 إذا كانت ليالي قليلة)
        payment_method: طريقة الدفع المختارة (cash، transfer، أو online)
        conversation_id: معرف المحادثة
        customer_email: البريد الإلكتروني (اختياري)
    """
    import logging
    import re
    from datetime import datetime, timedelta
    from flask import current_app
    from app.extensions import db
    from app.models.hotel_models import Unit
    from app.models.booking import Booking
    from app.models.tenant import Tenant
    from app.agents.tools.payment_tools import generate_payment_link, get_tenant_bank_info

    logger = logging.getLogger(__name__)

    # ── التحقق من الوحدة ─────────────────────────────────────────
    unit = Unit.query.filter_by(id=unit_id, tenant_id=tenant_id).first()
    if not unit:
        return 'عذراً، لم يتم العثور على الوحدة المطلوبة.'
    if not unit.is_available or unit.status != 'available':
        return f'عذراً، الوحدة رقم {unit.unit_number} غير متاحة حالياً.'

    tenant = Tenant.query.get(tenant_id)
    pm = payment_method.lower().strip()

    # ── حساب تاريخ الخروج ──────────────────────────────────────────
    try:
        ci_date = datetime.strptime(check_in_date, '%Y-%m-%d')
    except (ValueError, TypeError):
        ci_date = datetime.utcnow()

    # [إصلاح #1 و #2] حساب تاريخ الخروج وعدد الليالي
    co_date = ci_date + timedelta(days=duration_months * 30)
    duration_nights = (co_date - ci_date).days

    # ── إنشاء سجل الحجز مع كل البيانات ────────────────────────────
    booking = Booking(
        tenant_id=tenant_id,
        booking_number=Booking.generate_booking_number(),
        booking_type='hotel_room',
        customer_name=customer_name,
        customer_phone=customer_phone,
        customer_email=customer_email or '',
        conversation_id=conversation_id or None,
        status='new',
        unit_id=unit.id,
        branch_id=unit.branch_id,
        requested_unit_type=unit.unit_type,
        notes=f'طلب من الذكاء الاصطناعي - الدفع: {pm}',
        # [إصلاح #1] حفظ كلا التاريخين
        checkin_date=ci_date.date(),
        checkout_date=co_date.date(),
        guests_count=1,
    )

    db.session.add(booking)
    db.session.flush()  # للحصول على booking.id

    # [إصلاح #6] تحديث حالة الوحدة فوراً إلى "محجوزة مبدئياً"
    # (ستُحدَّث إلى 'booked' بشكل نهائي عند اكتمال الدفع في handle_webhook)
    unit.status = 'reserved'
    unit.is_available = False

    response_lines = [
        f'✅ تم تسجيل طلب الحجز برقم {booking.booking_number}',
        f'• الوحدة: {unit.unit_number}',
        f'• تاريخ الدخول: {ci_date.strftime("%Y-%m-%d")}',
        f'• تاريخ الخروج: {co_date.strftime("%Y-%m-%d")}',
        f'• المدة: {duration_months} شهر ({duration_nights} ليلة)',
    ]

    # ── إشعار التاجر ───────────────────────────────────────────────
    try:
        from app.utils.notification_service import NotificationService
        NotificationService.notify_tenant(
            tenant_id=tenant_id,
            category='booking',
            title=f'طلب حجز جديد #{booking.booking_number}',
            body=f'{customer_name} — الوحدة: {unit.unit_number} — الدفع: {pm}',
            action_url=f'/app/bookings/{booking.id}',
            icon='📅',
        )
    except Exception as e:
        logger.warning(f'[Notification] booking notify error: {e}')

    # ── الكاش: تأكيد فوري بدون عقد ────────────────────────────────
    if pm == 'cash':
        booking.status = 'confirmed'
        db.session.commit()
        response_lines.append('\n💵 طريقة الدفع: كاش')
        response_lines.append('تم تأكيد الحجز المبدئي. نتطلع لاستقبالك!')
        return '\n'.join(response_lines)

    # ── Transfer / Online: إنشاء مسودة عقد ────────────────────────
    monthly_price = float(unit.monthly_price or 0)
    total_amount = monthly_price * duration_months

    draft_result = create_draft_contract.invoke({
        'tenant_id': tenant_id,
        'customer_name': customer_name,
        'customer_phone': customer_phone,
        'customer_email': customer_email or '',
        'unit_id': unit_id,
        'duration_months': duration_months,
        'check_in_date': check_in_date,
        'conversation_id': conversation_id,
    })

    # استخراج contract_id من نتيجة الأداة
    match = re.search(r'\[contract_id=(\d+)\]', draft_result)
    contract_id = int(match.group(1)) if match else 0

    contract = None
    sign_url = ''

    if contract_id:
        from app.models.contract import Contract
        contract = Contract.query.get(contract_id)
        if contract:
            # [إصلاح #3] ربط الحجز بالعقد في field_values
            fv = contract.field_values or {}
            fv['booking_id'] = booking.id
            fv['booking_number'] = booking.booking_number
            contract.field_values = fv

            # تحديث حالة العقد
            contract.status = 'pending_payment'

            # [إصلاح #4] بناء رابط التوقيع جاهزاً للإرسال لاحقاً (بعد الدفع)
            # يُرسَل تلقائياً بواسطة ContractService.send_to_customer بعد الدفع
            try:
                site_url = current_app.config.get('SITE_URL', '')
                if site_url and contract.signature_token:
                    sign_url = f'{site_url}/contract/sign/{contract.signature_token}'
            except Exception:
                pass

    db.session.commit()

    # ── التحويل البنكي ──────────────────────────────────────────────
    if pm == 'transfer':
        bank_info = get_tenant_bank_info.invoke({'tenant_id': tenant_id})
        response_lines.append('\n📝 تم إنشاء مسودة عقدك بنجاح.')
        response_lines.append(f'• رقم العقد: {contract.contract_number if contract else "—"}')
        response_lines.append(f'• المبلغ الإجمالي: {total_amount} ر.س')
        response_lines.append('\n🏦 بيانات التحويل البنكي:')
        response_lines.append(bank_info)
        response_lines.append(
            '\nبعد إرسال إيصال التحويل واعتماده من الإدارة، '
            'ستصلك رسالة برابط توقيع العقد إلكترونياً على جوالك.'
        )
        return '\n'.join(response_lines)

    # ── الدفع الإلكتروني ────────────────────────────────────────────
    # [إصلاح #5] الاعتماد على PaymentService مباشرة بدلاً من payment_gateway_enabled
    if contract_id:
        payment_result = generate_payment_link.invoke({
            'tenant_id': tenant_id,
            'contract_id': contract_id,
        })

        # إذا نجح إنشاء الرابط
        if '✅' in payment_result or 'رابط الدفع' in payment_result:
            response_lines.append('\n📝 تم إنشاء عقدك بنجاح.')
            response_lines.append(f'• رقم العقد: {contract.contract_number if contract else "—"}')
            response_lines.append(f'• المبلغ: {total_amount} ر.س')
            response_lines.append('\n💳 يرجى إتمام الدفع عبر الرابط التالي:')
            response_lines.append(payment_result)
            response_lines.append(
                '\nبعد إتمام الدفع ستصلك رسالة تلقائية برابط '
                'توقيع العقد إلكترونياً. ✍️'
            )
            return '\n'.join(response_lines)
        else:
            # بوابة الدفع غير مفعلة أو خطأ — تحويل بنكي كبديل
            bank_info = get_tenant_bank_info.invoke({'tenant_id': tenant_id})
            response_lines.append('\n📝 تم إنشاء مسودة عقدك.')
            response_lines.append(
                '⚠️ الدفع الإلكتروني غير متاح حالياً، '
                'يمكنك الدفع عبر التحويل البنكي:'
            )
            response_lines.append(bank_info)
            response_lines.append(
                '\nأرسل إيصال التحويل وسيصلك رابط توقيع العقد بعد الاعتماد.'
            )
            return '\n'.join(response_lines)
    else:
        # فشل إنشاء العقد — خطأ نادر
        response_lines.append('\n⚠️ حدث خطأ في إنشاء العقد. يرجى التواصل مع الإدارة.')
        return '\n'.join(response_lines)


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

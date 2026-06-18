"""
app/agents/tools/payment_tools.py — أدوات الدفع والحساب البنكي.

يستخدمها وكيل التحصيل لإنشاء روابط الدفع وإرسال بيانات الحساب البنكي.
"""
from langchain_core.tools import tool


@tool
def generate_payment_link(
    tenant_id: int,
    contract_id: int,
    amount: float = 0,
    description: str = '',
) -> str:
    """إنشاء رابط دفع إلكتروني للعميل.
    استخدم هذه الأداة عندما يريد العميل الدفع إلكترونياً (مدى/فيزا).

    Args:
        tenant_id: معرف التاجر
        contract_id: معرف العقد
        amount: المبلغ (0 = يؤخذ من العقد)
        description: وصف الدفعة
    """
    from flask import current_app
    from app.extensions import db
    from app.models.contract import Contract
    from app.services.payment_service import PaymentService

    contract = Contract.query.filter_by(id=contract_id, tenant_id=tenant_id).first()
    if not contract:
        return 'لم يتم العثور على العقد.'

    if contract.payment_status == 'paid':
        return f'العقد {contract.contract_number} مدفوع بالفعل.'

    pay_amount = amount or float(contract.payment_amount or 0)
    if pay_amount <= 0:
        return 'لم يتم تحديد مبلغ الدفع في العقد.'

    desc = description or f'دفعة إيجار — عقد {contract.contract_number}'

    site_url = current_app.config.get('SITE_URL', 'http://localhost:5000')
    callback = f'{site_url}/api/v1/webhooks/payment'

    result = PaymentService.create_payment_link(
        tenant_id=tenant_id,
        amount=pay_amount,
        description=desc,
        customer_name=contract.customer_name,
        customer_email=contract.customer_email,
        customer_phone=contract.customer_phone,
        callback_url=callback,
    )

    if result.get('error'):
        return f'خطأ في إنشاء رابط الدفع: {result["error"]}'

    # حفظ مرجع الدفع
    contract.payment_reference = result.get('payment_id', '')
    contract.status = 'pending_payment'
    db.session.commit()

    return (
        f'✅ تم إنشاء رابط الدفع بنجاح:\n'
        f'• رابط الدفع: {result["payment_url"]}\n'
        f'• المبلغ: {pay_amount} ر.س\n'
        f'• رقم العقد: {contract.contract_number}\n'
        f'يمكن للعميل الدفع عبر مدى أو فيزا.'
    )


@tool
def get_tenant_bank_info(tenant_id: int) -> str:
    """جلب بيانات الحساب البنكي للتاجر.
    استخدم هذه الأداة عندما يريد العميل الدفع بالتحويل البنكي.

    Args:
        tenant_id: معرف التاجر
    """
    from app.models.tenant import Tenant

    tenant = Tenant.query.get(tenant_id)
    if not tenant:
        return 'لم يتم العثور على بيانات المنشأة.'

    if not tenant.bank_name and not tenant.bank_iban:
        return 'لم يتم تسجيل بيانات الحساب البنكي بعد. يرجى التواصل مع الإدارة.'

    bank_info = f"""بيانات الحساب البنكي للتحويل:
• البنك: {tenant.bank_name or 'غير محدد'}
• اسم صاحب الحساب: {tenant.bank_account_name or 'غير محدد'}
• رقم الحساب: {tenant.bank_account_number or 'غير محدد'}
• رقم الآيبان (IBAN): {tenant.bank_iban or 'غير محدد'}

يرجى إرسال صورة إيصال التحويل بعد الدفع للتأكيد."""

    return bank_info


@tool
def send_collection_reminder(
    tenant_id: int,
    contract_id: int,
    channels: str = 'whatsapp',
) -> str:
    """إرسال رسالة تذكير بالدفع للعميل عبر القنوات المحددة.
    يستخدمها وكيل التحصيل لإرسال تذكيرات الدفع.

    Args:
        tenant_id: معرف التاجر
        contract_id: معرف العقد
        channels: القنوات المطلوبة مفصولة بفاصلة (whatsapp,email,sms)
    """
    from flask import current_app
    from app.models.contract import Contract
    from app.models.tenant import Tenant

    contract = Contract.query.filter_by(id=contract_id, tenant_id=tenant_id).first()
    if not contract:
        return 'لم يتم العثور على العقد.'

    if contract.payment_status == 'paid':
        return f'العقد {contract.contract_number} مدفوع بالفعل. لا حاجة لتذكير.'

    tenant = Tenant.query.get(tenant_id)
    if not tenant:
        return 'لم يتم العثور على بيانات المنشأة.'

    # إعداد الرسالة
    fv = contract.field_values or {}
    check_out = fv.get('check_out_date', 'غير محدد')

    # إضافة بيانات البنك في الرسالة
    bank_section = ''
    if tenant.bank_name or tenant.bank_iban:
        bank_section = (
            f'\n\n💳 للتحويل البنكي:\n'
            f'البنك: {tenant.bank_name}\n'
            f'الحساب: {tenant.bank_account_name}\n'
            f'الآيبان: {tenant.bank_iban}'
        )

    # رسالة التذكير
    tenant_settings = tenant.settings or {}
    custom_msg = tenant_settings.get('global_reminder_message', '')
    if not custom_msg:
        custom_msg = (
            f'السلام عليكم {contract.customer_name} 🌹\n'
            f'نود تذكيركم باقتراب موعد الدفع للإيجار.\n'
            f'المبلغ: {contract.payment_amount} ر.س\n'
            f'تاريخ الاستحقاق: {check_out}\n'
            f'رقم العقد: {contract.contract_number}'
            f'{bank_section}\n\n'
            f'شاكرين ومقدرين حسن تعاونكم. 🙏'
        )

    sent_channels = []
    errors = []

    channel_list = [c.strip().lower() for c in channels.split(',')]

    # 1. واتساب
    if 'whatsapp' in channel_list and contract.customer_phone:
        try:
            from app.services.whatsapp_service import WhatsAppService
            WhatsAppService.send_text(tenant_id, contract.customer_phone, custom_msg)
            sent_channels.append('واتساب')
        except Exception as e:
            errors.append(f'واتساب: {str(e)[:80]}')

    # 2. إيميل
    if 'email' in channel_list and contract.customer_email:
        try:
            from app.services.email_service import EmailService
            site_url = current_app.config.get('SITE_URL', 'http://localhost:5000')
            payment_link = f'{site_url}/pay/{contract.contract_number or contract.id}'
            EmailService.send_payment_reminder(
                to_email=contract.customer_email,
                tenant_name=tenant.business_name,
                contract_number=contract.contract_number or str(contract.id),
                amount=str(contract.payment_amount),
                due_date=check_out,
                payment_link=payment_link,
                bank_name=tenant.bank_name,
                bank_account_name=tenant.bank_account_name,
                bank_iban=tenant.bank_iban,
            )
            sent_channels.append('إيميل')
        except Exception as e:
            errors.append(f'إيميل: {str(e)[:80]}')

    # 3. رسائل نصية SMS
    if 'sms' in channel_list and contract.customer_phone:
        try:
            from app.services.sms_service import SMSService
            short_msg = (
                f'تذكير بدفع الإيجار: {contract.payment_amount} ر.س — '
                f'عقد {contract.contract_number}'
            )
            SMSService.send_sms(tenant_id, contract.customer_phone, short_msg)
            sent_channels.append('رسائل نصية')
        except Exception as e:
            errors.append(f'SMS: {str(e)[:80]}')

    # تجميع النتيجة
    result_parts = []
    if sent_channels:
        result_parts.append(f'✅ تم إرسال التذكير عبر: {", ".join(sent_channels)}')
    if errors:
        result_parts.append(f'⚠️ أخطاء: {"; ".join(errors)}')
    if not sent_channels and not errors:
        result_parts.append('لم يتم إرسال أي تذكير — تأكد من وجود بيانات التواصل.')

    return '\n'.join(result_parts)

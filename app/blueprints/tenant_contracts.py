"""
app/blueprints/tenant_contracts.py — العقود الإلكترونية (/app/contracts/)

التاجر يدير:
- قوالب العقود (إنشاء/تعديل/حذف)
- العقود الموقّعة (عرض/تنزيل)
- ربط نظامه الخارجي (API)
"""
import io
import json
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, current_app, send_file

from app.extensions import db
from app.decorators import tenant_required, tenant_owner_required
from app.models.contract_template import ContractTemplate
from app.models.contract import Contract

bp = Blueprint('tenant_contracts', __name__, template_folder='../../templates/tenant')


# ========================================
# الصفحة الرئيسية
# ========================================
@bp.route('/')
@tenant_required
def index():
    """قائمة قوالب العقود + العقود الموقّعة."""
    tenant = g.current_tenant
    # الفنادق في النمط اليومي فقط: لا توجد عقود إلكترونية
    if (tenant.activity and tenant.activity.code == 'hotel'
            and not tenant.hotel_supports_contracts):
        flash(
            'العقود الإلكترونية متاحة فقط للنمط الشهري. '
            'لتفعيلها انتقل إلى «نمط الإيجار» واختر «شهري» أو «كلاهما».',
            'info',
        )
        return redirect(url_for('tenant_hotel.mode_settings'))

    templates = ContractTemplate.query.filter_by(tenant_id=tenant.id).order_by(
        ContractTemplate.created_at.desc()
    ).all()
    contracts = Contract.query.filter_by(tenant_id=tenant.id).order_by(
        Contract.created_at.desc()
    ).limit(20).all()

    counts = {
        'total': Contract.query.filter_by(tenant_id=tenant.id).count(),
        'pending': Contract.query.filter_by(tenant_id=tenant.id, status='pending_payment').count(),
        'awaiting': Contract.query.filter_by(tenant_id=tenant.id, status='awaiting_approval').count(),
        'sent': Contract.query.filter_by(tenant_id=tenant.id, status='sent').count(),
    }

    return render_template(
        'tenant/contracts/index.html',
        templates=templates,
        contracts=contracts,
        counts=counts,
    )


from flask_wtf import FlaskForm

class ManualContractForm(FlaskForm):
    pass

# ========================================
# إنشاء عقد يدوي (بدون بوت)
# ========================================
@bp.route('/manual/new', methods=['GET', 'POST'])
@tenant_owner_required
def new_manual():
    """إنشاء عقد يدوياً من قِبَل التاجر."""
    tenant = g.current_tenant
    from app.models.hotel_models import Unit
    from app.models.branch import Branch
    from app.services.contract_service import ContractService
    
    # نموذج لتمرير توكن CSRF بأمان
    form = ManualContractForm()
    
    # نجلب القوالب الخاصة بالعقود
    templates = ContractTemplate.query.filter_by(tenant_id=tenant.id, is_active=True).all()
    if not templates:
        flash('يجب إنشاء قالب عقد أولاً قبل التمكن من إنشاء العقود.', 'warning')
        return redirect(url_for('tenant_contracts.index'))

    branches = Branch.query.filter_by(tenant_id=tenant.id, is_active=True).all()
    branch_id = request.args.get('branch_id', type=int)

    # نجلب الوحدات المتاحة
    if branch_id:
        available_units = Unit.query.filter_by(tenant_id=tenant.id, branch_id=branch_id, status='available').all()
    else:
        available_units = []

    if request.method == 'POST':
        if not form.validate_on_submit():
            flash('انتهت صلاحية الجلسة أو حدث خطأ في التحقق (CSRF). يرجى المحاولة مرة أخرى.', 'danger')
            return redirect(request.url)

        template_id = request.form.get('template_id', type=int)
        unit_id = request.form.get('unit_id', type=int)
        customer_name = request.form.get('customer_name', '').strip()
        customer_phone = request.form.get('customer_phone', '').strip()
        
        tpl = ContractTemplate.query.filter_by(id=template_id, tenant_id=tenant.id).first()
        unit = Unit.query.filter_by(id=unit_id, tenant_id=tenant.id).first()
        
        if not tpl:
            flash('الرجاء اختيار قالب العقد.', 'danger')
            return redirect(request.url)
            
        if not customer_name or not customer_phone:
            flash('الرجاء إدخال بيانات العميل الأساسية.', 'danger')
            return redirect(request.url)

        if unit:
            if unit.status != 'available':
                flash(f'لا يمكن إنشاء العقد: هذه الوحدة غير متاحة حالياً (الحالة: {unit.status_label}).', 'danger')
                return redirect(request.url)

            # التحقق مما إذا كانت الوحدة مسجلة في عقد ساري
            active_contract = Contract.query.filter(
                Contract.unit_id == unit.id,
                Contract.status.in_(['draft', 'pending_payment', 'awaiting_approval', 'paid', 'signed', 'sent']),
                (Contract.expires_at.is_(None) | (Contract.expires_at > datetime.utcnow()))
            ).first()
            if active_contract:
                flash('هذه الوحدة مسجلة بالفعل في عقد ساري ولم ينتهي بعد.', 'danger')
                return redirect(request.url)

        try:
            # إنشاء العقد المبدئي
            contract = Contract(
                tenant_id=tenant.id,
                template_id=tpl.id,
                customer_name=customer_name,
                customer_phone=customer_phone,
                customer_email=request.form.get('customer_email', '').strip(),
                status='draft',
                payment_status='paid',
                payment_method=request.form.get('payment_method', 'cash')
            )
            db.session.add(contract)
            db.session.flush() # للحصول على الـ id
            contract.generate_contract_number()

            # جمع البيانات الأخرى من الفورم ووضعها في field_values
            field_values = {}
            for field in tpl.required_fields:
                key = field.get('key')
                if key:
                    val = request.form.get(key, '')
                    if val:
                        field_values[key] = val
            
            # إذا اختار وحدة نعكسها كبيانات افتراضية
            if unit:
                contract.unit_id = unit.id
                field_values['unit_id'] = str(unit.id)
                field_values['unit_name'] = unit.title or unit.unit_number
                
            contract.field_values = field_values
            
            # تحديد المبلغ
            contract.payment_amount = request.form.get('payment_amount', type=float, default=float(tpl.base_price or 0))
            contract.payment_paid = contract.payment_amount
            contract.paid_at = datetime.utcnow()

            # توليد العقد مباشرة
            contract.status = 'paid' # نفترض أنه دُفع أو أن التاجر أتم الإجراء يدوياً
            
            # -----------------
            # القيود المحاسبية
            # -----------------
            from app.services.accounting_service import create_journal_entry, seed_default_accounts
            from app.models.accounting import Account
            
            # التأكد من وجود الحسابات
            if Account.query.filter_by(tenant_id=tenant.id).count() == 0:
                seed_default_accounts(tenant.id)
                
            rev_acc = Account.query.filter_by(tenant_id=tenant.id, code='401').first()
            payment_method = request.form.get('payment_method', 'cash')
            credit_code = '101' if payment_method == 'cash' else '102'
            cash_acc = Account.query.filter_by(tenant_id=tenant.id, code=credit_code).first()
            
            if rev_acc and cash_acc and contract.payment_paid > 0:
                lines = [
                    {'account_id': cash_acc.id, 'debit': contract.payment_paid, 'credit': 0},
                    {'account_id': rev_acc.id, 'debit': 0, 'credit': contract.payment_paid}
                ]
                success, msg = create_journal_entry(
                    tenant_id=tenant.id,
                    description=f"إيراد إيجار للعميل {customer_name}",
                    reference_id=contract.contract_number,
                    reference_type="contract",
                    lines=lines
                )
                if not success:
                    db.session.rollback()
                    flash(f'فشل إنشاء القيد المحاسبي: {msg}', 'danger')
                    return redirect(request.url)
            else:
                db.session.rollback()
                flash('لم يتم العثور على الحسابات المطلوبة (الصندوق/البنك أو الإيرادات). تأكد من إعداد دليل الحسابات.', 'danger')
                return redirect(request.url)
                
            gen = ContractService.generate_contract(contract)
            
            if gen.get('success'):
                ContractService.send_to_customer(contract)
                db.session.commit()
                flash('✅ تم إنشاء العقد وإرساله للعميل بنجاح!', 'success')
                return redirect(url_for('tenant_contracts.contract_detail', id=contract.id))
            else:
                db.session.rollback()
                flash(f'حدث خطأ أثناء توليد العقد: {gen.get("error")}', 'danger')
                
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception(f'[contracts] Manual creation error: {e}')
            flash(f'حدث خطأ: {str(e)[:100]}', 'danger')

    return render_template(
        'tenant/contracts/new_manual.html',
        form=form,
        templates=templates,
        branches=branches,
        selected_branch_id=branch_id,
        available_units=available_units
    )


# ========================================
# قوالب — إنشاء/تعديل
# ========================================
@bp.route('/templates/new', methods=['GET', 'POST'])
@bp.route('/templates/<int:id>/edit', methods=['GET', 'POST'])
@tenant_owner_required
def template_form(id=None):
    """نموذج قالب عقد."""
    tenant = g.current_tenant
    tpl = None
    if id:
        tpl = ContractTemplate.query.filter_by(id=id, tenant_id=tenant.id).first_or_404()

    if request.method == 'POST':
        if not tpl:
            tpl = ContractTemplate(tenant_id=tenant.id)
            db.session.add(tpl)

        try:
            tpl.name = request.form.get('name', '').strip()
            tpl.contract_type = request.form.get('contract_type', 'monthly_rental')
            tpl.is_active = 'is_active' in request.form
            
            # بيانات المؤجر (الطرف الأول)
            tpl.lessor_name = request.form.get('lessor_name', '').strip()
            tpl.lessor_id_number = request.form.get('lessor_id_number', '').strip()
            tpl.lessor_phone = request.form.get('lessor_phone', '').strip()
            tpl.lessor_address = request.form.get('lessor_address', '').strip()
            
            # التذكير بالدفع
            tpl.reminder_message = request.form.get('reminder_message', '').strip()

            # ====== مصدر التوليد: internal أو external ======
            provider = request.form.get('provider', 'internal').strip().lower()
            if provider not in ('internal', 'external'):
                provider = 'internal'
            tpl.provider = provider

            if provider == 'internal':
                # قالب المنصة: شروط + ميزات + حقول البيانات فقط
                tpl.terms_text = request.form.get('terms_text', '').strip()
                tpl.features_text = request.form.get('features_text', '').strip()
                # نفرّغ بيانات API الخارجي
                tpl.external_api_url = ''
                tpl.external_api_auth = ''
            else:
                # نظام التاجر الخارجي: مفاتيح API فقط
                tpl.external_api_url = request.form.get('external_api_url', '').strip()
                tpl.external_api_method = request.form.get('external_api_method', 'POST')
                tpl.external_api_auth = request.form.get('external_api_auth', '').strip()
                headers_text = request.form.get('external_api_headers_json', '').strip()
                if headers_text:
                    try:
                        tpl.external_api_headers = json.loads(headers_text)
                    except json.JSONDecodeError:
                        flash('JSON الـ headers غير صالح', 'warning')

            # الحقول المطلوبة من العميل (مشتركة بين النوعين)
            fields_json = request.form.get('required_fields_json', '').strip()
            if fields_json:
                try:
                    tpl.required_fields = json.loads(fields_json)
                except json.JSONDecodeError:
                    flash('JSON الحقول غير صالح', 'warning')
            elif not tpl.required_fields:
                tpl.required_fields = ContractTemplate.default_fields_for_type(tpl.contract_type)

            db.session.commit()
            flash(f'✅ تم حفظ قالب "{tpl.name}"', 'success')
            return redirect(url_for('tenant_contracts.index'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'[contracts] template save error: {e}')
            flash(f'حدث خطأ: {str(e)[:100]}', 'danger')

    # GET أو خطأ POST: نعرض الفورم
    default_fields = []
    if not tpl or not tpl.required_fields:
        default_fields = ContractTemplate.default_fields_for_type(
            tpl.contract_type if tpl else 'monthly_rental'
        )

    return render_template(
        'tenant/contracts/template_form.html',
        template=tpl,
        default_fields=default_fields,
    )


@bp.route('/templates/<int:id>/delete', methods=['POST'])
@tenant_owner_required
def template_delete(id):
    tpl = ContractTemplate.query.filter_by(id=id, tenant_id=g.current_tenant.id).first_or_404()
    db.session.delete(tpl)
    db.session.commit()
    flash('تم حذف القالب', 'info')
    return redirect(url_for('tenant_contracts.index'))


@bp.route('/templates/<int:id>/toggle', methods=['POST'])
@tenant_owner_required
def template_toggle(id):
    tpl = ContractTemplate.query.filter_by(id=id, tenant_id=g.current_tenant.id).first_or_404()
    tpl.is_active = not tpl.is_active
    db.session.commit()
    flash(f'{"✅ تم تفعيل" if tpl.is_active else "⏸ تم تعطيل"} القالب', 'info')
    return redirect(url_for('tenant_contracts.index'))


# ========================================
# العقود — عرض التفاصيل
# ========================================
@bp.route('/contract/<int:id>')
@tenant_required
def contract_detail(id):
    contract = Contract.query.filter_by(id=id, tenant_id=g.current_tenant.id).first_or_404()
    return render_template('tenant/contracts/contract_detail.html', contract=contract)


@bp.route('/contract/<int:id>/preview')
@tenant_required
def contract_preview(id):
    """معاينة PDF للعقد (لا يرفع لـ Cloudinary، فقط للعرض)."""
    contract = Contract.query.filter_by(id=id, tenant_id=g.current_tenant.id).first_or_404()
    template = contract.template

    if not template:
        flash('قالب العقد غير موجود', 'danger')
        return redirect(url_for('tenant_contracts.contract_detail', id=id))

    from app.services.contract_service import ContractService
    try:
        pdf_bytes = ContractService._render_branded_pdf(contract, template)
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype='application/pdf',
            as_attachment=False,
            download_name=f'preview_{contract.contract_number or contract.id}.pdf',
        )
    except Exception as e:
        current_app.logger.exception(f'[contracts] preview error: {e}')
        flash(f'فشل توليد المعاينة: {str(e)[:120]}', 'danger')
        return redirect(url_for('tenant_contracts.contract_detail', id=id))


# ========================================
# تحويلات بنكية — قائمة بانتظار الموافقة
# ========================================
@bp.route('/transfers')
@tenant_required
def transfers_pending():
    """قائمة العقود التي تنتظر موافقة التاجر على التحويل البنكي."""
    contracts = Contract.query.filter_by(
        tenant_id=g.current_tenant.id,
        status='awaiting_approval',
    ).order_by(Contract.created_at.desc()).all()
    return render_template('tenant/contracts/transfers.html', contracts=contracts)


@bp.route('/contract/<int:id>/approve-transfer', methods=['POST'])
@tenant_owner_required
def contract_approve_transfer(id):
    """التاجر يوافق على التحويل البنكي → ينشأ العقد ويُرسل."""
    contract = Contract.query.filter_by(id=id, tenant_id=g.current_tenant.id).first_or_404()

    if contract.status != 'awaiting_approval':
        flash('العقد ليس بانتظار الموافقة', 'warning')
        return redirect(url_for('tenant_contracts.contract_detail', id=id))

    user = getattr(g, 'current_user', None)
    contract.bank_transfer_approved_by = user.id if user else None
    contract.bank_transfer_approved_at = datetime.utcnow()
    contract.payment_status = 'paid'
    contract.payment_paid = contract.payment_amount
    contract.paid_at = datetime.utcnow()
    contract.status = 'paid'

    # -----------------
    # القيود المحاسبية
    # -----------------
    from app.services.accounting_service import create_journal_entry, seed_default_accounts
    from app.models.accounting import Account
    
    if Account.query.filter_by(tenant_id=g.current_tenant.id).count() == 0:
        seed_default_accounts(g.current_tenant.id)
        
    rev_acc = Account.query.filter_by(tenant_id=g.current_tenant.id, code='401').first()
    bank_acc = Account.query.filter_by(tenant_id=g.current_tenant.id, code='102').first()
    
    if rev_acc and bank_acc and contract.payment_paid > 0:
        lines = [
            {'account_id': bank_acc.id, 'debit': contract.payment_paid, 'credit': 0},
            {'account_id': rev_acc.id, 'debit': 0, 'credit': contract.payment_paid}
        ]
        success, msg = create_journal_entry(
            tenant_id=g.current_tenant.id,
            description=f"إيراد إيجار تحويل بنكي للعقد {contract.contract_number or contract.id}",
            reference_id=str(contract.contract_number or contract.id),
            reference_type="contract",
            lines=lines
        )
        if not success:
            db.session.rollback()
            flash(f'فشل إنشاء القيد المحاسبي: {msg}', 'danger')
            return redirect(url_for('tenant_contracts.contract_detail', id=id))
    else:
        db.session.rollback()
        flash('لم يتم العثور على حسابات البنك أو الإيرادات. الرجاء مراجعة دليل الحسابات.', 'danger')
        return redirect(url_for('tenant_contracts.contract_detail', id=id))

    # توليد + إرسال
    from app.services.contract_service import ContractService
    gen = ContractService.generate_contract(contract)
    if gen.get('success'):
        ContractService.send_to_customer(contract)
        db.session.commit()
        flash('✅ تم التحقق والموافقة، وإرسال العقد للعميل', 'success')
    else:
        db.session.commit()
        flash(f'تمت الموافقة لكن فشل توليد العقد: {gen.get("error", "")}', 'warning')

    return redirect(url_for('tenant_contracts.contract_detail', id=id))


@bp.route('/contract/<int:id>/reject-transfer', methods=['POST'])
@tenant_owner_required
def contract_reject_transfer(id):
    """التاجر يرفض التحويل البنكي."""
    contract = Contract.query.filter_by(id=id, tenant_id=g.current_tenant.id).first_or_404()

    if contract.status != 'awaiting_approval':
        flash('العقد ليس بانتظار الموافقة', 'warning')
        return redirect(url_for('tenant_contracts.contract_detail', id=id))

    contract.bank_transfer_rejected_at = datetime.utcnow()
    contract.bank_transfer_note = (request.form.get('reason') or '').strip()[:500]
    contract.payment_status = 'pending'
    contract.status = 'rejected'
    
    # عكس أي قيود محاسبية مسجلة لهذا العقد إن وجدت
    from app.services.accounting_service import reverse_journal_entry
    reverse_journal_entry(
        tenant_id=g.current_tenant.id,
        original_reference_id=str(contract.contract_number or contract.id),
        original_reference_type="contract",
        reason="تم رفض التحويل البنكي"
    )
    
    db.session.commit()
    flash('تم رفض التحويل', 'info')
    return redirect(url_for('tenant_contracts.transfers_pending'))


@bp.route('/contract/<int:id>/regenerate', methods=['POST'])
@tenant_owner_required
def contract_regenerate(id):
    """إعادة توليد عقد."""
    contract = Contract.query.filter_by(id=id, tenant_id=g.current_tenant.id).first_or_404()

    from app.services.contract_service import ContractService
    result = ContractService.generate_contract(contract)

    if result.get('success'):
        db.session.commit()
        flash('✅ تم إعادة توليد العقد', 'success')
    else:
        flash(f'فشل التوليد: {result.get("error", "")}', 'danger')

    return redirect(url_for('tenant_contracts.contract_detail', id=id))


@bp.route('/contract/<int:id>/resend', methods=['POST'])
@tenant_owner_required
def contract_resend(id):
    """إعادة إرسال للعميل."""
    contract = Contract.query.filter_by(id=id, tenant_id=g.current_tenant.id).first_or_404()
    from app.services.contract_service import ContractService

    sent = ContractService.send_to_customer(contract)
    if sent:
        db.session.commit()
        flash('✅ تم إرسال العقد للعميل', 'success')
    else:
        flash('فشل الإرسال — تأكد من بيانات العميل', 'danger')

    return redirect(url_for('tenant_contracts.contract_detail', id=id))

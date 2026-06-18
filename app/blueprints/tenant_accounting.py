"""
app/blueprints/tenant_accounting.py — نظام القيود المحاسبية
"""
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, g

from app.extensions import db
from app.decorators import tenant_required, tenant_owner_required
from app.models.accounting import Account, JournalEntry, JournalEntryLine, Expense
from app.services.accounting_service import create_journal_entry, seed_default_accounts

bp = Blueprint('tenant_accounting', __name__, template_folder='../../templates/tenant/accounting')

@bp.route('/')
@tenant_required
def dashboard():
    """لوحة التحكم المحاسبية واستعراض القيود."""
    tenant = g.current_tenant
    
    accounts_count = Account.query.filter_by(tenant_id=tenant.id).count()
    if accounts_count == 0:
        seed_default_accounts(tenant.id)
        
    entries = JournalEntry.query.filter_by(tenant_id=tenant.id).order_by(JournalEntry.created_at.desc()).limit(50).all()
    accounts = Account.query.filter_by(tenant_id=tenant.id).all()
    
    return render_template('tenant/accounting/dashboard.html', entries=entries, accounts=accounts)

@bp.route('/expenses')
@tenant_required
def list_expenses():
    """استعراض المصروفات التشغيلية."""
    tenant = g.current_tenant
    expenses = Expense.query.filter_by(tenant_id=tenant.id).order_by(Expense.created_at.desc()).all()
    return render_template('tenant/accounting/expenses.html', expenses=expenses)

@bp.route('/expenses/new', methods=['GET', 'POST'])
@tenant_owner_required
def new_expense():
    """تسجيل مصروف جديد وتوليد قيد تلقائي."""
    tenant = g.current_tenant
    
    if request.method == 'POST':
        amount = request.form.get('amount', type=float, default=0.0)
        description = request.form.get('description', '').strip()
        category = request.form.get('category', 'general')
        payment_method = request.form.get('payment_method', 'cash') # cash -> 101, bank -> 102
        
        if amount <= 0 or not description:
            flash('الرجاء إدخال مبلغ صحيح وبيان واضح للمصروف.', 'warning')
            return redirect(request.url)
            
        expense = Expense(
            tenant_id=tenant.id,
            amount=amount,
            description=description,
            category=category,
            created_by=g.current_user.full_name or g.current_user.username
        )
        db.session.add(expense)
        db.session.commit() # للحصول على expense.id للربط
        
        # تجهيز القيد المحاسبي
        # حساب المصروف
        exp_acc = Account.query.filter_by(tenant_id=tenant.id, code='501').first()
        # حساب الدفع
        credit_code = '101' if payment_method == 'cash' else '102'
        cash_acc = Account.query.filter_by(tenant_id=tenant.id, code=credit_code).first()
        
        if exp_acc and cash_acc:
            lines = [
                {'account_id': exp_acc.id, 'debit': amount, 'credit': 0},
                {'account_id': cash_acc.id, 'debit': 0, 'credit': amount}
            ]
            success, msg = create_journal_entry(
                tenant_id=tenant.id,
                description=f"تسجيل مصروف: {description}",
                reference_id=str(expense.id),
                reference_type="expense",
                lines=lines
            )
            if success:
                flash('✅ تم تسجيل المصروف وتوليد القيد المحاسبي بنجاح.', 'success')
            else:
                flash(f'تم حفظ المصروف لكن فشل توليد القيد: {msg}', 'warning')
        else:
            flash('تم حفظ المصروف لكن لم نتمكن من توليد القيد لعدم توفر الحسابات الأساسية.', 'warning')
            
        return redirect(url_for('tenant_accounting.list_expenses'))
        
    return render_template('tenant/accounting/new_expense.html')

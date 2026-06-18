"""
app/services/accounting_service.py — الخدمات الخاصة بالقيود المحاسبية
"""
from typing import List, Dict
from sqlalchemy.exc import SQLAlchemyError
from ..extensions import db
from ..models import Account, JournalEntry, JournalEntryLine

def seed_default_accounts(tenant_id: int):
    """
    توليد الحسابات الافتراضية لأي مشترك (Tenant) جديد إذا لم تكن موجودة.
    """
    default_accounts = [
        {'name': 'الصندوق', 'account_type': 'asset', 'code': '101'},
        {'name': 'البنك', 'account_type': 'asset', 'code': '102'},
        {'name': 'إيرادات الإيجار', 'account_type': 'revenue', 'code': '401'},
        {'name': 'المصاريف التشغيلية', 'account_type': 'expense', 'code': '501'},
    ]
    
    for acc in default_accounts:
        existing = Account.query.filter_by(tenant_id=tenant_id, code=acc['code']).first()
        if not existing:
            new_account = Account(
                tenant_id=tenant_id,
                name=acc['name'],
                account_type=acc['account_type'],
                code=acc['code']
            )
            db.session.add(new_account)
    
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()


def create_journal_entry(tenant_id: int, description: str, reference_id: str, reference_type: str, lines: List[Dict]):
    """
    إنشاء قيد محاسبي متزن.
    lines: قائمة من القواميس بصيغة [{'account_id': 1, 'debit': 100, 'credit': 0}, ...]
    """
    if not lines or len(lines) < 2:
        return False, "القيد يجب أن يحتوي على سطرين على الأقل."

    total_debit = sum(float(line.get('debit', 0)) for line in lines)
    total_credit = sum(float(line.get('credit', 0)) for line in lines)

    if round(total_debit, 2) != round(total_credit, 2):
        return False, f"القيد غير متزن: مجموع المدين ({total_debit}) لا يساوي مجموع الدائن ({total_credit})."

    if total_debit <= 0:
        return False, "يجب أن تكون قيمة القيد أكبر من صفر."

    try:
        # إنشاء رأس القيد
        entry = JournalEntry(
            tenant_id=tenant_id,
            description=description,
            reference_id=str(reference_id) if reference_id else None,
            reference_type=reference_type
        )
        db.session.add(entry)
        db.session.flush() # للحصول على entry.id

        # إنشاء أسطر القيد
        for line in lines:
            entry_line = JournalEntryLine(
                journal_entry_id=entry.id,
                account_id=line['account_id'],
                debit=line.get('debit', 0),
                credit=line.get('credit', 0)
            )
            db.session.add(entry_line)

        db.session.flush() # فقط flush بدلاً من commit لضمان ذرية العمليات (Atomicity)
        return True, "تم إنشاء القيد المحاسبي بنجاح."

    except SQLAlchemyError as e:
        # لا نقوم بعمل rollback هنا لنسمح للموجه بالتعامل مع الخطأ
        return False, f"خطأ في قاعدة البيانات أثناء إنشاء القيد: {str(e)}"

def reverse_journal_entry(tenant_id: int, original_reference_id: str, original_reference_type: str, reason: str):
    """
    إلغاء قيد محاسبي عبر إنشاء قيد عكسي.
    """
    original_entries = JournalEntry.query.filter_by(
        tenant_id=tenant_id, 
        reference_id=str(original_reference_id), 
        reference_type=original_reference_type
    ).all()
    
    if not original_entries:
        return False, "لم يتم العثور على القيد الأصلي لعكسه."
        
    for original_entry in original_entries:
        if "عكس قيد" in original_entry.description:
            continue # لا تعكس قيداً عكسياً
            
        lines = []
        for line in original_entry.lines:
            # نعكس المدين والدائن
            lines.append({
                'account_id': line.account_id,
                'debit': line.credit,
                'credit': line.debit
            })
            
        success, msg = create_journal_entry(
            tenant_id=tenant_id,
            description=f"عكس قيد: {original_entry.description} - السبب: {reason}",
            reference_id=str(original_reference_id),
            reference_type=f"{original_reference_type}_reversal",
            lines=lines
        )
        if not success:
            return False, f"فشل في عكس القيد: {msg}"
            
    return True, "تم عكس القيد المحاسبي بنجاح."

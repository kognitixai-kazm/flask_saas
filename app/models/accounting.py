"""
app/models/accounting.py — نظام القيود المحاسبية الآلية والمصروفات
"""
from datetime import datetime
from ..extensions import db

class Account(db.Model):
    """دليل الحسابات المبسط (لكل فندق/مشترك)."""
    __tablename__ = 'accounts'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    
    name = db.Column(db.String(100), nullable=False)
    # asset (أصول: كالصندوق/البنك), liability (خصوم), equity (حقوق ملكية), revenue (إيرادات), expense (مصروفات)
    account_type = db.Column(db.String(50), nullable=False)
    code = db.Column(db.String(50), default='')
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Account {self.name} ({self.account_type})>'


class JournalEntry(db.Model):
    """رأس القيد المحاسبي."""
    __tablename__ = 'journal_entries'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    
    description = db.Column(db.String(255), nullable=False)
    # المرجع: رقم الحجز أو رقم فاتورة المصروف، للرجوع للعملية الأساسية
    reference_id = db.Column(db.String(100), nullable=True)
    # نوع المرجع: booking, expense, contract
    reference_type = db.Column(db.String(50), nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # العلاقة مع أسطر القيد
    lines = db.relationship('JournalEntryLine', backref='journal_entry', lazy='dynamic', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<JournalEntry {self.id} ref={self.reference_id}>'


class JournalEntryLine(db.Model):
    """سطر القيد المحاسبي (مدين / دائن)."""
    __tablename__ = 'journal_entry_lines'

    id = db.Column(db.Integer, primary_key=True)
    journal_entry_id = db.Column(db.Integer, db.ForeignKey('journal_entries.id'), nullable=False, index=True)
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=False)
    
    debit = db.Column(db.Numeric(10, 2), default=0)
    credit = db.Column(db.Numeric(10, 2), default=0)

    # العلاقة مع الحساب
    account = db.relationship('Account')

    def __repr__(self):
        return f'<JournalEntryLine Acc={self.account_id} Dr={self.debit} Cr={self.credit}>'


class Expense(db.Model):
    """المصروفات التشغيلية للمنشأة."""
    __tablename__ = 'expenses'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    category = db.Column(db.String(100), default='general') # نوع المصروف: كهرباء، ماء، صيانة..
    expense_date = db.Column(db.Date, default=datetime.utcnow)
    
    # للإشارة لمن قام بإدخال المصروف
    created_by = db.Column(db.String(100), default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Expense {self.amount} - {self.description}>'

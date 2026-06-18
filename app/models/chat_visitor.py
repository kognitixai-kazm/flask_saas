"""
app/models/chat_visitor.py — زوار الشات المسجلين.

✅ تحديثات الأمان (المرحلة 1.5 - ثغرة #10):
- verification_code يُخزَّن كـ hash بدلاً من نص خام
- verification_salt للتشفير الآمن
- verification_attempts عداد محاولات (حد أقصى 5)
"""
from datetime import datetime
from ..extensions import db


class ChatVisitor(db.Model):
    """زائر مسجّل في شات tenant معين."""
    __tablename__ = 'chat_visitors'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)

    name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(255), nullable=False, index=True)
    phone = db.Column(db.String(30), default='')

    # session identifier
    visitor_token = db.Column(db.String(64), unique=True, index=True)

    # التحقق بالبريد — مشفّر
    is_verified = db.Column(db.Boolean, default=False)
    verification_code_hash = db.Column(db.String(64), default='')  # SHA256 hex
    verification_salt = db.Column(db.String(32), default='')
    verification_expires = db.Column(db.DateTime, nullable=True)
    verification_attempts = db.Column(db.Integer, default=0)
    verification_locked_until = db.Column(db.DateTime, nullable=True)

    # العمود القديم — يُبقى للتوافق ولكن يُهمَل
    verification_code = db.Column(db.String(6), default='')

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'email', name='uq_tenant_visitor_email'),
    )

    MAX_VERIFICATION_ATTEMPTS = 5  # حد المحاولات قبل القفل

    def set_verification_code(self, code: str):
        """تخزين رمز التحقق مشفّراً."""
        from app.utils.security import hash_otp
        hashed, salt = hash_otp(code)
        self.verification_code_hash = hashed
        self.verification_salt = salt
        self.verification_attempts = 0
        self.verification_locked_until = None
        # تنظيف العمود القديم
        self.verification_code = ''

    def check_verification_code(self, code_input: str) -> tuple:
        """
        التحقق من رمز الإدخال.

        Returns:
            (success: bool, message: str)
        """
        from app.utils.security import verify_otp

        # هل القفل لا يزال ساري؟
        if self.verification_locked_until and datetime.utcnow() < self.verification_locked_until:
            remaining = (self.verification_locked_until - datetime.utcnow()).seconds // 60
            return False, f'تم قفل المحاولات. حاول بعد {remaining} دقيقة'

        # هل انتهت صلاحية الرمز؟
        if not self.verification_expires or datetime.utcnow() > self.verification_expires:
            return False, 'انتهت صلاحية الرمز. يرجى طلب رمز جديد'

        # تحقق من الـ hash
        if not self.verification_code_hash or not self.verification_salt:
            return False, 'لم يُرسل رمز تحقق. اطلب رمزاً أولاً'

        if verify_otp(code_input, self.verification_code_hash, self.verification_salt):
            # ✅ صحيح — تنظيف
            self.is_verified = True
            self.verification_code_hash = ''
            self.verification_salt = ''
            self.verification_code = ''
            self.verification_attempts = 0
            self.verification_locked_until = None
            return True, 'تم التحقق'

        # ❌ خطأ — زيادة المحاولات
        self.verification_attempts = (self.verification_attempts or 0) + 1
        attempts_left = self.MAX_VERIFICATION_ATTEMPTS - self.verification_attempts

        if self.verification_attempts >= self.MAX_VERIFICATION_ATTEMPTS:
            # قفل لمدة 30 دقيقة
            from datetime import timedelta
            self.verification_locked_until = datetime.utcnow() + timedelta(minutes=30)
            return False, 'تم قفل المحاولات لمدة 30 دقيقة بسبب كثرة المحاولات الخاطئة'

        return False, f'رمز خاطئ. محاولات متبقية: {attempts_left}'

    def __repr__(self):
        return f'<ChatVisitor {self.email} tenant={self.tenant_id}>'

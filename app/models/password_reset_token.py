"""رمز لمرة واحدة لإعادة تعيين كلمة المرور (سوبر أدمن أو مستخدم نشاط)."""
from datetime import datetime

from ..extensions import db


class PasswordResetToken(db.Model):
    __tablename__ = 'password_reset_tokens'

    id = db.Column(db.Integer, primary_key=True)
    # super_admin | tenant_user
    purpose = db.Column(db.String(20), nullable=False, index=True)
    subject_id = db.Column(db.Integer, nullable=False, index=True)
    token_hash = db.Column(db.String(128), nullable=False, index=True)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    used_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

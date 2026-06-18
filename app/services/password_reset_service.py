"""إصدار والتحقق من رموز إعادة تعيين كلمة المرور."""
from __future__ import annotations

import hmac
import hashlib
import secrets
from datetime import datetime, timedelta

from flask import current_app

from app.extensions import db
from app.models.password_reset_token import PasswordResetToken

PURPOSE_SUPER_ADMIN = 'super_admin'
PURPOSE_TENANT_USER = 'tenant_user'

TOKEN_TTL_MINUTES = 60


def _hash_token(raw: str) -> str:
    secret = (current_app.config.get('SECRET_KEY') or '').encode()
    return hmac.new(secret, (raw or '').encode('utf-8'), hashlib.sha256).hexdigest()


def issue_token(purpose: str, subject_id: int) -> str:
    """يُبطل الرموز السابقة غير المستخدمة لنفس الجهة، ويُنشئ رمزاً جديداً ويعيد النص الصريح."""
    PasswordResetToken.query.filter_by(
        purpose=purpose, subject_id=subject_id, used_at=None
    ).delete(synchronize_session=False)
    raw = secrets.token_urlsafe(32)
    row = PasswordResetToken(
        purpose=purpose,
        subject_id=subject_id,
        token_hash=_hash_token(raw),
        expires_at=datetime.utcnow() + timedelta(minutes=TOKEN_TTL_MINUTES),
    )
    db.session.add(row)
    db.session.commit()
    return raw


def find_valid_token(purpose: str, raw: str) -> PasswordResetToken | None:
    if not raw or len(raw) < 10:
        return None
    h = _hash_token(raw.strip())
    row = PasswordResetToken.query.filter_by(
        purpose=purpose, token_hash=h, used_at=None
    ).first()
    if not row or row.expires_at < datetime.utcnow():
        return None
    return row


def revoke_all_for_subject(purpose: str, subject_id: int) -> None:
    PasswordResetToken.query.filter_by(purpose=purpose, subject_id=subject_id).delete(
        synchronize_session=False
    )
    db.session.commit()

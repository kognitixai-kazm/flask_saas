"""
app/utils/passwords.py — تشفير وتحقق كلمات المرور (argon2)
"""
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError

_ph = PasswordHasher(
    time_cost=2,
    memory_cost=65536,
    parallelism=1,
)


def hash_password(plain: str) -> str:
    """تشفير كلمة المرور."""
    return _ph.hash(plain)


def verify_password(password_hash: str, plain: str) -> bool:
    """مقارنة كلمة المرور مع الهاش المحفوظ."""
    try:
        return _ph.verify(password_hash, plain)
    except (VerifyMismatchError, VerificationError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """هل الهاش يحتاج إعادة تشفير (لأن الإعدادات تغيّرت)."""
    return _ph.check_needs_rehash(password_hash)

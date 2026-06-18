"""
app/utils/security.py — دوال التحقق الأمني المركزية.

تشمل:
- verify_meta_signature: التحقق من توقيع Meta لـ webhook WhatsApp
- verify_moyasar_signature: التحقق من Moyasar
- verify_tap_signature: التحقق من Tap
- hash_otp / verify_otp: تشفير ومقارنة رموز التحقق
- check_production_safety: فحص القيم الافتراضية الخطرة
"""
import hmac
import hashlib
import secrets
from typing import Optional

# ========================================
# 1. WhatsApp / Meta — X-Hub-Signature-256
# ========================================
def verify_meta_signature(
    request_body: bytes,
    received_signature: str,
    app_secret: str,
) -> bool:
    """
    التحقق من توقيع Meta على الـ webhook.

    الترويسة المتوقّعة: X-Hub-Signature-256: sha256=<hex>

    Args:
        request_body: raw bytes من request.get_data()
        received_signature: قيمة الترويسة كاملة
        app_secret: App Secret من Meta Developer Dashboard

    Returns:
        True إذا التوقيع صحيح، False خلاف ذلك
    """
    if not app_secret or not received_signature:
        return False

    # الترويسة بصيغة "sha256=<hex>"
    if not received_signature.startswith('sha256='):
        return False

    received_hex = received_signature.split('=', 1)[1]

    # حساب التوقيع المتوقّع
    expected_hex = hmac.new(
        app_secret.encode('utf-8'),
        request_body,
        hashlib.sha256,
    ).hexdigest()

    # المقارنة الآمنة (ضد timing attacks)
    return hmac.compare_digest(received_hex, expected_hex)


# ========================================
# 2. Moyasar — webhook signature
# ========================================
def verify_moyasar_signature(
    request_body: bytes,
    received_signature: str,
    secret_token: str,
) -> bool:
    """
    التحقق من توقيع Moyasar.

    Moyasar يرسل ترويسة X-Moyasar-Signature
    التوقيع = HMAC SHA256 من body باستخدام secret_token

    Args:
        request_body: raw bytes
        received_signature: قيمة الترويسة (hex مباشرة بدون prefix)
        secret_token: Webhook Secret من dashboard Moyasar

    Returns:
        True إذا التوقيع صحيح
    """
    if not secret_token or not received_signature:
        return False

    expected_hex = hmac.new(
        secret_token.encode('utf-8'),
        request_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(received_signature.strip(), expected_hex)


# ========================================
# 3. Tap Payments — webhook signature
# ========================================
def verify_tap_signature(
    request_body: bytes,
    received_signature: str,
    secret_key: str,
) -> bool:
    """
    التحقق من توقيع Tap Payments.

    Tap يرسل hashstring في الترويسة، وبيانات معيّنة من body
    تُجمع وتُحسب HMAC SHA256.

    لاستخدام مبسّط: نتحقق من HMAC على body كاملاً.
    """
    if not secret_key or not received_signature:
        return False

    expected_hex = hmac.new(
        secret_key.encode('utf-8'),
        request_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(received_signature.strip(), expected_hex)


# ========================================
# 4. OTP — تشفير رموز التحقق
# ========================================
def hash_otp(otp: str, salt: Optional[str] = None) -> tuple:
    """
    تشفير رمز التحقق بـ SHA256 + salt.

    Args:
        otp: الرمز الأصلي (مثل "123456")
        salt: salt اختياري — لو None يُولَّد تلقائياً

    Returns:
        (hashed_hex, salt_hex)
    """
    if salt is None:
        salt = secrets.token_hex(16)

    combined = (otp + salt).encode('utf-8')
    hashed = hashlib.sha256(combined).hexdigest()
    return hashed, salt


def verify_otp(otp_input: str, stored_hash: str, salt: str) -> bool:
    """
    مقارنة رمز التحقق المُدخَل مع المخزّن.

    Args:
        otp_input: ما أدخله المستخدم
        stored_hash: الـ hash المخزّن في DB
        salt: الـ salt المخزّن

    Returns:
        True إذا متطابقين
    """
    if not otp_input or not stored_hash or not salt:
        return False

    computed_hash, _ = hash_otp(otp_input, salt)
    return hmac.compare_digest(computed_hash, stored_hash)


# ========================================
# 5. فحص الإنتاج — قيم افتراضية خطرة
# ========================================
DEFAULT_INSECURE_VALUES = {
    'SECRET_KEY': {
        'dev-secret-key-CHANGE-THIS',
        'change-me',
        'secret',
        'CHANGE_ME',
    },
    'SUPER_ADMIN_PASSWORD': {
        'admin123',
        'admin',
        'password',
        '123456',
        'CHANGE_ME',
    },
}


def check_production_safety(config: dict) -> list:
    """
    فحص الإعدادات قبل التشغيل في الإنتاج.

    Returns:
        قائمة بالمشاكل الأمنية المكتشفة
    """
    issues = []

    # فحص SECRET_KEY
    secret = config.get('SECRET_KEY', '')
    if not secret or len(secret) < 32:
        issues.append('SECRET_KEY قصير جداً أو فارغ — يجب 32 حرف على الأقل')
    elif secret in DEFAULT_INSECURE_VALUES['SECRET_KEY']:
        issues.append('SECRET_KEY قيمة افتراضية خطرة — يجب تغييره')

    # فحص كلمة مرور السوبر أدمن
    sa_pass = config.get('SUPER_ADMIN_PASSWORD', '')
    if sa_pass in DEFAULT_INSECURE_VALUES['SUPER_ADMIN_PASSWORD']:
        issues.append('SUPER_ADMIN_PASSWORD قيمة افتراضية خطرة')

    # فحص DEBUG
    if config.get('DEBUG'):
        issues.append('DEBUG مفعّل — يجب إيقافه في الإنتاج')

    # فحص وضع flask-debugtoolbar
    if config.get('DEBUG_TB_ENABLED'):
        issues.append('flask-debugtoolbar مفعّل — يجب إيقافه في الإنتاج')

    return issues


def generate_secure_secret(length: int = 64) -> str:
    """توليد SECRET_KEY آمن."""
    return secrets.token_urlsafe(length)

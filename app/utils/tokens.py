"""
app/utils/tokens.py — Setup Tokens (للإعداد الأولي للحساب)
Token صالح لمرة واحدة + ينتهي بعد 24 ساعة (حسب الخطة)
"""
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from flask import current_app


class SetupTokenManager:
    """مدير توليد وتحقق tokens الإعداد."""

    SALT = 'tenant-setup-v1'

    @classmethod
    def _serializer(cls):
        return URLSafeTimedSerializer(current_app.config['SECRET_KEY'])

    @classmethod
    def generate(cls, tenant_id: int) -> str:
        """توليد token لـ tenant معين."""
        return cls._serializer().dumps({'tenant_id': tenant_id}, salt=cls.SALT)

    @classmethod
    def verify(cls, token: str, max_age_hours: int = None) -> int | None:
        """
        التحقق من token وإرجاع tenant_id إن كان صالحاً.
        يرجع None إذا انتهى أو غير صالح.
        """
        if max_age_hours is None:
            max_age_hours = current_app.config.get('SETUP_TOKEN_EXPIRY_HOURS', 24)

        try:
            data = cls._serializer().loads(
                token,
                salt=cls.SALT,
                max_age=max_age_hours * 3600,
            )
            return data.get('tenant_id')
        except SignatureExpired:
            current_app.logger.info(f'Expired setup token attempt')
            return None
        except BadSignature:
            current_app.logger.warning(f'Invalid setup token attempt')
            return None

    @classmethod
    def build_setup_url(cls, tenant_id: int) -> str:
        """بناء رابط الإعداد الكامل."""
        token = cls.generate(tenant_id)
        site_url = current_app.config['SITE_URL'].rstrip('/')
        return f"{site_url}/app/setup?token={token}"

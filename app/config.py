"""
app/config.py — إعدادات التطبيق حسب البيئة (development/production/testing)
"""
import os
from datetime import timedelta
from pathlib import Path
from dotenv import load_dotenv

# تحميل .env
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')


class BaseConfig:
    """الإعدادات المشتركة بين كل البيئات."""

    # ============================================
    # المسارات
    # ============================================
    BASE_DIR = BASE_DIR
    UPLOAD_FOLDER = BASE_DIR / 'static' / 'uploads'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB upload limit

    # ============================================
    # الأمان
    # ============================================
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-change-me')

    # Password hashing
    PASSWORD_HASH_METHOD = 'argon2'

    # CSRF
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600  # ساعة واحدة

    # Cookies الافتراضية (عامة، كل عالم يعدّل على خصائصه)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = False  # True في الإنتاج مع HTTPS

    # ============================================
    # 3 Sessions منفصلة (تطبيق فصل العوالم)
    # كل عالم له cookie منفصل + path منفصل
    # ============================================
    SESSIONS = {
        'super_admin': {
            'cookie_name': 'sa_session',
            'cookie_path': '/sa',
            'lifetime': timedelta(hours=2),
            'secure_key': 'sa_user_id',
        },
        'tenant': {
            'cookie_name': 'tenant_session',
            'cookie_path': '/app',
            'lifetime': timedelta(days=7),
            'secure_key': 'tenant_user_id',
        },
        'chat_visitor': {
            'cookie_name': 'chat_visitor',
            'cookie_path': '/c',
            'lifetime': timedelta(days=365),
            'secure_key': 'visitor_id',
        },
    }

    # ============================================
    # قاعدة البيانات
    # ============================================
    SQLALCHEMY_DATABASE_URI = os.getenv(
        'DATABASE_URL',
        'postgresql://saas_user:saas_password@localhost:5432/saas_db'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = False

    # ============================================
    # Redis (للجلسات + Rate Limiting)
    # ============================================
    REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')

    # ============================================
    # Session Storage
    # ============================================
    SESSION_TYPE = os.getenv('SESSION_TYPE', 'filesystem')
    SESSION_PERMANENT = False
    SESSION_USE_SIGNER = True
    SESSION_FILE_DIR = str(BASE_DIR / 'instance' / 'flask_session')

    # ============================================
    # Rate Limiting
    # ============================================
    RATELIMIT_STORAGE_URI = os.getenv('RATELIMIT_STORAGE_URI', 'memory://')
    RATELIMIT_DEFAULT = '200 per hour'
    RATELIMIT_HEADERS_ENABLED = True

    # ============================================
    # Site Info
    # ============================================
    SITE_URL = os.getenv('SITE_URL', 'http://localhost:5000')
    SITE_NAME = os.getenv('SITE_NAME', 'KOGNITIX')

    # ============================================
    # Super Admin (للإنشاء الأولي)
    # ============================================
    SUPER_ADMIN_USERNAME = os.getenv('SUPER_ADMIN_USERNAME', 'superadmin')
    SUPER_ADMIN_EMAIL = os.getenv('SUPER_ADMIN_EMAIL', 'admin@localhost')
    SUPER_ADMIN_PASSWORD = os.getenv('SUPER_ADMIN_PASSWORD', 'admin123')

    # ============================================
    # AI Providers (قابل للتبديل)
    # ============================================
    # openai | anthropic | google_gemini | mistral
    AI_PROVIDER = os.getenv('AI_PROVIDER', 'openai')

    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
    OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')

    ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY', '')
    ANTHROPIC_MODEL = os.getenv('ANTHROPIC_MODEL', 'claude-3-5-sonnet-20241022')

    GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY', '')
    GOOGLE_AI_MODEL = os.getenv('GOOGLE_AI_MODEL', 'gemini-2.0-flash')

    MISTRAL_API_KEY = os.getenv('MISTRAL_API_KEY', '')
    MISTRAL_MODEL = os.getenv('MISTRAL_MODEL', 'mistral-small-latest')

    # ============================================
    # WhatsApp (المرحلة 7)
    # ============================================
    WHATSAPP_ENABLED = os.getenv('WHATSAPP_ENABLED', 'False') == 'True'
    WHATSAPP_API_URL = os.getenv('WHATSAPP_API_URL', '')
    WHATSAPP_TOKEN = os.getenv('WHATSAPP_TOKEN', '')
    WHATSAPP_PHONE_ID = os.getenv('WHATSAPP_PHONE_ID', '')
    WHATSAPP_VERIFY_TOKEN = os.getenv('WHATSAPP_VERIFY_TOKEN', '')

    # ============================================
    # Email (للمرحلة 8 - حالياً يُطبع في الـ log)
    # ============================================
    MAIL_ENABLED = os.getenv('MAIL_ENABLED', 'False') == 'True'
    MAIL_SERVER = os.getenv('MAIL_SERVER', 'localhost')
    MAIL_PORT = int(os.getenv('MAIL_PORT', 587))
    MAIL_USE_TLS = os.getenv('MAIL_USE_TLS', 'True') == 'True'
    MAIL_USERNAME = os.getenv('MAIL_USERNAME', '')
    MAIL_PASSWORD = os.getenv('MAIL_PASSWORD', '')
    MAIL_DEFAULT_SENDER = os.getenv('MAIL_DEFAULT_SENDER', 'noreply@localhost')

    # ============================================
    # Setup Token (لإعداد حساب العميل)
    # ============================================
    SETUP_TOKEN_EXPIRY_HOURS = 24

    # ============================================
    # Chat
    # ============================================
    CHAT_HISTORY_LIMIT = 20  # عدد الرسائل المحفوظة في context الـ AI

    # ============================================
    # Web Push Notifications (VAPID Keys)
    # ============================================
    VAPID_PRIVATE_KEY = os.getenv('VAPID_PRIVATE_KEY', '')
    VAPID_PUBLIC_KEY = os.getenv('VAPID_PUBLIC_KEY', '')
    VAPID_CLAIMS_EMAIL = os.getenv('VAPID_CLAIMS_EMAIL', os.getenv('MAIL_DEFAULT_SENDER', 'admin@kognitixai.com'))


class DevelopmentConfig(BaseConfig):
    """بيئة التطوير."""
    DEBUG = True
    TESTING = False
    SQLALCHEMY_ECHO = False


class ProductionConfig(BaseConfig):
    """بيئة الإنتاج."""
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True  # HTTPS فقط
    WTF_CSRF_SSL_STRICT = True
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 20,
        'pool_recycle': 3600,
        'pool_pre_ping': True,
        'max_overflow': 10,
    }


class TestingConfig(BaseConfig):
    """بيئة الاختبارات."""
    TESTING = True
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


# خريطة الإعدادات
config_map = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig,
}


def get_config(env='development'):
    """إرجاع class الإعدادات حسب اسم البيئة."""
    return config_map.get(env, DevelopmentConfig)

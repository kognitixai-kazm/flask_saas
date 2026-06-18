"""
app/extensions.py — تعريف امتدادات Flask (يتم ربطها بالتطبيق في factory)
"""
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_session import Session

# قاعدة البيانات
db = SQLAlchemy()

# Migrations
migrate = Migrate()

# CSRF
csrf = CSRFProtect()

# Rate Limiter
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=['200 per hour'],
    storage_uri='memory://',  # يُعاد ضبطه في factory من config
)

# Session
sess = Session()

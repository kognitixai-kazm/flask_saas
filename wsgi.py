"""
wsgi.py — نقطة دخول Gunicorn للإنتاج
الاستخدام:
    gunicorn wsgi:app -w 4 -b 0.0.0.0:8000
"""
import os
from app import create_app

app = create_app(os.getenv('FLASK_ENV', 'production'))

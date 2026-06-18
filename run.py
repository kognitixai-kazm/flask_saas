"""
run.py — نقطة تشغيل التطبيق
الاستخدام:
    python run.py          # تشغيل للتطوير
    flask run              # بديل
    gunicorn run:app       # للإنتاج
"""
import os
from app import create_app

# إنشاء التطبيق حسب البيئة
config_name = os.getenv('FLASK_ENV', 'development')
app = create_app(config_name)


if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=int(os.getenv('PORT', 5000)),
        debug=app.config.get('DEBUG', False)
    )

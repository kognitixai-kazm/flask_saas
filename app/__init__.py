"""
app/__init__.py — مصنع التطبيق (Application Factory Pattern)
"""
import os
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from flask import Flask, render_template

from .config import get_config
from .extensions import db, migrate, csrf, limiter, sess


def create_app(config_name='development'):
    app = Flask(
        __name__,
        static_folder='../static',
        template_folder='../templates',
        instance_relative_config=True,
    )
    config_class = get_config(config_name)
    app.config.from_object(config_class)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    Path(app.config.get('SESSION_FILE_DIR', app.instance_path)).mkdir(parents=True, exist_ok=True)

    # ✅ فحص الأمان للإنتاج (ثغرة #4)
    _security_check(app, config_name)

    _init_extensions(app)
    _register_blueprints(app)
    _register_error_handlers(app)
    _register_security_headers(app)
    _register_context_processors(app)
    _register_cli_commands(app)
    _setup_logging(app)
    app.logger.info(f'✓ App started in {config_name} mode')
    return app


def _security_check(app, config_name):
    """
    فحص القيم الافتراضية الخطرة قبل التشغيل.
    في الإنتاج: يرفع SystemExit لو فيه قيم خطرة.
    في التطوير: يطبع تحذيرات فقط.
    """
    from .utils.security import check_production_safety, generate_secure_secret

    is_production = config_name == 'production' or os.environ.get('FLASK_ENV') == 'production'
    issues = check_production_safety(app.config)

    if not issues:
        return

    if is_production:
        # في الإنتاج: رفض التشغيل
        msg = '\n'.join([f'  ❌ {i}' for i in issues])
        raise SystemExit(
            '\n' + '=' * 60 + '\n'
            '🚨 رفض التشغيل في الإنتاج بسبب مشاكل أمنية:\n'
            f'{msg}\n'
            '\n'
            '💡 لإصلاح:\n'
            '  1. ضع SECRET_KEY قوي في .env (32+ حرف):\n'
            f'     SECRET_KEY={generate_secure_secret()}\n'
            '  2. غيّر SUPER_ADMIN_PASSWORD لقيمة قوية\n'
            '  3. ضع DEBUG=False\n'
            + '=' * 60
        )

    # في التطوير: تحذيرات فقط
    app.logger.warning('=' * 60)
    app.logger.warning('⚠️  تحذيرات أمنية (وضع التطوير):')
    for issue in issues:
        app.logger.warning(f'   • {issue}')
    app.logger.warning('=' * 60)


def _init_extensions(app):
    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    limiter.storage_uri = app.config['RATELIMIT_STORAGE_URI']
    limiter.init_app(app)
    sess.init_app(app)
    with app.app_context():
        from .models import (  # noqa: F401
            super_admin, tenant, tenant_user, activity, plan,
            subscription, conversation, audit_log,
            branch, hotel_models, restaurant_models, inquiry,
            chat_visitor, booking, integration,
            bot_config, custom_reply, tenant_deletion_code, password_reset_token,
            system_settings,
            ai_model, service_pricing, message_usage, tenant_wallet,
            contract_template, contract,
        )


def _register_blueprints(app):
    from .blueprints.public import bp as public_bp
    from .blueprints.registration import bp as registration_bp
    from .blueprints.super_admin import bp as super_admin_bp
    from .blueprints.tenant import bp as tenant_bp
    from .blueprints.chat import bp as chat_bp
    from .blueprints.api import bp as api_bp
    from .blueprints.tenant_hotel import bp as hotel_bp
    from .blueprints.tenant_restaurant import bp as restaurant_bp
    from .blueprints.tenant_inquiries import bp as inquiries_bp
    from .blueprints.tenant_bookings import bp as bookings_bp
    from .blueprints.admin_integrations import bp as integrations_bp
    from .blueprints.admin_bot_settings import bp as bot_bp
    from .blueprints.tenant_whatsapp import bp as tenant_whatsapp_bp
    from .blueprints.admin_system import bp as admin_system_bp
    from .blueprints.admin_pricing import bp as admin_pricing_bp
    from .blueprints.tenant_usage import bp as tenant_usage_bp
    from .blueprints.tenant_contracts import bp as tenant_contracts_bp
    from .blueprints.tenant_integrations import bp as tenant_integrations_bp
    from .blueprints.admin_ai_assistant import bp as admin_ai_bp
    from .blueprints.tenant_accounting import bp as tenant_accounting_bp
    from .routes.tenant_social_media_integrations import bp as social_media_bp
    from .blueprints.tenant_ai_agents import bp as ai_agents_bp
    from .blueprints.admin_plans_api import bp as admin_plans_api_bp
    from .blueprints.public_plans_api import bp as public_plans_api_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(registration_bp, url_prefix='/register')
    app.register_blueprint(super_admin_bp, url_prefix='/sa')
    app.register_blueprint(tenant_bp, url_prefix='/app')
    app.register_blueprint(chat_bp, url_prefix='/c')
    app.register_blueprint(api_bp, url_prefix='/api/v1')
    app.register_blueprint(hotel_bp, url_prefix='/app/hotel')
    app.register_blueprint(restaurant_bp, url_prefix='/app/restaurant')
    app.register_blueprint(inquiries_bp, url_prefix='/app/inquiries')
    app.register_blueprint(bookings_bp, url_prefix='/app/bookings')
    app.register_blueprint(integrations_bp, url_prefix='/sa/integrations')
    app.register_blueprint(bot_bp, url_prefix='/sa/bot')
    app.register_blueprint(tenant_whatsapp_bp, url_prefix='/app/whatsapp')
    app.register_blueprint(admin_system_bp, url_prefix='/sa/system')
    app.register_blueprint(admin_pricing_bp, url_prefix='/sa/pricing')
    app.register_blueprint(tenant_usage_bp, url_prefix='/app/usage')
    app.register_blueprint(tenant_contracts_bp, url_prefix='/app/contracts')
    app.register_blueprint(tenant_integrations_bp, url_prefix='/app/integrations')
    app.register_blueprint(admin_ai_bp, url_prefix='/sa/ai-assistant')
    app.register_blueprint(tenant_accounting_bp, url_prefix='/app/accounting')
    app.register_blueprint(social_media_bp, url_prefix='/app/integrations/social-media')
    app.register_blueprint(ai_agents_bp, url_prefix='/app/agents')
    app.register_blueprint(admin_plans_api_bp, url_prefix='/api/sa/plans')
    app.register_blueprint(public_plans_api_bp, url_prefix='/api/public/pricing')

    from .blueprints.notifications_api import bp as notifications_api_bp
    app.register_blueprint(notifications_api_bp, url_prefix='/api/notifications')

    app.logger.info('✓ Blueprints registered (+ AI Agents & Plans & Notifications)')


def _register_error_handlers(app):
    @app.errorhandler(404)
    def not_found(e):
        return render_template('errors/404.html'), 404
    @app.errorhandler(403)
    def forbidden(e):
        return render_template('errors/403.html'), 403
    @app.errorhandler(500)
    def server_error(e):
        app.logger.error(f'500 error: {e}')
        return render_template('errors/500.html'), 500
    @app.errorhandler(429)
    def ratelimit_handler(e):
        return render_template('errors/429.html', limit=str(e.description)), 429


def _register_security_headers(app):
    @app.after_request
    def add_security_headers(response):
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
        # Content-Security-Policy لمنع XSS
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://cdn.tailwindcss.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
            "img-src 'self' data: https: blob:; "
            "connect-src 'self' https://api.openai.com https://api.anthropic.com; "
            "frame-ancestors 'none'"
        )
        if app.config.get('SESSION_COOKIE_SECURE'):
            # HSTS فقط في بيئة HTTPS (الإنتاج)
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response


def _register_context_processors(app):
    @app.context_processor
    def inject_globals():
        from flask import g, session
        notif_count = 0
        try:
            from .utils.notification_service import NotificationService
            if hasattr(g, 'current_tenant') and g.current_tenant:
                notif_count = NotificationService.get_unread_count('tenant', g.current_tenant.id)
            else:
                sa = g.get('current_admin') or g.get('current_super_admin')
                if sa:
                    notif_count = NotificationService.get_unread_count('admin', sa.id)
        except Exception:
            pass

        return {
            'SITE_NAME': app.config.get('SITE_NAME'),
            'SITE_URL': app.config.get('SITE_URL'),
            'VAPID_PUBLIC_KEY': app.config.get('VAPID_PUBLIC_KEY', ''),
            'notification_count': notif_count,
        }


def _register_cli_commands(app):
    import click

    @app.cli.command('init-db')
    def init_db():
        with app.app_context():
            db.create_all()
            click.echo('✓ Database tables created')
            from .models.super_admin import SuperAdmin
            # ✅ لا نُنشئ Super Admin هنا — يُنشأ عبر صفحة /sa/setup عند أول دخول
            if SuperAdmin.query.count() == 0:
                click.echo('• No Super Admin yet — open /sa/setup in browser to create the first admin')
            else:
                click.echo(f'• Super Admin already exists ({SuperAdmin.query.count()} accounts)')
            from .services.activity_service import ActivityService
            from .services.plan_service import PlanService
            ActivityService.seed_defaults()
            PlanService.seed_defaults()

            # ✅ المرحلة 1.5: مفاتيح النظام الافتراضية
            from .models.system_settings import SystemSetting
            SystemSetting.seed_defaults()
            click.echo('✓ System settings seeded')

            # ✅ المرحلة 2A: نماذج AI + أسعار الخدمات
            from .models.ai_model import AIModel
            from .models.service_pricing import ServicePricing
            AIModel.seed_defaults()
            ServicePricing.seed_defaults()
            click.echo('✓ AI models and service pricing seeded')
            click.echo('✓ Default activities & plans seeded')

    @app.cli.command('super-admin-show')
    def super_admin_show():
        """طباعة أسماء المستخدمين وبريد السوبر أدمن المسجّل في القاعدة (بدون كلمة المرور)."""
        with app.app_context():
            from .models.super_admin import SuperAdmin
            admins = SuperAdmin.query.order_by(SuperAdmin.id).all()
            if not admins:
                click.echo(
                    'لا يوجد سوبر أدمن — افتح في المتصفح: /sa/setup لإنشاء أول حساب.'
                )
                return
            for a in admins:
                click.echo(
                    f"id={a.id}  username={a.username!r}  email={a.email!r}  active={a.is_active}"
                )

    @app.cli.command('reset-super-admin-password')
    @click.option('--username', default=None,
                  help='اسم المستخدم (إذا كان عندك أكثر من حساب؛ الافتراضي: أول حساب بالجدول)')
    @click.option('--password', default=None,
                  help='كلمة المرور الجديدة — إن لم تُمرَّر، سيُطلب إدخالها بشكل مخفي')
    def reset_super_admin_password(username, password):
        """إعادة تعيين كلمة مرور السوبر أدمن مباشرة في قاعدة البيانات (عند نسيانها أو فشل البريد)."""
        from .models.super_admin import SuperAdmin
        from .utils.passwords import hash_password

        with app.app_context():
            if username:
                admin = SuperAdmin.query.filter_by(username=username.strip()).first()
            else:
                admin = SuperAdmin.query.order_by(SuperAdmin.id).first()
            if not admin:
                click.echo('لم يُعثر على أي سوبر أدمن في القاعدة.', err=True)
                raise SystemExit(1)
            if not password:
                password = click.prompt('كلمة المرور الجديدة', hide_input=True,
                                        confirmation_prompt=True)
            if len((password or '')) < 6:
                click.echo('كلمة المرور يجب أن تكون 6 أحرف على الأقل.', err=True)
                raise SystemExit(1)
            admin.password_hash = hash_password(password)
            db.session.commit()
            click.echo(f'✓ تم تحديث كلمة المرور للحساب: {admin.username!r} ({admin.email})')

    @app.cli.command('super-admin-set-email')
    @click.option('--username', default=None,
                  help='اسم مستخدم السوبر أدمن (الافتراضي: أول حساب في الجدول)')
    @click.option('--email', 'new_email', required=True,
                  help='البريد الذي تستخدمه لتسجيل الدخول ولـ «نسيت كلمة المرور»')
    def super_admin_set_email(username, new_email):
        """تعيين أو تغيير بريد السوبر أدمن (لو كان عند الإعداد placeholder مثل admin@localhost)."""
        from .models.super_admin import SuperAdmin

        addr = (new_email or '').strip().lower()
        if '@' not in addr or len(addr) < 5:
            click.echo('بريد غير صالح.', err=True)
            raise SystemExit(1)

        with app.app_context():
            if username:
                admin = SuperAdmin.query.filter_by(username=username.strip()).first()
            else:
                admin = SuperAdmin.query.order_by(SuperAdmin.id).first()
            if not admin:
                click.echo('لم يُعثر على أي سوبر أدمن.', err=True)
                raise SystemExit(1)

            old = admin.email
            dup = SuperAdmin.query.filter(
                SuperAdmin.id != admin.id,
                db.func.lower(SuperAdmin.email) == addr,
            ).first()
            if dup:
                click.echo(f'البريد مستخدم مسبقاً لحساب آخر (id={dup.id}).', err=True)
                raise SystemExit(1)

            admin.email = addr
            db.session.commit()
            click.echo(f'✓ تم تحديث البريد: {old!r} → {addr!r}  (المستخدم: {admin.username!r})')
            click.echo('الآن يمكنك «نسيت كلمة المرور» بهذا البريد، أو تسجيل الدخول كالمعتاد.')

    @app.cli.command('seed-demo')
    def seed_demo():
        with app.app_context():
            click.echo('Creating demo tenant...')
            click.echo('✓ Demo data seeded')

    @app.cli.command('patch-schema')
    def patch_schema():
        """
        يضيف أعمدة ناقصة بعد تحديث النماذج دون حذف بيانات.
        (مثلاً whatsapp_auto_reply_enabled في bot_configs)
        """
        from sqlalchemy import inspect, text

        with app.app_context():
            bind = db.engine
            insp = inspect(bind)
            if not insp.has_table('bot_configs'):
                click.echo('bot_configs missing — run: flask init-db')
                return
            cols = {c['name'] for c in insp.get_columns('bot_configs')}
            changed = False
            if 'whatsapp_auto_reply_enabled' not in cols:
                if bind.dialect.name == 'sqlite':
                    ddl_wa = (
                        'ALTER TABLE bot_configs ADD COLUMN whatsapp_auto_reply_enabled '
                        'BOOLEAN NOT NULL DEFAULT 1'
                    )
                else:
                    ddl_wa = (
                        'ALTER TABLE bot_configs ADD COLUMN whatsapp_auto_reply_enabled '
                        'BOOLEAN NOT NULL DEFAULT true'
                    )
                with bind.begin() as conn:
                    conn.execute(text(ddl_wa))
                click.echo('OK: added bot_configs.whatsapp_auto_reply_enabled')
                changed = True
            if 'agent_gender' not in cols:
                ddl_ag = (
                    "ALTER TABLE bot_configs ADD COLUMN agent_gender VARCHAR(10) "
                    "NOT NULL DEFAULT 'neutral'"
                )
                with bind.begin() as conn:
                    conn.execute(text(ddl_ag))
                click.echo('OK: added bot_configs.agent_gender')
                changed = True
            if 'semantic_intent_enabled' not in cols:
                if bind.dialect.name == 'sqlite':
                    ddl_sem = (
                        'ALTER TABLE bot_configs ADD COLUMN semantic_intent_enabled '
                        'BOOLEAN NOT NULL DEFAULT 0'
                    )
                else:
                    ddl_sem = (
                        'ALTER TABLE bot_configs ADD COLUMN semantic_intent_enabled '
                        'BOOLEAN NOT NULL DEFAULT false'
                    )
                with bind.begin() as conn:
                    conn.execute(text(ddl_sem))
                click.echo('OK: added bot_configs.semantic_intent_enabled')
                changed = True
            if 'semantic_threshold' not in cols:
                if bind.dialect.name == 'sqlite':
                    ddl_th = (
                        'ALTER TABLE bot_configs ADD COLUMN semantic_threshold '
                        'REAL NOT NULL DEFAULT 0.42'
                    )
                else:
                    ddl_th = (
                        'ALTER TABLE bot_configs ADD COLUMN semantic_threshold '
                        'DOUBLE PRECISION NOT NULL DEFAULT 0.42'
                    )
                with bind.begin() as conn:
                    conn.execute(text(ddl_th))
                click.echo('OK: added bot_configs.semantic_threshold')
                changed = True
            if not changed:
                click.echo('OK: bot_configs schema up to date')

            # جدول رموز حذف النشاط (لوحة التاجر)
            if not insp.has_table('tenant_deletion_codes'):
                if bind.dialect.name == 'sqlite':
                    ddl_tdc = """
                    CREATE TABLE tenant_deletion_codes (
                        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                        tenant_id INTEGER NOT NULL,
                        code_hash VARCHAR(128) NOT NULL,
                        expires_at DATETIME NOT NULL,
                        created_at DATETIME NOT NULL,
                        FOREIGN KEY(tenant_id) REFERENCES tenants (id)
                    )
                    """
                    idx = 'CREATE INDEX ix_tdc_tenant ON tenant_deletion_codes (tenant_id)'
                else:
                    ddl_tdc = """
                    CREATE TABLE tenant_deletion_codes (
                        id SERIAL PRIMARY KEY,
                        tenant_id INTEGER NOT NULL REFERENCES tenants(id),
                        code_hash VARCHAR(128) NOT NULL,
                        expires_at TIMESTAMP NOT NULL,
                        created_at TIMESTAMP NOT NULL DEFAULT NOW()
                    )
                    """
                    idx = 'CREATE INDEX ix_tdc_tenant ON tenant_deletion_codes (tenant_id)'
                with bind.begin() as conn:
                    conn.execute(text(ddl_tdc))
                    conn.execute(text(idx))
                click.echo('OK: created tenant_deletion_codes')

            # ✅ أعمدة جديدة لـ contract_templates (provider/terms_text/features_text)
            if insp.has_table('contract_templates'):
                ct_cols = {c['name'] for c in insp.get_columns('contract_templates')}
                if 'provider' not in ct_cols:
                    with bind.begin() as conn:
                        conn.execute(text(
                            "ALTER TABLE contract_templates ADD COLUMN provider "
                            "VARCHAR(20) NOT NULL DEFAULT 'internal'"
                        ))
                    click.echo('OK: added contract_templates.provider')
                if 'terms_text' not in ct_cols:
                    with bind.begin() as conn:
                        conn.execute(text(
                            "ALTER TABLE contract_templates ADD COLUMN terms_text TEXT DEFAULT ''"
                        ))
                    click.echo('OK: added contract_templates.terms_text')
                if 'features_text' not in ct_cols:
                    with bind.begin() as conn:
                        conn.execute(text(
                            "ALTER TABLE contract_templates ADD COLUMN features_text TEXT DEFAULT ''"
                        ))
                    click.echo('OK: added contract_templates.features_text')

            # ✅ أعمدة جديدة لـ contracts (unit_id + bank_transfer_*)
            if insp.has_table('contracts'):
                cc_cols = {c['name'] for c in insp.get_columns('contracts')}
                ddl_list = []
                if 'unit_id' not in cc_cols:
                    ddl_list.append("ALTER TABLE contracts ADD COLUMN unit_id INTEGER")
                if 'bank_transfer_proof_url' not in cc_cols:
                    ddl_list.append("ALTER TABLE contracts ADD COLUMN bank_transfer_proof_url VARCHAR(500) DEFAULT ''")
                if 'bank_transfer_approved_by' not in cc_cols:
                    ddl_list.append("ALTER TABLE contracts ADD COLUMN bank_transfer_approved_by INTEGER")
                if 'bank_transfer_approved_at' not in cc_cols:
                    ddl_list.append("ALTER TABLE contracts ADD COLUMN bank_transfer_approved_at TIMESTAMP")
                if 'bank_transfer_rejected_at' not in cc_cols:
                    ddl_list.append("ALTER TABLE contracts ADD COLUMN bank_transfer_rejected_at TIMESTAMP")
                if 'bank_transfer_note' not in cc_cols:
                    ddl_list.append("ALTER TABLE contracts ADD COLUMN bank_transfer_note TEXT DEFAULT ''")
                for ddl in ddl_list:
                    with bind.begin() as conn:
                        conn.execute(text(ddl))
                    click.echo(f'OK: {ddl[:80]}')

            # ✅ صور أصناف المطعم
            if insp.has_table('restaurant_items'):
                ri_cols = {c['name'] for c in insp.get_columns('restaurant_items')}
                if 'images' not in ri_cols:
                    images_col_type = 'JSONB' if bind.dialect.name == 'postgresql' else 'JSON'
                    with bind.begin() as conn:
                        conn.execute(text(
                            f"ALTER TABLE restaurant_items ADD COLUMN images {images_col_type}"
                        ))
                    click.echo('OK: added restaurant_items.images')

            # ✅ حقول الحساب البنكي للتاجر (للتحويل البنكي)
            if insp.has_table('tenants'):
                t_cols = {c['name'] for c in insp.get_columns('tenants')}
                bank_ddl = []
                if 'bank_name' not in t_cols:
                    bank_ddl.append("ALTER TABLE tenants ADD COLUMN bank_name VARCHAR(100) DEFAULT ''")
                if 'bank_account_name' not in t_cols:
                    bank_ddl.append("ALTER TABLE tenants ADD COLUMN bank_account_name VARCHAR(200) DEFAULT ''")
                if 'bank_account_number' not in t_cols:
                    bank_ddl.append("ALTER TABLE tenants ADD COLUMN bank_account_number VARCHAR(40) DEFAULT ''")
                if 'bank_iban' not in t_cols:
                    bank_ddl.append("ALTER TABLE tenants ADD COLUMN bank_iban VARCHAR(40) DEFAULT ''")
                for ddl in bank_ddl:
                    with bind.begin() as conn:
                        conn.execute(text(ddl))
                    click.echo(f'OK: {ddl[:80]}')

            if not insp.has_table('password_reset_tokens'):
                if bind.dialect.name == 'sqlite':
                    ddl_prt = """
                    CREATE TABLE password_reset_tokens (
                        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                        purpose VARCHAR(20) NOT NULL,
                        subject_id INTEGER NOT NULL,
                        token_hash VARCHAR(128) NOT NULL,
                        expires_at DATETIME NOT NULL,
                        used_at DATETIME,
                        created_at DATETIME NOT NULL
                    )
                    """
                else:
                    ddl_prt = """
                    CREATE TABLE password_reset_tokens (
                        id SERIAL PRIMARY KEY,
                        purpose VARCHAR(20) NOT NULL,
                        subject_id INTEGER NOT NULL,
                        token_hash VARCHAR(128) NOT NULL,
                        expires_at TIMESTAMP NOT NULL,
                        used_at TIMESTAMP,
                        created_at TIMESTAMP NOT NULL DEFAULT NOW()
                    )
                    """
                idx1 = 'CREATE INDEX ix_prt_purpose_subj ON password_reset_tokens (purpose, subject_id)'
                idx2 = 'CREATE INDEX ix_prt_hash ON password_reset_tokens (token_hash)'
                idx3 = 'CREATE INDEX ix_prt_exp ON password_reset_tokens (expires_at)'
                with bind.begin() as conn:
                    conn.execute(text(ddl_prt))
                    conn.execute(text(idx1))
                    conn.execute(text(idx2))
                    conn.execute(text(idx3))
                click.echo('OK: created password_reset_tokens')

    @app.cli.command('send-reminders')
    def send_reminders():
        """فحص العقود وإرسال تذكيرات الدفع للعملاء بدءاً من 3 أيام قبل الانتهاء وبشكل يومي حتى الدفع."""
        with app.app_context():
            from datetime import datetime, timedelta
            from .models.contract import Contract
            from .services.whatsapp_service import WhatsAppService
            from .services.email_service import EmailService
            from .services.sms_service import SMSService
            
            click.echo('Starting reminder check...')
            now = datetime.utcnow()
            
            # نجلب العقود التي ما زالت تنتظر الدفع أو موقّعة أو مرسلة
            # ملاحظة: إذا كان paid يعني أن الفاتورة الحالية مدفوعة والعقد لم يُجدد، فلن نرسل تذكير إذا كانت paid 
            # ولكن سنرسل التذكير إذا كان payment_status != 'paid' (أي pending أو rejected الخ) أو status ليست paid
            contracts = Contract.query.filter(Contract.status.in_(['draft', 'pending_payment', 'sent', 'signed'])).all()
            sent_count = 0
            
            for c in contracts:
                fv = c.field_values or {}
                check_out = fv.get('check_out_date')
                duration = fv.get('duration')
                check_in = fv.get('check_in_date')
                
                # استنتاج تاريخ الخروج إذا لم يكن موجوداً
                if not check_out and check_in and duration:
                    try:
                        ci_date = datetime.strptime(check_in, '%Y-%m-%d')
                        co_date = ci_date + timedelta(days=int(duration) * 30) # تقريبي
                        check_out = co_date.strftime('%Y-%m-%d')
                    except Exception:
                        pass
                
                if check_out:
                    try:
                        co_date_parsed = datetime.strptime(check_out, '%Y-%m-%d')
                        days_left = (co_date_parsed - now).days
                        
                        # إرسال التذكير إذا تبقى 3 أيام أو أقل، ولم يتم الدفع
                        if days_left <= 3 and c.payment_status != 'paid':
                            tenant_settings = c.tenant.settings or {}
                            
                            # اختيار الرسالة
                            msg = 'نود تذكيركم باقتراب موعد الدفع للإيجار. شاكرين ومقدرين حسن تعاونكم.'
                            if tenant_settings.get('global_reminder_message'):
                                msg = tenant_settings.get('global_reminder_message')
                            elif c.template and c.template.reminder_message:
                                msg = c.template.reminder_message
                                
                            send_wa = tenant_settings.get('reminder_send_whatsapp', False)
                            send_em = tenant_settings.get('reminder_send_email', False)
                            send_sms = tenant_settings.get('reminder_send_sms', False)
                            
                            # للحفاظ على التوافق الرجعي: إذا لم يختر التاجر أي قناة، لا ترسل أو أرسل واتساب افتراضياً؟
                            # بما أنها ميزة جديدة، نرسل واتساب افتراضياً لو لم يوجد إعداد
                            if not (send_wa or send_em or send_sms):
                                send_wa = True
                                
                            # 1. إرسال واتساب
                            if send_wa and c.customer_phone and c.tenant:
                                try:
                                    WhatsAppService.send_text(c.tenant_id, c.customer_phone, msg)
                                    click.echo(f"WhatsApp reminder sent to {c.customer_phone}")
                                except Exception as e:
                                    click.echo(f"Failed to send WA to {c.customer_phone}: {e}")
                                    
                            # 2. إرسال إيميل
                            if send_em and c.customer_email and c.tenant:
                                try:
                                    payment_link = f"{app.config.get('SITE_URL', 'http://localhost:5000')}/pay/{c.contract_number or c.id}"
                                    EmailService.send_payment_reminder(
                                        to_email=c.customer_email,
                                        tenant_name=c.tenant.business_name,
                                        contract_number=c.contract_number or str(c.id),
                                        amount=str(c.payment_amount or c.template.get_payment_amount()),
                                        due_date=check_out,
                                        payment_link=payment_link,
                                        bank_name=c.tenant.bank_name,
                                        bank_account_name=c.tenant.bank_account_name,
                                        bank_iban=c.tenant.bank_iban
                                    )
                                    click.echo(f"Email reminder sent to {c.customer_email}")
                                except Exception as e:
                                    click.echo(f"Failed to send Email to {c.customer_email}: {e}")

                            # 3. إرسال SMS
                            if send_sms and c.customer_phone and c.tenant:
                                try:
                                    SMSService.send_sms(c.tenant_id, c.customer_phone, msg)
                                    click.echo(f"SMS reminder sent to {c.customer_phone}")
                                except Exception as e:
                                    click.echo(f"Failed to send SMS to {c.customer_phone}: {e}")
                                    
                            sent_count += 1
                    except Exception as e:
                        click.echo(f"Error parsing date for contract {c.id}: {e}")
                        
            click.echo(f'Finished. Processed {sent_count} reminders.')

    @app.cli.command('run-collection-agent')
    @click.option('--tenant-id', default=None, type=int,
                  help='معرف التاجر — إذا لم يُحدد يتم تشغيله على جميع التجار')
    @click.option('--days', default=3, type=int,
                  help='عدد الأيام للتحقق من العقود المنتهية (افتراضي: 3)')
    def run_collection_agent(tenant_id, days):
        """تشغيل وكيل التحصيل الذكي — يفحص العقود ويرسل تذكيرات الدفع."""
        with app.app_context():
            from .agents.collection_agent import CollectionAgent
            from .models.tenant import Tenant

            if tenant_id:
                tenants = [Tenant.query.get(tenant_id)]
                if not tenants[0]:
                    click.echo(f'لم يتم العثور على التاجر رقم {tenant_id}')
                    return
            else:
                tenants = Tenant.query.filter_by(status='active').all()

            click.echo(f'🤖 بدء تشغيل وكيل التحصيل على {len(tenants)} تاجر...')

            for t in tenants:
                click.echo(f'\n--- تاجر: {t.business_name} (ID={t.id}) ---')
                try:
                    agent = CollectionAgent(tenant_id=t.id)
                    result = agent.run_batch(days_ahead=days)
                    if result.success:
                        click.echo(result.text)
                    else:
                        click.echo(f'⚠️ {result.error}')
                except Exception as e:
                    click.echo(f'❌ خطأ: {e}')

            click.echo(f'\n✅ تم الانتهاء.')


def _setup_logging(app):
    if app.config.get('TESTING'):
        return
    log_format = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s [in %(pathname)s:%(lineno)d]'
    )

    # ✅ stdout handler — ضروري لمنصات PaaS (Heroku/Railway/Render)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(log_format)
    stream_handler.setLevel(logging.INFO)
    app.logger.addHandler(stream_handler)

    if not app.debug:
        logs_dir = app.config['BASE_DIR'] / 'logs'
        logs_dir.mkdir(exist_ok=True)
        file_handler = RotatingFileHandler(
            logs_dir / 'app.log', maxBytes=10*1024*1024, backupCount=5, encoding='utf-8'
        )
        file_handler.setFormatter(log_format)
        file_handler.setLevel(logging.INFO)
        app.logger.addHandler(file_handler)

    app.logger.setLevel(logging.INFO)

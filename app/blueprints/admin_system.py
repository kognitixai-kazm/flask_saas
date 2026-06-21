"""
app/blueprints/admin_system.py — إعدادات النظام (/sa/system)

تشمل:
- إدارة مفاتيح API (WhatsApp, AI, Cloudinary, Email...)
- تغيير كلمة مرور السوبر أدمن (بدون لمس .env)
- فحص الأمان والتحذيرات
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, current_app

from app.extensions import db
from app.decorators import super_admin_required
from app.models.system_settings import SystemSetting
from app.models.super_admin import SuperAdmin

bp = Blueprint('admin_system', __name__, template_folder='../../templates/super_admin')


# ========================================
# الصفحة الرئيسية — إعدادات النظام
# ========================================
@bp.route('/')
@super_admin_required
def index():
    """لوحة الإعدادات العامة — مفاتيح API."""
    settings_by_cat = {
        'whatsapp': SystemSetting.get_all_by_category('whatsapp'),
        'ai': SystemSetting.get_all_by_category('ai'),
        'cloudinary': SystemSetting.get_all_by_category('cloudinary'),
        'email': SystemSetting.get_all_by_category('email'),
        'google': SystemSetting.get_all_by_category('google'),
    }

    # جلب جميع نماذج الذكاء الاصطناعي المتاحة
    from app.models.ai_model import AIModel
    ai_models = AIModel.query.order_by(AIModel.sort_order).all()

    # فحص الأمان
    from app.utils.security import check_production_safety
    security_issues = check_production_safety(current_app.config)

    return render_template(
        'super_admin/system.html',
        settings_by_cat=settings_by_cat,
        ai_models=ai_models,
        security_issues=security_issues,
        sa_user=g.current_admin,
    )


# ========================================
# تحديث مفتاح
# ========================================
@bp.route('/update', methods=['POST'])
@super_admin_required
def update_setting():
    """تحديث قيمة مفتاح."""
    key = (request.form.get('key') or '').strip()
    value = request.form.get('value') or ''

    if not key:
        flash('مفتاح غير صالح', 'danger')
        return redirect(url_for('admin_system.index'))

    setting = SystemSetting.query.filter_by(key=key).first()
    if not setting:
        flash('المفتاح غير موجود', 'danger')
        return redirect(url_for('admin_system.index'))

    setting.value = value.strip()
    setting.updated_by = g.current_admin.username
    try:
        db.session.commit()
        flash(f'✅ تم تحديث {key}', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'[admin_system] update error: {e}')
        flash('حدث خطأ في الحفظ', 'danger')

    return redirect(url_for('admin_system.index'))


@bp.route('/update-bulk', methods=['POST'])
@super_admin_required
def update_bulk():
    """تحديث جميع المفاتيح في تصنيف واحد + تحقق ذكي للـ AI."""
    category = (request.form.get('category') or '').strip()
    if not category:
        flash('تصنيف غير صالح', 'danger')
        return redirect(url_for('admin_system.index'))

    settings = SystemSetting.query.filter_by(category=category).all()
    updated = 0
    changed_ai_providers: list[tuple[str, str]] = []  # (provider, key)

    ai_provider_map = {
        'AI_OPENAI_KEY': 'openai',
        'AI_ANTHROPIC_KEY': 'anthropic',
        'AI_GOOGLE_KEY': 'google',
    }

    for s in settings:
        new_value = request.form.get(f'val_{s.key}', None)
        if new_value is not None:
            new_value = new_value.strip()
            # لو سرّي وفاضي، لا نعدّل (نحافظ على القديم)
            if s.is_secret and not new_value:
                continue
            if s.value != new_value:
                # تحقق فوري لمفاتيح الذكاء الاصطناعي
                if category == 'ai' and s.key in ai_provider_map and new_value:
                    prov = ai_provider_map[s.key]
                    try:
                        from app.services.ai_service import AIService
                        AIService.invalidate_key_cache(prov, new_value)
                        ok, reason = AIService.validate_api_key(prov, new_value, force=True)
                        if not ok:
                            flash(f'❌ مفتاح {prov.upper()} غير صالح ({reason}). لم يتم حفظه.', 'danger')
                            continue
                        else:
                            flash(f'✅ مفتاح {prov.upper()} تم التحقق منه.', 'success')
                    except Exception as e:
                        current_app.logger.warning(f'[admin_system] AI validate error: {e}')
                        flash(f'⚠️ تعذر فحص مفتاح {prov.upper()} بسبب خطأ اتصال.', 'warning')
                        continue
                
                s.value = new_value
                s.updated_by = g.current_admin.username
                updated += 1

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'[admin_system] bulk update error: {e}')
        flash('حدث خطأ في الحفظ', 'danger')
        return redirect(url_for('admin_system.index'))

    if updated:
        flash(f'تم تحديث {updated} مفتاح في {category}.', 'success')
    return redirect(url_for('admin_system.index'))


# ========================================
# تغيير كلمة مرور السوبر أدمن (من اللوحة)
# ========================================
@bp.route('/change-password', methods=['POST'])
@super_admin_required
def change_password():
    """تغيير كلمة مرور السوبر أدمن — بدون لمس .env."""
    sa = g.current_admin

    current_pass = request.form.get('current_password', '')
    new_pass = request.form.get('new_password', '')
    confirm_pass = request.form.get('confirm_password', '')

    # تحقق
    if not sa.check_password(current_pass):
        flash('كلمة المرور الحالية غير صحيحة', 'danger')
        return redirect(url_for('admin_system.index'))

    if len(new_pass) < 10:
        flash('كلمة المرور الجديدة قصيرة جداً (10 أحرف على الأقل)', 'danger')
        return redirect(url_for('admin_system.index'))

    if new_pass != confirm_pass:
        flash('كلمتا المرور غير متطابقتين', 'danger')
        return redirect(url_for('admin_system.index'))

    # كلمات مرور ضعيفة شائعة
    weak = {'admin123', 'password', '1234567890', 'qwerty123'}
    if new_pass.lower() in weak:
        flash('كلمة المرور ضعيفة جداً، اختر كلمة أقوى', 'danger')
        return redirect(url_for('admin_system.index'))

    # حفظ
    sa.set_password(new_pass)
    try:
        db.session.commit()
        current_app.logger.info(f'[Security] Super admin password changed by {sa.username}')
        flash('✅ تم تغيير كلمة المرور بنجاح', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'[admin_system] password change error: {e}')
        flash('حدث خطأ', 'danger')

    return redirect(url_for('admin_system.index'))


@bp.route('/change-username', methods=['POST'])
@super_admin_required
def change_username():
    """تغيير اسم المستخدم للسوبر أدمن."""
    sa = g.current_admin

    new_username = (request.form.get('new_username') or '').strip()
    current_pass = request.form.get('current_password', '')

    if not sa.check_password(current_pass):
        flash('كلمة المرور غير صحيحة', 'danger')
        return redirect(url_for('admin_system.index'))

    if len(new_username) < 4:
        flash('اسم المستخدم قصير جداً (4 أحرف على الأقل)', 'danger')
        return redirect(url_for('admin_system.index'))

    # تحقق من عدم تكرار
    existing = SuperAdmin.query.filter(
        SuperAdmin.username == new_username,
        SuperAdmin.id != sa.id,
    ).first()
    if existing:
        flash('اسم المستخدم مستخدم مسبقاً', 'danger')
        return redirect(url_for('admin_system.index'))

    old_username = sa.username
    sa.username = new_username
    try:
        db.session.commit()
        current_app.logger.info(f'[Security] Super admin username changed: {old_username} → {new_username}')
        flash(f'✅ تم تغيير اسم المستخدم من "{old_username}" إلى "{new_username}"', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'[admin_system] username change error: {e}')
        flash('حدث خطأ', 'danger')

    return redirect(url_for('admin_system.index'))

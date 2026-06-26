"""
app/blueprints/admin_system.py — إعدادات النظام (/sa/system)

تشمل:
- إدارة مفاتيح API (WhatsApp, AI, Cloudinary, Email...)
- تغيير كلمة مرور السوبر أدمن (بدون لمس .env)
- فحص الأمان والتحذيرات
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, current_app, jsonify

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
    # فرض البذور التلقائية لضمان وجود كافة المفاتيح في قاعدة البيانات دائماً
    SystemSetting.seed_defaults()
    
    settings_by_cat = {
        'whatsapp': SystemSetting.get_all_by_category('whatsapp'),
        'ai': SystemSetting.get_all_by_category('ai'),
        'cloudinary': SystemSetting.get_all_by_category('cloudinary'),
        'email': SystemSetting.get_all_by_category('email'),
        'google': SystemSetting.get_all_by_category('google'),
    }

    # جلب جميع نماذج الذكاء الاصطناعي المتاحة (مع البذور التلقائية إذا كانت فارغة)
    from app.models.ai_model import AIModel
    from app.models.ai_provider import AIProvider
    
    if AIModel.query.count() == 0:
        AIModel.seed_defaults()
    ai_models = AIModel.query.order_by(AIModel.sort_order).all()
    ai_providers = AIProvider.query.order_by(AIProvider.priority).all()

    # فحص الأمان
    from app.utils.security import check_production_safety
    security_issues = check_production_safety(current_app.config)

    return render_template(
        'super_admin/system.html',
        settings_by_cat=settings_by_cat,
        ai_models=ai_models,
        ai_providers=ai_providers,
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

    setting.value_decrypted = value.strip()
    setting.updated_by = g.current_admin.username
    try:
        db.session.commit()
        flash(f'✅ تم تحديث {key}', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'[admin_system] update error: {e}')
        flash('حدث خطأ في الحفظ', 'danger')

    return redirect(url_for('admin_system.index'))


@bp.route('/update-ai', methods=['POST'])
@super_admin_required
def update_ai():
    """تحديث مزودي ونماذج الذكاء الاصطناعي."""
    from app.models.ai_provider import AIProvider
    from app.models.ai_model import AIModel
    
    providers = AIProvider.query.all()
    
    # 1. تحديث مفاتيح المزودين
    for p in providers:
        new_key = request.form.get(f'provider_key_{p.id}')
        if new_key is not None:
            new_key = new_key.strip()
            # If it's a masked password from the UI (e.g. •••••••), don't overwrite if it hasn't changed.
            # But the UI will just send empty if unchanged, so we check if it's not empty.
            if new_key:
                p.api_key_decrypted = new_key
                p.is_active = True
            elif request.form.get(f'provider_clear_{p.id}'):
                p.api_key_decrypted = ''
                p.is_active = False
                
    # 2. تحديث النماذج (التفعيل)
    models = AIModel.query.all()
    for m in models:
        m.is_active = request.form.get(f'model_active_{m.id}') == 'on'
        
    # 3. النموذج الافتراضي
    default_model_id = request.form.get('default_model_id')
    if default_model_id:
        for m in models:
            m.is_default = (str(m.id) == str(default_model_id))
            
    try:
        db.session.commit()
        flash('✅ تم حفظ إعدادات الذكاء الاصطناعي بنجاح.', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'[admin_system] update ai error: {e}')
        flash('حدث خطأ في الحفظ', 'danger')

    return redirect(url_for('admin_system.index') + '#tab-ai')

@bp.route('/update-bulk', methods=['POST'])
@super_admin_required
def update_bulk():
    """تحديث المفاتيح الاخرى."""
    category = (request.form.get('category') or '').strip()
    if not category or category == 'ai':
        flash('تصنيف غير صالح', 'danger')
        return redirect(url_for('admin_system.index'))

    settings = SystemSetting.query.filter_by(category=category).all()
    updated = 0
    for s in settings:
        new_value = request.form.get(f'val_{s.key}', None)
        if new_value is not None:
            new_value = new_value.strip()
            if s.is_secret and not new_value:
                continue
            if s.value_decrypted != new_value:
                s.value_decrypted = new_value
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


@bp.route('/test-ai-key', methods=['POST'])
@super_admin_required
def test_ai_key():
    """Test an AI API key without saving it."""
    data = request.get_json(silent=True) or {}
    provider = data.get('provider', '').strip().lower()
    api_key = data.get('api_key', '').strip()

    if not provider or not api_key:
        return jsonify({'success': False, 'message': 'المزوّد أو المفتاح مفقود'}), 400

    from app.services.ai_service import AIService
    ok, reason = AIService.validate_api_key(provider, api_key, force=True)
    
    if ok:
        return jsonify({'success': True, 'message': f'مفتاح {provider.upper()} صحيح ويعمل بنجاح!'})
    else:
        return jsonify({'success': False, 'message': f'فشل التحقق: {reason}'})



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

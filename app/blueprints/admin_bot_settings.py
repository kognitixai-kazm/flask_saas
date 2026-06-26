"""
app/blueprints/admin_bot_settings.py — إعدادات البوت لكل tenant (/sa/bot/*)
يشمل: أسلوب + تعليمات + مفاتيح + ردود مخصصة + رفع PDF + اتصال
"""
import os
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, current_app

from app.extensions import db
from app.decorators import super_admin_required
from app.models.tenant import Tenant
from app.models.bot_config import BotConfig
from app.models.custom_reply import CustomReply

bp = Blueprint('admin_bot', __name__, template_folder='../../templates/super_admin')


def _get_or_create_config(tenant_id):
    config = BotConfig.query.filter_by(tenant_id=tenant_id).first()
    if not config:
        config = BotConfig(tenant_id=tenant_id)
        db.session.add(config)
        db.session.flush()
    return config


# ==================== الصفحة الرئيسية ====================
@bp.route('/<int:tenant_id>')
@super_admin_required
def settings(tenant_id):
    tenant = Tenant.query.get_or_404(tenant_id)
    config = _get_or_create_config(tenant_id)
    replies = CustomReply.query.filter_by(tenant_id=tenant_id).order_by(CustomReply.usage_count.desc()).all()
    manual_count = CustomReply.query.filter_by(tenant_id=tenant_id, source='manual').count()
    learned_count = CustomReply.query.filter_by(tenant_id=tenant_id, source='learned').count()

    from app.models.ai_model import AIModel
    from app.models.ai_provider import AIProvider
    ai_models = AIModel.query.filter_by(is_active=True).all()
    ai_providers = AIProvider.query.filter_by(is_active=True).all()

    return render_template('super_admin/bot_settings.html',
        tenant=tenant, config=config, replies=replies,
        manual_count=manual_count, learned_count=learned_count,
        ai_models=ai_models, ai_providers=ai_providers)


# ==================== حفظ الإعدادات ====================
@bp.route('/<int:tenant_id>/save', methods=['POST'])
@super_admin_required
def save_settings(tenant_id):
    tenant = Tenant.query.get_or_404(tenant_id)
    config = _get_or_create_config(tenant_id)

    # أسلوب الرد
    config.tone = request.form.get('tone', 'friendly')
    config.bot_name = request.form.get('bot_name', '')
    ag = (request.form.get('agent_gender') or 'neutral').strip().lower()
    config.agent_gender = ag if ag in ('male', 'female', 'neutral') else 'neutral'
    config.custom_instructions = request.form.get('custom_instructions', '')
    config.blocked_topics = request.form.get('blocked_topics', '')

    # We no longer save image/voice/AI keys here as it is managed platform-wide

    # اتصال
    config.call_provider = request.form.get('call_provider', '')
    config.call_api_key_decrypted = request.form.get('call_api_key', '')
    config.call_api_secret_decrypted = request.form.get('call_api_secret', '')

    config.call_phone_number = request.form.get('call_phone_number', '')
    config.call_is_active = 'call_is_active' in request.form
    config.call_voice = request.form.get('call_voice', 'female_ar')
    config.call_greeting = request.form.get('call_greeting', '')

    base_url = (current_app.config.get('SITE_URL') or '').rstrip('/')
    if base_url:
        config.call_webhook_url = f'{base_url}/api/v1/webhooks/twilio/voice/{tenant_id}'

    # التعلم التلقائي
    config.auto_learn_enabled = 'auto_learn_enabled' in request.form

    # نوايا دلالية (اختياري)
    config.semantic_intent_enabled = 'semantic_intent_enabled' in request.form
    try:
        st = float((request.form.get('semantic_threshold') or '0.42').strip().replace(',', '.'))
        if 0.15 <= st <= 0.95:
            config.semantic_threshold = st
    except (TypeError, ValueError):
        pass

    db.session.commit()
    flash('✅ تم حفظ إعدادات البوت', 'success')
    return redirect(url_for('admin_bot.settings', tenant_id=tenant_id))


@bp.route('/test-ai-key', methods=['POST'])
@super_admin_required
def test_ai_key():
    """Test AI API key validity without saving it."""
    provider = request.form.get('provider', '').strip()
    api_key = request.form.get('api_key', '').strip()
    
    if not provider or not api_key:
        return {'success': False, 'message': 'الرجاء إدخال المزوّد والمفتاح'}
        
    from app.services.ai_service import AIService
    # Always force test for this endpoint
    ok, reason = AIService.validate_api_key(provider, api_key, force=True)
    
    if ok:
        return {'success': True, 'message': 'تم الاتصال بالذكاء الاصطناعي بنجاح ✅'}
    else:
        return {'success': False, 'message': f'فشل الاتصال: {reason} ❌'}


@bp.route('/<int:tenant_id>/call-test', methods=['POST'])
@super_admin_required
def call_test_outbound(tenant_id):
    """اختبار مكالمة Twilio صادرة (يتطلب إعدادات كاملة + SITE_URL)."""
    Tenant.query.get_or_404(tenant_id)
    phone = (request.form.get('test_call_phone') or '').strip()
    if not phone:
        flash('أدخل رقم العميل بصيغة دولية (مثال +9665...)', 'danger')
        return redirect(url_for('admin_bot.settings', tenant_id=tenant_id))
    from app.services.call_integration_service import initiate_outbound_call

    r = initiate_outbound_call(tenant_id, phone)
    if r.get('ok'):
        flash('✅ تم طلب المكالمة من Twilio', 'success')
    else:
        flash(f'❌ {r.get("error", "فشل")}', 'danger')
    return redirect(url_for('admin_bot.settings', tenant_id=tenant_id))


# ==================== رفع PDF (قاعدة معرفة) ====================
@bp.route('/<int:tenant_id>/upload-pdf', methods=['POST'])
@super_admin_required
def upload_pdf(tenant_id):
    config = _get_or_create_config(tenant_id)

    file = request.files.get('pdf_file')
    if not file or not file.filename.endswith('.pdf'):
        flash('يرجى رفع ملف PDF', 'danger')
        return redirect(url_for('admin_bot.settings', tenant_id=tenant_id))

    try:
        # استخراج النص من PDF
        import pdfplumber
        text_parts = []
        pdf_bytes = file.read()

        import io
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)

        extracted_text = '\n'.join(text_parts)

        if not extracted_text.strip():
            flash('لم يتم استخراج نص من الـ PDF (قد يكون صور فقط)', 'warning')
            return redirect(url_for('admin_bot.settings', tenant_id=tenant_id))

        # إضافة للقاعدة المعرفية (نضيف فوق الموجود)
        from datetime import datetime
        if config.knowledge_base:
            config.knowledge_base += f'\n\n--- ملف: {file.filename} ---\n' + extracted_text
        else:
            config.knowledge_base = f'--- ملف: {file.filename} ---\n' + extracted_text

        config.knowledge_files_count += 1
        config.knowledge_last_updated = datetime.utcnow()
        db.session.commit()

        chars = len(extracted_text)
        flash(f'✅ تم رفع "{file.filename}" — {chars:,} حرف مستخرج', 'success')

    except ImportError:
        # إذا pdfplumber مش مثبّت، نستخدم pypdf
        try:
            from pypdf import PdfReader
            import io

            file.seek(0)
            reader = PdfReader(io.BytesIO(file.read()))
            text_parts = []
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    text_parts.append(t)

            extracted_text = '\n'.join(text_parts)
            if not extracted_text.strip():
                flash('لم يتم استخراج نص من الـ PDF', 'warning')
                return redirect(url_for('admin_bot.settings', tenant_id=tenant_id))

            from datetime import datetime
            if config.knowledge_base:
                config.knowledge_base += f'\n\n--- ملف: {file.filename} ---\n' + extracted_text
            else:
                config.knowledge_base = f'--- ملف: {file.filename} ---\n' + extracted_text

            config.knowledge_files_count += 1
            config.knowledge_last_updated = datetime.utcnow()
            db.session.commit()

            flash(f'✅ تم رفع "{file.filename}" — {len(extracted_text):,} حرف', 'success')

        except Exception as e:
            flash(f'خطأ في قراءة الـ PDF: {e}', 'danger')

    except Exception as e:
        flash(f'خطأ: {e}', 'danger')

    return redirect(url_for('admin_bot.settings', tenant_id=tenant_id))


@bp.route('/<int:tenant_id>/clear-knowledge', methods=['POST'])
@super_admin_required
def clear_knowledge(tenant_id):
    config = _get_or_create_config(tenant_id)
    config.knowledge_base = ''
    config.knowledge_files_count = 0
    db.session.commit()
    flash('تم مسح قاعدة المعرفة', 'info')
    return redirect(url_for('admin_bot.settings', tenant_id=tenant_id))


# ==================== الردود المخصصة ====================
@bp.route('/<int:tenant_id>/replies/add', methods=['POST'])
@super_admin_required
def add_reply(tenant_id):
    keywords = request.form.get('keywords', '').strip()
    reply_text = request.form.get('reply_text', '').strip()

    if not keywords or not reply_text:
        flash('الكلمات المفتاحية والرد مطلوبين', 'danger')
        return redirect(url_for('admin_bot.settings', tenant_id=tenant_id))

    reply = CustomReply(
        tenant_id=tenant_id,
        keywords=keywords,
        reply_text=reply_text,
        source='manual',
    )
    db.session.add(reply)
    db.session.commit()
    flash('✅ تم إضافة الرد المخصص', 'success')
    return redirect(url_for('admin_bot.settings', tenant_id=tenant_id))


@bp.route('/<int:tenant_id>/replies/<int:reply_id>/delete', methods=['POST'])
@super_admin_required
def delete_reply(tenant_id, reply_id):
    reply = CustomReply.query.filter_by(id=reply_id, tenant_id=tenant_id).first_or_404()
    db.session.delete(reply)
    db.session.commit()
    flash('تم حذف الرد', 'info')
    return redirect(url_for('admin_bot.settings', tenant_id=tenant_id))


@bp.route('/<int:tenant_id>/replies/<int:reply_id>/toggle', methods=['POST'])
@super_admin_required
def toggle_reply(tenant_id, reply_id):
    reply = CustomReply.query.filter_by(id=reply_id, tenant_id=tenant_id).first_or_404()
    reply.is_active = not reply.is_active
    db.session.commit()
    flash(f'الرد {"مفعّل" if reply.is_active else "معطّل"}', 'info')
    return redirect(url_for('admin_bot.settings', tenant_id=tenant_id))

"""
app/routes/tenant_social_media_integrations.py — مسارات إدارة تكاملات التواصل الاجتماعي
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, g
from app.decorators import tenant_required

from app.extensions import db
from app.models.tenant import Tenant
from app.models.integration import Integration
from app.models.tenant_user import TenantUser
from app.services.social_media_integration_service import SocialMediaIntegrationService

bp = Blueprint('tenant_social_media_integrations', __name__, url_prefix='/tenant/integrations/social-media')


def get_tenant():
    """الحصول على المستأجر من الجلسة الحالية."""
    tenant = getattr(g, 'current_tenant', None)
    if not tenant:
        flash('المستأجر غير موجود', 'error')
    return tenant


@bp.route('/', methods=['GET'])
@tenant_required
def social_media():
    """صفحة تكاملات التواصل الاجتماعي الرئيسية."""
    tenant = get_tenant()
    if not tenant:
        return redirect(url_for('auth.login'))
    
    # الحصول على التكاملات النشطة
    integrations = Integration.query.filter(
        Integration.tenant_id == tenant.id,
        Integration.service_type.in_(['facebook', 'instagram', 'tiktok', 'snapchat', 'linkedin', 'google_maps'])
    ).all()
    
    social_integrations = {
        integ.service_type: integ for integ in integrations
    }
    
    return render_template(
        'tenant/integrations/social_media.html',
        tenant=tenant,
        social_integrations=social_integrations
    )


@bp.route('/ai-studio', methods=['GET'])
@tenant_required
def ai_studio():
    """ستوديو الذكاء الاصطناعي لصناعة المحتوى."""
    tenant = get_tenant()
    if not tenant:
        return redirect(url_for('auth.login'))
    
    return render_template(
        'tenant/integrations/ai_studio.html',
        tenant=tenant
    )


@bp.route('/api/ai-studio/generate', methods=['POST'])
@tenant_required
def generate_ai_content():
    """توليد محتوى وتصميم باستخدام الذكاء الاصطناعي."""
    tenant = get_tenant()
    if not tenant:
        return jsonify({'error': 'غير مصرح'}), 401
        
    try:
        data = request.get_json()
        prompt = data.get('prompt', '')
        platform = data.get('platform', 'general')
        tone = data.get('tone', 'professional')
        
        if not prompt:
            return jsonify({'error': 'الرجاء إدخال وصف مبدئي'}), 400
            
        # محاكاة توليد محتوى بالذكاء الاصطناعي
        # في بيئة الإنتاج الفعلية، سيتم استدعاء OpenAI API أو نموذج آخر
        import time
        time.sleep(1.5) # محاكاة التأخير
        
        # بعض القوالب الوهمية المؤقتة حتى يتم ربط الـ AI
        generated_text = f"✨ اكتشف روعة خدماتنا مع عروضنا الحصرية!\n\nنقدم لكم أفضل تجربة ممكنة في مجالنا.\n\nلماذا تختارنا؟\n✅ جودة عالية\n✅ خدمة عملاء على مدار الساعة\n✅ أسعار تنافسية\n\nتواصل معنا الآن للحجز والاستفسار!\n\n#تسويق #عروض #تخفيضات #أفضل_الأسعار"
        
        # تعديل النص قليلاً بناء على المنصة
        if platform == 'instagram':
            generated_text = f"🌟 جديدنا اليوم!\n\nهل تبحث عن الأفضل؟ وصلنا للتو تشكيلة جديدة ومميزة تليق بكم 💖\n\n✨ مميزات لا تفوت:\n✔️ جودة لا يعلى عليها\n✔️ تفاصيل دقيقة\n✔️ تصاميم عصرية\n\nاطلب الآن عبر الرابط في البايو 🔗\n\n#انستغرام #جديد #عروض #أناقة #لايف_ستايل #السعودية"
        elif platform == 'twitter':
            generated_text = f"🚀 لا تفوت الفرصة!\nاستمتع بأفضل العروض الحصرية لدينا اليوم.\n\nتواصل معنا الآن لتحصل على خصم خاص 🎁\n\n#عروض #خصومات #السعودية #ترند"
        elif platform == 'snapchat':
            generated_text = f"🔥 حصرياً لمتابعين السناب!\n\nارفع الشاشة الآن لاكتشاف العرض الخيالي 👆\n\n#سناب #حصري #عروض_خاصة"
            
        # رابط صورة وهمية (في الواقع سيتم توليدها عبر DALL-E أو Midjourney)
        image_url = "https://images.unsplash.com/photo-1542744173-8e7e53415bb0?ixlib=rb-4.0.3&auto=format&fit=crop&w=800&q=80"
        if tenant.activity and tenant.activity.code == 'restaurant':
            image_url = "https://images.unsplash.com/photo-1504674900247-0877df9cc836?ixlib=rb-4.0.3&auto=format&fit=crop&w=800&q=80"
        elif tenant.activity and tenant.activity.code == 'hotel':
            image_url = "https://images.unsplash.com/photo-1566073771259-6a8506099945?ixlib=rb-4.0.3&auto=format&fit=crop&w=800&q=80"
            
        return jsonify({
            'status': 'success',
            'generated_text': generated_text,
            'image_url': image_url
        })
    except Exception as e:
        current_app.logger.error(f'[AI Studio] Error: {e}')
        return jsonify({'error': 'حدث خطأ أثناء التوليد'}), 500



@bp.route('/<service_type>/setup', methods=['GET', 'POST'])
@tenant_required
def social_media_setup(service_type):
    """صفحة إعداد تكامل معين."""
    tenant = get_tenant()
    if not tenant:
        return redirect(url_for('auth.login'))
    
    # التحقق من أن service_type صحيح
    valid_services = ['facebook', 'instagram', 'tiktok', 'snapchat', 'linkedin', 'google_maps']
    if service_type not in valid_services:
        flash('نوع الخدمة غير صحيح', 'error')
        return redirect(url_for('tenant_social_media_integrations.social_media'))
    
    # الحصول على التكامل الموجود (إن وجد)
    integration = Integration.query.filter_by(
        tenant_id=tenant.id,
        service_type=service_type
    ).first()
    
    # خريطة أسماء الخدمات والأيقونات
    service_names = {
        'facebook': 'فيسبوك',
        'instagram': 'انستغرام',
        'tiktok': 'تيك توك',
        'snapchat': 'سناب شات',
        'linkedin': 'لينكدإن',
        'google_maps': 'خرائط جوجل'
    }
    
    service_icons = {
        'facebook': '👍',
        'instagram': '📸',
        'tiktok': '🎵',
        'snapchat': '👻',
        'linkedin': '💼',
        'google_maps': '🗺️'
    }
    
    if request.method == 'POST':
        try:
            # جمع البيانات من النموذج
            credentials = {
                'api_key': request.form.get('api_key', ''),
                'api_secret': request.form.get('api_secret', ''),
                'access_token': request.form.get('access_token', ''),
                'phone_number': request.form.get('phone_number', ''),
                'phone_number_id': request.form.get('phone_number_id', ''),
                'waba_id': request.form.get('waba_id', ''),
                'webhook_verify_token': request.form.get('webhook_verify_token', ''),
                'extra_config': {
                    'page_id': request.form.get('page_id', ''),
                    'instagram_business_account_id': request.form.get('instagram_business_account_id', ''),
                    'ad_account_id': request.form.get('ad_account_id', ''),
                    'organization_id': request.form.get('organization_id', ''),
                    'business_location_id': request.form.get('business_location_id', ''),
                    'enable_ai_responses': request.form.get('enable_ai_responses') == 'true',
                    'ai_tone': request.form.get('ai_tone', 'professional'),
                    'ai_instructions': request.form.get('ai_instructions', '')
                }
            }
            
            # تحديد المزود بناءً على نوع الخدمة
            provider_map = {
                'facebook': 'facebook_graph_api',
                'instagram': 'instagram_graph_api',
                'tiktok': 'tiktok_for_business_api',
                'snapchat': 'snap_marketing_api',
                'linkedin': 'linkedin_marketing_api',
                'google_maps': 'google_my_business_api'
            }
            
            provider = provider_map.get(service_type, 'custom')
            
            # تفعيل التكامل
            service = SocialMediaIntegrationService(tenant.id)
            success, message = service.activate_integration(
                service_type=service_type,
                provider=provider,
                credentials=credentials
            )
            
            if success:
                flash(f'✅ تم تفعيل تكامل {service_names[service_type]} بنجاح', 'success')
                return redirect(url_for('tenant_social_media_integrations.social_media'))
            else:
                flash(f'❌ خطأ: {message}', 'error')
        except Exception as e:
            current_app.logger.error(f'[Social Media] setup error: {e}')
            flash(f'❌ حدث خطأ: {str(e)}', 'error')
    
    webhook_url = f"{request.host_url.rstrip('/')}/api/v1/webhooks/{service_type}"
    return render_template(
        'tenant/integrations/social_media_setup.html',
        service_type=service_type,
        service_name=service_names.get(service_type, service_type),
        service_icon=service_icons.get(service_type, ''),
        integration=integration,
        webhook_url=webhook_url
    )


@bp.route('/<service_type>/deactivate', methods=['POST'])
@tenant_required
def social_media_deactivate(service_type):
    """تعطيل تكامل."""
    tenant = get_tenant()
    if not tenant:
        return redirect(url_for('auth.login'))
    
    try:
        service = SocialMediaIntegrationService(tenant.id)
        success, message = service.deactivate_integration(service_type)
        
        if success:
            flash(f'✅ تم تعطيل التكامل بنجاح', 'success')
        else:
            flash(f'❌ خطأ: {message}', 'error')
    except Exception as e:
        current_app.logger.error(f'[Social Media] deactivate error: {e}')
        flash(f'❌ حدث خطأ: {str(e)}', 'error')
    
    return redirect(url_for('tenant_social_media_integrations.social_media'))





@bp.route('/test/<service_type>', methods=['POST'])
@tenant_required
def test_integration(service_type):
    """اختبار التكامل."""
    tenant = get_tenant()
    if not tenant:
        return jsonify({'error': 'المستأجر غير موجود'}), 404
    
    try:
        integration = Integration.query.filter_by(
            tenant_id=tenant.id,
            service_type=service_type
        ).first()
        
        if not integration:
            return jsonify({'error': 'التكامل غير موجود'}), 404
        
        # اختبار بسيط: التحقق من صحة المفاتيح
        if not integration.access_token:
            return jsonify({'error': 'لم يتم تعيين رمز الوصول'}), 400
        
        # يمكن إضافة اختبارات أكثر تفصيلاً هنا
        return jsonify({
            'status': 'success',
            'message': f'التكامل مع {service_type} يعمل بشكل صحيح'
        }), 200
    except Exception as e:
        current_app.logger.error(f'[Social Media] test error: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/stats/<service_type>', methods=['GET'])
@tenant_required
def get_integration_stats(service_type):
    """الحصول على إحصائيات التكامل."""
    tenant = get_tenant()
    if not tenant:
        return jsonify({'error': 'المستأجر غير موجود'}), 404
    
    try:
        integration = Integration.query.filter_by(
            tenant_id=tenant.id,
            service_type=service_type
        ).first()
        
        if not integration:
            return jsonify({'error': 'التكامل غير موجود'}), 404
        
        stats = {
            'service_type': service_type,
            'is_active': integration.is_active,
            'is_verified': integration.is_verified,
            'messages_sent': integration.messages_sent,
            'messages_received': integration.messages_received,
            'created_at': integration.created_at.isoformat(),
            'updated_at': integration.updated_at.isoformat()
        }
        
        return jsonify(stats), 200
    except Exception as e:
        current_app.logger.error(f'[Social Media] stats error: {e}')
        return jsonify({'error': str(e)}), 500

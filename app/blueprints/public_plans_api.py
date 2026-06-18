from flask import Blueprint, jsonify
from app.models.plan import Plan

bp = Blueprint('public_plans_api', __name__, url_prefix='/api/public/pricing')

@bp.route('/', methods=['GET'])
def get_public_pricing():
    # Only return active plans, ordered by sort_order
    plans = Plan.query.filter_by(status='active').order_by(Plan.sort_order).all()
    result = []
    
    for p in plans:
        result.append({
            'id': p.id,
            'code': p.code,
            'name_ar': p.name_ar,
            'name_en': p.name_en,
            'description_ar': p.description_ar,
            'description_en': p.description_en,
            'is_popular': p.is_popular,
            'badge_color': p.badge_color,
            'badge_text': p.badge_text,
            'trial_days': p.trial_days,
            'pricing': {
                'price_monthly': float(p.pricing.price_monthly) if p.pricing else 0,
                'price_yearly': float(p.pricing.price_yearly) if p.pricing else 0,
                'currency': p.pricing.currency if p.pricing else 'SAR',
            },
            'limits': {
                'max_branches': p.limits.max_branches if p.limits else 1,
                'max_users': p.limits.max_users if p.limits else 1,
                'max_employees': p.limits.max_employees if p.limits else 1,
                'max_clients': p.limits.max_clients if p.limits else 0,
                'max_whatsapp_msgs': p.limits.max_whatsapp_msgs if p.limits else 0,
                'max_sms': p.limits.max_sms if p.limits else 0,
                'max_emails': p.limits.max_emails if p.limits else 0,
                'max_push_notifications': p.limits.max_push_notifications if p.limits else 0,
                'max_contracts_per_month': p.limits.max_contracts_per_month if p.limits else 0,
                'storage_limit_gb': p.limits.storage_limit_gb if p.limits else 1,
            },
            'modules': [{'module_name': m.module_name, 'is_enabled': m.is_enabled} for m in p.modules if m.is_enabled],
            'agents': [{'agent_type': a.agent_type, 'is_enabled': a.is_enabled, 'monthly_usage_limit': a.monthly_usage_limit, 'max_conversations': a.max_conversations, 'max_voice_calls': a.max_voice_calls} for a in p.agents if a.is_enabled],
            'integrations': [{'integration_name': i.integration_name, 'is_enabled': i.is_enabled} for i in p.integrations if i.is_enabled],
            # Permissions might not be public depending on the logic, but 'visible' ones can be shown as features
            'features': [{'feature_key': perm.feature_key, 'visibility': perm.visibility} for perm in p.permissions if perm.visibility != 'hidden'],
        })
        
    return jsonify({'success': True, 'plans': result})

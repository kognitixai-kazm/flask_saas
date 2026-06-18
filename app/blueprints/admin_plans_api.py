import json
from flask import Blueprint, jsonify, request, flash, g, current_app
from app.extensions import db
from app.decorators import super_admin_required
from app.models.plan import Plan, PlanPricing, PlanLimit, PlanModule, PlanAgent, PlanIntegration, PlanPermission

bp = Blueprint('admin_plans_api', __name__, url_prefix='/api/sa/plans')

@bp.route('/', methods=['GET'])
@super_admin_required
def get_plans():
    plans = Plan.query.order_by(Plan.sort_order).all()
    result = []
    for p in plans:
        result.append({
            'id': p.id,
            'code': p.code,
            'name_ar': p.name_ar,
            'name_en': p.name_en,
            'status': p.status,
            'price_monthly': float(p.price_monthly),
            'price_yearly': float(p.price_yearly),
            'currency': p.currency,
            'is_popular': p.is_popular,
            'sort_order': p.sort_order,
        })
    return jsonify(result)

@bp.route('/<int:plan_id>', methods=['GET'])
@super_admin_required
def get_plan(plan_id):
    p = Plan.query.get_or_404(plan_id)
    return jsonify({
        'id': p.id,
        'code': p.code,
        'name_ar': p.name_ar,
        'name_en': p.name_en,
        'description_ar': p.description_ar,
        'description_en': p.description_en,
        'status': p.status,
        'is_popular': p.is_popular,
        'badge_color': p.badge_color,
        'badge_text': p.badge_text,
        'sort_order': p.sort_order,
        'trial_days': p.trial_days,
        'pricing': {
            'price_monthly': float(p.pricing.price_monthly) if p.pricing else 0,
            'price_yearly': float(p.pricing.price_yearly) if p.pricing else 0,
            'currency': p.pricing.currency if p.pricing else 'SAR',
            'stripe_price_id_monthly': p.pricing.stripe_price_id_monthly if p.pricing else '',
            'stripe_price_id_yearly': p.pricing.stripe_price_id_yearly if p.pricing else '',
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
        'modules': [{'module_name': m.module_name, 'is_enabled': m.is_enabled} for m in p.modules],
        'agents': [{'agent_type': a.agent_type, 'is_enabled': a.is_enabled, 'monthly_usage_limit': a.monthly_usage_limit, 'max_conversations': a.max_conversations, 'max_voice_calls': a.max_voice_calls} for a in p.agents],
        'integrations': [{'integration_name': i.integration_name, 'is_enabled': i.is_enabled} for i in p.integrations],
        'permissions': [{'feature_key': perm.feature_key, 'visibility': perm.visibility} for perm in p.permissions],
    })

@bp.route('/', methods=['POST'])
@super_admin_required
def create_plan():
    data = request.json
    
    plan = Plan(
        code=data.get('code', ''),
        name_ar=data.get('name_ar', ''),
        name_en=data.get('name_en', ''),
        description_ar=data.get('description_ar', ''),
        description_en=data.get('description_en', ''),
        status=data.get('status', 'draft'),
        is_popular=data.get('is_popular', False),
        badge_color=data.get('badge_color', ''),
        badge_text=data.get('badge_text', ''),
        sort_order=int(data.get('sort_order', 0)),
        trial_days=int(data.get('trial_days', 14)),
    )
    db.session.add(plan)
    db.session.flush() # to get plan.id
    
    # Pricing
    p_data = data.get('pricing', {})
    pricing = PlanPricing(
        plan_id=plan.id,
        price_monthly=p_data.get('price_monthly', 0),
        price_yearly=p_data.get('price_yearly', 0),
        currency=p_data.get('currency', 'SAR'),
        stripe_price_id_monthly=p_data.get('stripe_price_id_monthly'),
        stripe_price_id_yearly=p_data.get('stripe_price_id_yearly')
    )
    db.session.add(pricing)
    
    # Limits
    l_data = data.get('limits', {})
    limits = PlanLimit(
        plan_id=plan.id,
        max_branches=l_data.get('max_branches', 1),
        max_users=l_data.get('max_users', 1),
        max_employees=l_data.get('max_employees', 1),
        max_clients=l_data.get('max_clients', 0),
        max_whatsapp_msgs=l_data.get('max_whatsapp_msgs', 0),
        max_sms=l_data.get('max_sms', 0),
        max_emails=l_data.get('max_emails', 0),
        max_push_notifications=l_data.get('max_push_notifications', 0),
        max_contracts_per_month=l_data.get('max_contracts_per_month', 0),
        storage_limit_gb=l_data.get('storage_limit_gb', 1)
    )
    db.session.add(limits)
    
    # Modules
    for m in data.get('modules', []):
        db.session.add(PlanModule(plan_id=plan.id, module_name=m['module_name'], is_enabled=m['is_enabled']))
        
    # Agents
    for a in data.get('agents', []):
        db.session.add(PlanAgent(
            plan_id=plan.id, 
            agent_type=a['agent_type'], 
            is_enabled=a['is_enabled'],
            monthly_usage_limit=a.get('monthly_usage_limit', 0),
            max_conversations=a.get('max_conversations', 0),
            max_voice_calls=a.get('max_voice_calls', 0)
        ))
        
    # Integrations
    for i in data.get('integrations', []):
        db.session.add(PlanIntegration(plan_id=plan.id, integration_name=i['integration_name'], is_enabled=i['is_enabled']))
        
    # Permissions
    for p in data.get('permissions', []):
        db.session.add(PlanPermission(plan_id=plan.id, feature_key=p['feature_key'], visibility=p['visibility']))
        
    db.session.commit()
    return jsonify({'success': True, 'plan_id': plan.id})

@bp.route('/<int:plan_id>', methods=['PUT'])
@super_admin_required
def update_plan(plan_id):
    plan = Plan.query.get_or_404(plan_id)
    data = request.json
    
    plan.code = data.get('code', plan.code)
    plan.name_ar = data.get('name_ar', plan.name_ar)
    plan.name_en = data.get('name_en', plan.name_en)
    plan.description_ar = data.get('description_ar', plan.description_ar)
    plan.description_en = data.get('description_en', plan.description_en)
    plan.status = data.get('status', plan.status)
    plan.is_popular = data.get('is_popular', plan.is_popular)
    plan.badge_color = data.get('badge_color', plan.badge_color)
    plan.badge_text = data.get('badge_text', plan.badge_text)
    plan.sort_order = int(data.get('sort_order', plan.sort_order))
    plan.trial_days = int(data.get('trial_days', plan.trial_days))
    
    # Pricing
    p_data = data.get('pricing', {})
    if not plan.pricing:
        plan.pricing = PlanPricing(plan_id=plan.id)
        db.session.add(plan.pricing)
    plan.pricing.price_monthly = p_data.get('price_monthly', plan.pricing.price_monthly)
    plan.pricing.price_yearly = p_data.get('price_yearly', plan.pricing.price_yearly)
    plan.pricing.currency = p_data.get('currency', plan.pricing.currency)
    plan.pricing.stripe_price_id_monthly = p_data.get('stripe_price_id_monthly', plan.pricing.stripe_price_id_monthly)
    plan.pricing.stripe_price_id_yearly = p_data.get('stripe_price_id_yearly', plan.pricing.stripe_price_id_yearly)
    
    # Limits
    l_data = data.get('limits', {})
    if not plan.limits:
        plan.limits = PlanLimit(plan_id=plan.id)
        db.session.add(plan.limits)
    for key in ['max_branches', 'max_users', 'max_employees', 'max_clients', 'max_whatsapp_msgs', 'max_sms', 'max_emails', 'max_push_notifications', 'max_contracts_per_month', 'storage_limit_gb']:
        if key in l_data:
            setattr(plan.limits, key, l_data[key])
            
    # Modules
    PlanModule.query.filter_by(plan_id=plan.id).delete()
    for m in data.get('modules', []):
        db.session.add(PlanModule(plan_id=plan.id, module_name=m['module_name'], is_enabled=m['is_enabled']))
        
    # Agents
    PlanAgent.query.filter_by(plan_id=plan.id).delete()
    for a in data.get('agents', []):
        db.session.add(PlanAgent(
            plan_id=plan.id, 
            agent_type=a['agent_type'], 
            is_enabled=a['is_enabled'],
            monthly_usage_limit=a.get('monthly_usage_limit', 0),
            max_conversations=a.get('max_conversations', 0),
            max_voice_calls=a.get('max_voice_calls', 0)
        ))
        
    # Integrations
    PlanIntegration.query.filter_by(plan_id=plan.id).delete()
    for i in data.get('integrations', []):
        db.session.add(PlanIntegration(plan_id=plan.id, integration_name=i['integration_name'], is_enabled=i['is_enabled']))
        
    # Permissions
    PlanPermission.query.filter_by(plan_id=plan.id).delete()
    for p in data.get('permissions', []):
        db.session.add(PlanPermission(plan_id=plan.id, feature_key=p['feature_key'], visibility=p['visibility']))
        
    db.session.commit()
    return jsonify({'success': True})

@bp.route('/<int:plan_id>/publish', methods=['POST'])
@super_admin_required
def publish_plan(plan_id):
    plan = Plan.query.get_or_404(plan_id)
    plan.status = 'active'
    db.session.commit()
    return jsonify({'success': True, 'message': 'تم نشر الباقة بنجاح'})

@bp.route('/reorder', methods=['POST'])
@super_admin_required
def reorder_plans():
    data = request.json # expected: [{'id': 1, 'sort_order': 0}, ...]
    for item in data.get('plans', []):
        p = Plan.query.get(item['id'])
        if p:
            p.sort_order = item['sort_order']
    db.session.commit()
    return jsonify({'success': True})

"""
app/blueprints/tenant_ai_agents.py — واجهة API لوكلاء الذكاء الاصطناعي.

يوفر:
1. /app/agents/manager/ask — شريط البحث الذكي في لوحة التاجر
2. /app/agents/front-desk/reply — وكيل الاستقبال (يُستدعى من أي قناة)
3. /app/agents/collection/run — تشغيل وكيل التحصيل يدوياً
4. /app/agents/status — حالة الوكلاء وإعداداتهم
"""
import json
from flask import Blueprint, request, jsonify, session, current_app

from app.extensions import db
from app.decorators import tenant_required

bp = Blueprint('tenant_ai_agents', __name__)


def _get_tenant_id():
    """جلب tenant_id من الجلسة."""
    return session.get('tenant_id')


# ================================================================
# 1. شريط البحث الذكي — وكيل المدير (Manager Agent)
# ================================================================
@bp.route('/manager/ask', methods=['POST'])
@tenant_required
def manager_ask():
    """
    شريط البحث الذكي — يستقبل سؤال من التاجر ويرد بتحليلات مالية.

    Request JSON:
        {"question": "كم أرباح هذا الشهر؟"}

    Response JSON:
        {"success": true, "answer": "...", "tokens": 150, "price": 0.15}
    """
    tenant_id = _get_tenant_id()
    if not tenant_id:
        return jsonify({'error': 'غير مصرح'}), 401

    data = request.get_json(silent=True) or {}
    question = (data.get('question') or '').strip()

    if not question:
        return jsonify({'error': 'يرجى كتابة سؤال'}), 400

    if len(question) > 500:
        return jsonify({'error': 'السؤال طويل جداً (الحد الأقصى 500 حرف)'}), 400

    try:
        from app.agents.manager_agent import ManagerAgent
        agent = ManagerAgent(tenant_id=tenant_id)
        result = agent.run(question)

        return jsonify({
            'success': result.success,
            'answer': result.text if result.success else result.error,
            'tokens': result.tokens_in + result.tokens_out,
            'price': result.price_charged,
            'agent_type': result.agent_type,
        })

    except Exception as e:
        current_app.logger.exception(f'[ManagerAgent] error: {e}')
        return jsonify({
            'success': False,
            'error': f'حدث خطأ: {str(e)[:100]}',
        }), 500


# ================================================================
# 2. وكيل الاستقبال — Omnichannel (لجميع المنصات)
# ================================================================
@bp.route('/front-desk/reply', methods=['POST'])
def front_desk_reply():
    """
    وكيل الاستقبال — يُستدعى من أي قناة (واتساب، فيسبوك، ويب...).

    Request JSON:
        {
            "tenant_id": 1,
            "message": "أريد حجز شقة",
            "channel": "whatsapp",
            "visitor_id": "966500000000",
            "conversation_id": 123,
            "extra_context": {}
        }

    Response JSON:
        {"success": true, "reply": "...", "tool_calls": [...]}
    """
    data = request.get_json(silent=True) or {}

    tenant_id = data.get('tenant_id')
    message = (data.get('message') or '').strip()
    channel = data.get('channel', 'web')
    visitor_id = data.get('visitor_id', '')
    conversation_id = data.get('conversation_id')
    extra_context = data.get('extra_context', {})

    if not tenant_id or not message:
        return jsonify({'error': 'tenant_id و message مطلوبان'}), 400

    try:
        from app.agents.front_desk_agent import FrontDeskAgent

        agent = FrontDeskAgent(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            channel=channel,
        )

        result = agent.run(
            user_message=message,
            channel=channel,
            visitor_id=visitor_id,
            extra_context=extra_context,
        )

        return jsonify({
            'success': result.success,
            'reply': result.text if result.success else result.error,
            'tokens': result.tokens_in + result.tokens_out,
            'price': result.price_charged,
            'tool_calls': result.tool_calls,
            'agent_type': result.agent_type,
        })

    except Exception as e:
        current_app.logger.exception(f'[FrontDeskAgent] error: {e}')
        return jsonify({
            'success': False,
            'error': f'حدث خطأ: {str(e)[:100]}',
        }), 500


# ================================================================
# 3. وكيل التحصيل — تشغيل يدوي أو آلي
# ================================================================
@bp.route('/collection/run', methods=['POST'])
@tenant_required
def collection_run():
    """
    تشغيل وكيل التحصيل يدوياً — يفحص العقود ويرسل تذكيرات.

    Request JSON:
        {"days_ahead": 3}

    Response JSON:
        {"success": true, "summary": "...", "actions": [...]}
    """
    tenant_id = _get_tenant_id()
    if not tenant_id:
        return jsonify({'error': 'غير مصرح'}), 401

    data = request.get_json(silent=True) or {}
    days_ahead = data.get('days_ahead', 3)

    try:
        from app.agents.collection_agent import CollectionAgent

        agent = CollectionAgent(tenant_id=tenant_id)
        result = agent.run_batch(days_ahead=int(days_ahead))

        return jsonify({
            'success': result.success,
            'summary': result.text if result.success else result.error,
            'tokens': result.tokens_in + result.tokens_out,
            'price': result.price_charged,
            'tool_calls': result.tool_calls,
            'agent_type': result.agent_type,
        })

    except Exception as e:
        current_app.logger.exception(f'[CollectionAgent] error: {e}')
        return jsonify({
            'success': False,
            'error': f'حدث خطأ: {str(e)[:100]}',
        }), 500


# ================================================================
# 4. حالة الوكلاء وإعداداتهم
# ================================================================
@bp.route('/status', methods=['GET'])
@tenant_required
def agents_status():
    """حالة الوكلاء — النموذج المستخدم والرصيد والتوفر."""
    tenant_id = _get_tenant_id()
    if not tenant_id:
        return jsonify({'error': 'غير مصرح'}), 401

    try:
        from app.agents.model_resolver import ModelResolver
        from app.services.pricing_service import PricingService

        resolved = ModelResolver.resolve(tenant_id)
        balance = PricingService.get_tenant_balance(tenant_id)

        return jsonify({
            'ai_available': resolved is not None,
            'model': {
                'provider': resolved.provider if resolved else None,
                'model_name': resolved.display_name if resolved else None,
                'model_id': resolved.model_id if resolved else None,
                'is_tenant_key': resolved.is_tenant_key if resolved else False,
                'price_per_message': resolved.price_per_message if resolved else 0,
            } if resolved else None,
            'wallet': balance,
            'agents': {
                'front_desk': {'name': 'وكيل الاستقبال', 'status': 'active' if resolved else 'unavailable'},
                'collection': {'name': 'وكيل التحصيل', 'status': 'active' if resolved else 'unavailable'},
                'manager': {'name': 'المستشار المالي', 'status': 'active' if resolved else 'unavailable'},
            },
        })

    except Exception as e:
        current_app.logger.exception(f'[AgentStatus] error: {e}')
        return jsonify({'error': str(e)[:100]}), 500

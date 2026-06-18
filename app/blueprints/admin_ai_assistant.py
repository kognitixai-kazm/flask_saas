"""
app/blueprints/admin_ai_assistant.py — مساعد ذكي للسوبر أدمن (/sa/ai-assistant).

- ينادي السوبر أدمن بـ "يا ريّس" ويرحب به.
- يجمع إحصائيات حية (مستأجرون، اشتراكات، رسائل، تكلفة) ويُمرّرها كسياق.
- يُرسل سؤال الأدمن إلى نموذج OpenAI (إن توفر مفتاح صالح) ويعيد الردّ.
- لا يخزّن مفاتيح ولا أسئلة في القاعدة — حواري فقط.
"""
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, g, current_app
from sqlalchemy import func

from app.decorators import super_admin_required
from app.extensions import db
from app.models.tenant import Tenant
from app.models.subscription import Subscription
from app.models.conversation import Conversation, Message
from app.models.audit_log import AuditLog
from app.models.system_settings import SystemSetting
from app.models.ai_model import AIModel
from app.services.ai_service import AIService

bp = Blueprint('admin_ai', __name__)


# ----------------------------------------------------------------------------
# جمع إحصائيات المنصة (سياق سريع للمساعد)
# ----------------------------------------------------------------------------
def _platform_snapshot() -> dict:
    """يبني صورة مختصرة عن الحالة الحالية للمنصة."""
    today = datetime.utcnow().date()
    today_start = datetime(today.year, today.month, today.day)
    week_start = today_start - timedelta(days=7)

    total_tenants = Tenant.query.count()
    active_tenants = Tenant.query.filter_by(status='active').count()
    pending_tenants = Tenant.query.filter_by(status='pending').count()
    suspended_tenants = Tenant.query.filter_by(status='suspended').count()

    trial_subs = Subscription.query.filter_by(status='trial').count()
    active_subs = Subscription.query.filter_by(status='active').count()
    pending_subs = Subscription.query.filter_by(status='pending_approval').count()

    new_tenants_today = Tenant.query.filter(Tenant.created_at >= today_start).count()
    new_tenants_week = Tenant.query.filter(Tenant.created_at >= week_start).count()

    total_conversations = Conversation.query.count()
    total_messages = Message.query.count()
    msgs_today = Message.query.filter(Message.created_at >= today_start).count() if hasattr(Message, 'created_at') else 0
    msgs_week = Message.query.filter(Message.created_at >= week_start).count() if hasattr(Message, 'created_at') else 0

    # تكلفة تقريبية (إن وُجد جدول استخدام)
    estimated_cost = 0.0
    estimated_revenue = 0.0
    try:
        from app.models.message_usage import MessageUsage
        rows = MessageUsage.query.filter(MessageUsage.created_at >= week_start).all()
        for r in rows:
            estimated_cost += float(getattr(r, 'cost_actual', 0) or 0)
            estimated_revenue += float(getattr(r, 'price_charged', 0) or 0)
    except Exception:
        pass

    # آخر النشاطات
    recent_logs = (AuditLog.query
                   .order_by(AuditLog.created_at.desc())
                   .limit(8)
                   .all())
    log_lines = []
    for lg in recent_logs:
        ts = lg.created_at.strftime('%m-%d %H:%M') if lg.created_at else ''
        log_lines.append(f'- [{ts}] {lg.actor_type}: {lg.action}')

    # مزوّد AI الافتراضي
    default_model = AIModel.query.filter_by(is_default=True, is_active=True).first()

    return {
        'tenants': {
            'total': total_tenants,
            'active': active_tenants,
            'pending': pending_tenants,
            'suspended': suspended_tenants,
            'new_today': new_tenants_today,
            'new_week': new_tenants_week,
        },
        'subscriptions': {
            'trial': trial_subs,
            'active': active_subs,
            'pending_approval': pending_subs,
        },
        'messaging': {
            'conversations': total_conversations,
            'messages_total': total_messages,
            'messages_today': msgs_today,
            'messages_week': msgs_week,
        },
        'finance_week': {
            'cost': round(estimated_cost, 2),
            'revenue': round(estimated_revenue, 2),
            'margin': round(estimated_revenue - estimated_cost, 2),
        },
        'ai_model': {
            'provider': default_model.provider if default_model else '',
            'model': default_model.model_id if default_model else '',
            'display_name': default_model.display_name if default_model else '',
        },
        'recent_activity': log_lines,
    }


def _format_snapshot_for_prompt(snap: dict) -> str:
    t = snap['tenants']
    s = snap['subscriptions']
    m = snap['messaging']
    f = snap['finance_week']
    a = snap['ai_model']

    lines = [
        f"المستأجرون: إجمالي {t['total']} | فعّال {t['active']} | بانتظار الموافقة {t['pending']} | موقوف {t['suspended']}",
        f"جدد اليوم: {t['new_today']} | جدد الأسبوع: {t['new_week']}",
        f"الاشتراكات: تجريبي {s['trial']} | نشط {s['active']} | بانتظار الموافقة {s['pending_approval']}",
        f"الرسائل: إجمالي {m['messages_total']} | اليوم {m['messages_today']} | الأسبوع {m['messages_week']} | محادثات {m['conversations']}",
        f"الأسبوع: تكلفة {f['cost']} ر.س | إيراد {f['revenue']} ر.س | هامش {f['margin']} ر.س",
        f"نموذج AI الافتراضي: {a['display_name'] or 'غير معيّن'} ({a['provider']}/{a['model']})",
    ]
    if snap['recent_activity']:
        lines.append('آخر النشاطات:')
        lines.extend(snap['recent_activity'])
    return '\n'.join(lines)


# ----------------------------------------------------------------------------
# Endpoint: snapshot (للوحة الحيّة)
# ----------------------------------------------------------------------------
@bp.route('/snapshot', methods=['GET'])
@super_admin_required
def snapshot():
    return jsonify({'ok': True, 'data': _platform_snapshot()})


# ----------------------------------------------------------------------------
# Endpoint: ask (سؤال نصي للأدمن)
# ----------------------------------------------------------------------------
@bp.route('/ask', methods=['POST'])
@super_admin_required
def ask():
    data = request.get_json(silent=True) or {}
    question = (data.get('question') or '').strip()
    if not question:
        return jsonify({'ok': False, 'error': 'سؤال فارغ'}), 400
    if len(question) > 500:
        question = question[:500]

    snap = _platform_snapshot()
    snap_text = _format_snapshot_for_prompt(snap)

    admin_username = (g.current_admin.username if g.current_admin else 'الريّس')

    system_prompt = (
        "أنت مساعد KOGNITIX الذكي للسوبر أدمن في لوحة تحكم المنصة.\n"
        f"الذي يحدّثك هو مدير المنصة ({admin_username}). نادِه دائماً بـ \"يا ريّس\".\n"
        "أسلوبك: عربي فصيح بسيط، قصير ومباشر، بدون مصطلحات تقنية ثقيلة وبدون رموز برمجية.\n"
        "لا تفترض معلومات غير موجودة في السياق — إذا كان السؤال يحتاج بياناً غير موجود، قل ذلك بأدب.\n"
        "صيغة الرد: جملة استهلالية قصيرة (مثل: أبشر يا ريّس) ثم الرقم/الجواب ثم نصيحة عملية إن لزم.\n"
        "لا تتجاوز 6 أسطر. لا تستخدم قوائم طويلة. لا تذكر اسم النموذج أو أنك ذكاء اصطناعي.\n"
        "يمنع كشف أسرار: لا تذكر مفاتيح API ولا قيم متغيرات البيئة.\n"
        "السياق الحالي للمنصة:\n"
        f"{snap_text}"
    )

    # تحقّق من توفر مفتاح OpenAI
    model = AIService.get_tenant_model(0)
    if not model:
        return jsonify({
            'ok': True,
            'fallback': True,
            'reply': _heuristic_answer(question, snap),
            'snapshot': snap,
        })

    api_key = AIService._get_api_key(model.provider, tenant_id=None)
    if not api_key:
        return jsonify({
            'ok': True,
            'fallback': True,
            'reply': _heuristic_answer(question, snap),
            'snapshot': snap,
        })

    valid, _why = AIService.validate_api_key(model.provider, api_key)
    if not valid:
        return jsonify({
            'ok': True,
            'fallback': True,
            'reply': _heuristic_answer(question, snap),
            'snapshot': snap,
        })

    try:
        result = AIService.generate(
            tenant_id=0,
            user_message=question,
            system_prompt=system_prompt,
            history=[],
            model_override=model,
        )
    except Exception as e:
        current_app.logger.warning(f'[admin_ai] generate failed: {e}')
        return jsonify({
            'ok': True,
            'fallback': True,
            'reply': _heuristic_answer(question, snap),
            'snapshot': snap,
        })

    if not result.success or not (result.text or '').strip():
        return jsonify({
            'ok': True,
            'fallback': True,
            'reply': _heuristic_answer(question, snap),
            'snapshot': snap,
        })

    return jsonify({
        'ok': True,
        'fallback': False,
        'reply': result.text.strip(),
        'snapshot': snap,
    })


# ----------------------------------------------------------------------------
# ردّ احتياطي (بدون AI) — يعتمد على snapshot بشكل ذكي
# ----------------------------------------------------------------------------
def _heuristic_answer(q: str, snap: dict) -> str:
    qn = (q or '').strip().lower()
    t = snap['tenants']
    s = snap['subscriptions']
    m = snap['messaging']
    f = snap['finance_week']

    has = lambda *xs: any(x in qn for x in xs)

    if has('مرحب', 'اهلا', 'هلا', 'سلام', 'hello', 'hi'):
        return f"أهلاً يا ريّس. عندنا {t['active']} نشاط فعّال و{t['pending']} طلب بانتظار موافقتك."
    if has('مستأجر', 'تجار', 'انشطة', 'نشاط', 'tenants'):
        return (f"يا ريّس، إجمالي المستأجرين {t['total']}؛ منهم {t['active']} فعّال، "
                f"و{t['pending']} بانتظار الموافقة. جدد اليوم: {t['new_today']}.")
    if has('طلب', 'طلبات', 'موافق', 'pending'):
        return (f"يا ريّس، عندك {s['pending_approval']} طلب اشتراك بانتظار الموافقة "
                f"(ومن المستأجرين {t['pending']} حساباً معلّقاً).")
    if has('تكلف', 'إيراد', 'دخل', 'هامش', 'فلوس', 'cost', 'revenue'):
        return (f"يا ريّس (آخر 7 أيام): تكلفة {f['cost']} ر.س، إيراد {f['revenue']} ر.س، "
                f"هامش صافي {f['margin']} ر.س.")
    if has('رسائل', 'محادث', 'messages'):
        return (f"يا ريّس: محادثات {m['conversations']}، رسائل اليوم {m['messages_today']}، "
                f"الأسبوع {m['messages_week']}، الإجمالي {m['messages_total']}.")
    if has('اشتراك', 'تجريب', 'subscription'):
        return (f"يا ريّس: نشطة {s['active']}، تجريبية {s['trial']}، "
                f"بانتظار الموافقة {s['pending_approval']}.")

    return (f"أبشر يا ريّس. لمحة سريعة: {t['active']} نشاط فعّال، "
            f"{s['pending_approval']} طلب بانتظار الموافقة، "
            f"رسائل اليوم {m['messages_today']}.")

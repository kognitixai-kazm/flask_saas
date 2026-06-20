"""
app/blueprints/notifications_api.py — API للإشعارات و Web Push
يوفّر endpoints لـ:
  - الاشتراك في Push Notifications
  - جلب الإشعارات
  - تعليم إشعار كمقروء
  - عدد الإشعارات غير المقروءة (Polling)
"""
from flask import Blueprint, request, jsonify, g, session
from app.extensions import db, csrf
from app.decorators import tenant_required
from app.models.push_subscription import PushSubscription
from app.utils.notification_service import NotificationService

bp = Blueprint('notifications_api', __name__)


# =====================
# تحديد هوية المستخدم الحالي
# =====================
def _current_user_info():
    """إرجاع (user_type, user_id) للمستخدم الحالي."""
    # لوحة التاجر
    if hasattr(g, 'current_tenant') and g.current_tenant:
        return 'tenant', g.current_tenant.id

    # لوحة السوبر أدمن
    sa = g.get('current_admin') or g.get('current_super_admin')
    if sa:
        return 'admin', sa.id

    # من الجلسة
    if session.get('tenant_id'):
        return 'tenant', session['tenant_id']
    if session.get('sa_id'):
        return 'admin', session['sa_id']

    return None, None


# =====================
# Push Subscription
# =====================
@bp.route('/push/subscribe', methods=['POST'])
@csrf.exempt
def push_subscribe():
    """اشتراك جهاز في Push Notifications."""
    user_type, user_id = _current_user_info()
    if not user_type:
        return jsonify({'error': 'unauthorized'}), 401

    data = request.get_json(silent=True) or {}
    endpoint = data.get('endpoint', '')
    keys = data.get('keys', {})
    p256dh = keys.get('p256dh', '')
    auth = keys.get('auth', '')

    if not endpoint or not p256dh or not auth:
        return jsonify({'error': 'missing subscription data'}), 400

    # تحقق من عدم التكرار
    existing = PushSubscription.query.filter_by(
        user_type=user_type,
        user_id=user_id,
        endpoint=endpoint,
    ).first()

    if existing:
        existing.p256dh_key = p256dh
        existing.auth_key = auth
        existing.is_active = True
        existing.user_agent = request.headers.get('User-Agent', '')[:500]
    else:
        sub = PushSubscription(
            user_type=user_type,
            user_id=user_id,
            endpoint=endpoint,
            p256dh_key=p256dh,
            auth_key=auth,
            user_agent=request.headers.get('User-Agent', '')[:500],
        )
        db.session.add(sub)

    db.session.commit()
    return jsonify({'success': True})


# =====================
# جلب الإشعارات
# =====================
@bp.route('/list')
def list_notifications():
    """إرجاع آخر 20 إشعار للمستخدم الحالي."""
    user_type, user_id = _current_user_info()
    if not user_type:
        return jsonify({'error': 'unauthorized'}), 401

    notifications = NotificationService.get_recent(user_type, user_id, limit=20)
    return jsonify({
        'notifications': [n.to_dict() for n in notifications],
        'unread_count': NotificationService.get_unread_count(user_type, user_id),
    })


# =====================
# عدد غير المقروء (Polling)
# =====================
@bp.route('/unread-count')
def unread_count():
    """إرجاع عدد الإشعارات غير المقروءة."""
    user_type, user_id = _current_user_info()
    if not user_type:
        return jsonify({'count': 0})
    return jsonify({
        'count': NotificationService.get_unread_count(user_type, user_id),
    })


# =====================
# تعليم كمقروء
# =====================
@bp.route('/read/<int:notif_id>', methods=['POST'])
@csrf.exempt
def mark_read(notif_id):
    """تعليم إشعار واحد كمقروء."""
    user_type, user_id = _current_user_info()
    if not user_type:
        return jsonify({'error': 'unauthorized'}), 401

    ok = NotificationService.mark_as_read(notif_id, user_type, user_id)
    return jsonify({'success': ok})


@bp.route('/read-all', methods=['POST'])
@csrf.exempt
def mark_all_read():
    """تعليم جميع الإشعارات كمقروءة."""
    user_type, user_id = _current_user_info()
    if not user_type:
        return jsonify({'error': 'unauthorized'}), 401

    count = NotificationService.mark_all_read(user_type, user_id)
    return jsonify({'success': True, 'marked': count})

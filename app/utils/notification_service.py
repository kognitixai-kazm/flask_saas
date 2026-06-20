"""
app/utils/notification_service.py — خدمة الإشعارات المركزية
يوفّر واجهة موحّدة لإنشاء الإشعارات + إرسال Push Notifications + تشغيل الصوت.
"""
import json
import logging
from flask import current_app
from app.extensions import db
from app.models.notification import Notification
from app.models.push_subscription import PushSubscription

logger = logging.getLogger(__name__)


class NotificationService:
    """خدمة إنشاء وإرسال الإشعارات."""

    # =====================
    # إنشاء إشعار + إرسال Push
    # =====================
    @staticmethod
    def notify_tenant(tenant_id: int, category: str, title: str,
                      body: str = '', action_url: str = '', icon: str = '🔔'):
        """إنشاء إشعار للتاجر + إرسال Web Push."""
        notif = Notification(
            recipient_type='tenant',
            recipient_id=tenant_id,
            category=category,
            title=title,
            body=body,
            action_url=action_url,
            icon=icon,
        )
        db.session.add(notif)
        db.session.commit()

        # إرسال Push في الخلفية
        NotificationService._send_push('tenant', tenant_id, notif)
        return notif

    @staticmethod
    def notify_admin(category: str, title: str,
                     body: str = '', action_url: str = '', icon: str = '🔔'):
        """إنشاء إشعار لجميع مدراء المنصة + إرسال Web Push."""
        from app.models.super_admin import SuperAdmin
        admins = SuperAdmin.query.filter_by(is_active=True).all()
        notifications = []
        for admin in admins:
            notif = Notification(
                recipient_type='admin',
                recipient_id=admin.id,
                category=category,
                title=title,
                body=body,
                action_url=action_url,
                icon=icon,
            )
            db.session.add(notif)
            notifications.append((admin.id, notif))

        db.session.commit()

        for admin_id, notif in notifications:
            NotificationService._send_push('admin', admin_id, notif)

        return notifications

    # =====================
    # إرسال Web Push Notification
    # =====================
    @staticmethod
    def _send_push(user_type: str, user_id: int, notif: Notification):
        """إرسال Web Push لجميع أجهزة المستخدم المشتركة."""
        try:
            from pywebpush import webpush, WebPushException

            vapid_private = current_app.config.get('VAPID_PRIVATE_KEY', '')
            vapid_email = current_app.config.get('VAPID_CLAIMS_EMAIL', '')

            if not vapid_private or not vapid_email:
                logger.warning('[Push] VAPID keys not configured, skipping push')
                return

            subs = PushSubscription.query.filter_by(
                user_type=user_type,
                user_id=user_id,
                is_active=True,
            ).all()

            if not subs:
                return

            payload = json.dumps({
                'title': notif.title,
                'body': notif.body,
                'icon': notif.icon,
                'url': notif.action_url or '/',
                'category': notif.category,
                'notif_id': notif.id,
            }, ensure_ascii=False)

            for sub in subs:
                try:
                    webpush(
                        subscription_info=sub.to_subscription_info(),
                        data=payload,
                        vapid_private_key=vapid_private,
                        vapid_claims={'sub': f'mailto:{vapid_email}'},
                        timeout=10,
                    )
                except WebPushException as e:
                    # إذا كان الاشتراك منتهي الصلاحية، نلغيه
                    if hasattr(e, 'response') and e.response is not None:
                        status = e.response.status_code
                        if status in (404, 410):
                            sub.is_active = False
                            db.session.commit()
                            logger.info(f'[Push] Removed expired subscription {sub.id}')
                        else:
                            logger.warning(f'[Push] WebPush error {status}: {e}')
                    else:
                        logger.warning(f'[Push] WebPush error: {e}')
                except Exception as e:
                    logger.warning(f'[Push] Unexpected push error: {e}')

        except ImportError:
            logger.warning('[Push] pywebpush not installed, skipping push notifications')
        except Exception as e:
            logger.warning(f'[Push] Push service error: {e}')

    # =====================
    # جلب الإشعارات
    # =====================
    @staticmethod
    def get_unread_count(recipient_type: str, recipient_id: int) -> int:
        return Notification.query.filter_by(
            recipient_type=recipient_type,
            recipient_id=recipient_id,
            is_read=False,
        ).count()

    @staticmethod
    def get_recent(recipient_type: str, recipient_id: int, limit: int = 20):
        return Notification.query.filter_by(
            recipient_type=recipient_type,
            recipient_id=recipient_id,
        ).order_by(Notification.created_at.desc()).limit(limit).all()

    @staticmethod
    def mark_as_read(notification_id: int, recipient_type: str, recipient_id: int) -> bool:
        notif = Notification.query.filter_by(
            id=notification_id,
            recipient_type=recipient_type,
            recipient_id=recipient_id,
        ).first()
        if notif:
            notif.mark_read()
            db.session.commit()
            return True
        return False

    @staticmethod
    def mark_all_read(recipient_type: str, recipient_id: int) -> int:
        count = Notification.query.filter_by(
            recipient_type=recipient_type,
            recipient_id=recipient_id,
            is_read=False,
        ).update({'is_read': True})
        db.session.commit()
        return count

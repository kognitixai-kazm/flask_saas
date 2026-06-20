"""
app/services/tenant_service.py — إنشاء وإدارة المستأجرين.
"""
from datetime import datetime, timedelta
from flask import current_app

from app.extensions import db
from app.models.tenant import Tenant
from app.models.subscription import Subscription
from app.models.plan import Plan
from app.utils.slug import generate_tenant_slug
from app.utils.tokens import SetupTokenManager
from app.services.audit_service import AuditService
from app.services.email_service import EmailService


def _resolve_default_plan() -> Plan:
    """جلب باقة افتراضية لطلبات الانضمام (الأولوية: trial → أول باقة فعّالة)."""
    p = Plan.query.filter_by(code='trial', status='active').first()
    if p:
        return p
    return Plan.query.filter_by(status='active').order_by(Plan.sort_order).first()


class TenantService:
    """منطق أعمال المستأجرين."""

    @staticmethod
    def create_tenant(
        business_name: str,
        owner_full_name: str,
        owner_email: str,
        owner_phone: str,
        activity_id: int,
        plan_id: int,
    ) -> tuple[Tenant, str, bool]:
        """
        إنشاء tenant جديد (حالة pending) + اشتراك تجريبي + setup token.
        يرجع (tenant, setup_url, setup_email_sent).
        setup_email_sent = True فقط عند MAIL_ENABLED ونجاح إرسال البريد.
        """
        # توليد slug فريد
        slug = generate_tenant_slug()
        while Tenant.query.filter_by(slug=slug).first():
            slug = generate_tenant_slug()

        # إنشاء Tenant
        tenant = Tenant(
            slug=slug,
            business_name=business_name,
            owner_full_name=owner_full_name,
            owner_email=owner_email,
            owner_phone=owner_phone,
            activity_id=activity_id,
            plan_id=plan_id,
            status='pending',
            setup_completed=False,
        )
        db.session.add(tenant)
        db.session.flush()  # للحصول على ID

        # إنشاء Subscription (تجريبي)
        plan = Plan.query.get(plan_id)
        trial_days = plan.trial_days if plan else 14

        subscription = Subscription(
            tenant_id=tenant.id,
            plan_id=plan_id,
            status='trial',
            trial_ends_at=datetime.utcnow() + timedelta(days=trial_days),
            ends_at=datetime.utcnow() + timedelta(days=trial_days),
        )
        db.session.add(subscription)
        db.session.commit()

        # توليد setup URL
        setup_url = SetupTokenManager.build_setup_url(tenant.id)

        setup_email_sent = EmailService.send_tenant_setup_link(
            to_email=owner_email,
            owner_name=owner_full_name,
            business_name=business_name,
            setup_url=setup_url,
        )

        # Log
        AuditService.log(
            actor_type='system',
            action='tenant_created',
            tenant_id=tenant.id,
            target=f'tenant:{tenant.id}',
            extra_data={'slug': slug, 'plan_id': plan_id},
        )

        if setup_email_sent:
            current_app.logger.info(
                f'Setup link emailed to {owner_email} (tenant id={tenant.id}, slug={slug})'
            )
        else:
            current_app.logger.info(
                f'\n'
                f'╔══════════════════════════════════════════╗\n'
                f'║  ✉️  SETUP LINK (عرض يدوي / بريد غير مفعّل) ║\n'
                f'║  Tenant: {business_name:<30s}  ║\n'
                f'║  Email:  {owner_email:<30s}  ║\n'
                f'╠══════════════════════════════════════════╣\n'
                f'║  {setup_url}\n'
                f'╚══════════════════════════════════════════╝'
            )

        return tenant, setup_url, setup_email_sent

    @staticmethod
    def request_subscription(
        business_name: str,
        owner_full_name: str,
        owner_email: str,
        owner_phone: str,
        activity_id: int,
    ):
        """تسجيل «طلب وصول» للمنصة بانتظار موافقة الأدمن.

        النتيجة: Tenant بحالة pending + Subscription بحالة pending_approval،
        دون إرسال رابط الإعداد للعميل (يُرسَل عند الموافقة من الأدمن).
        """
        plan = _resolve_default_plan()
        if not plan:
            raise RuntimeError('لا توجد باقة فعّالة. أنشئ باقة من لوحة الأدمن أولاً.')

        slug = generate_tenant_slug()
        while Tenant.query.filter_by(slug=slug).first():
            slug = generate_tenant_slug()

        tenant = Tenant(
            slug=slug,
            business_name=business_name,
            owner_full_name=owner_full_name,
            owner_email=owner_email,
            owner_phone=owner_phone,
            activity_id=activity_id,
            plan_id=plan.id,
            status='pending',
            setup_completed=False,
            activity_data={'pending_admin_approval': True, 'requested_at': datetime.utcnow().isoformat()},
        )
        db.session.add(tenant)
        db.session.flush()

        subscription = Subscription(
            tenant_id=tenant.id,
            plan_id=plan.id,
            status='pending_approval',
            trial_ends_at=None,
            ends_at=None,
        )
        db.session.add(subscription)
        db.session.commit()

        AuditService.log(
            actor_type='system',
            action='tenant_subscription_requested',
            tenant_id=tenant.id,
            target=f'tenant:{tenant.id}',
            extra_data={'slug': slug, 'plan_id': plan.id},
        )
        current_app.logger.info(
            f'[TenantService] subscription request slug={slug} email={owner_email}'
        )

        # ===== إشعار للسوبر أدمن =====
        try:
            from app.utils.notification_service import NotificationService
            NotificationService.notify_admin(
                category='new_tenant',
                title='طلب اشتراك جديد 🏢',
                body=f'{business_name} — {owner_full_name} ({owner_email})',
                action_url='/sa/',
                icon='🏢',
            )
        except Exception as e:
            current_app.logger.warning(f'[Notification] new tenant notify error: {e}')

        return tenant

    @staticmethod
    def approve_request(tenant_id: int) -> tuple[bool, str]:
        """يوافق الأدمن على طلب الاشتراك → يُفعّل التجربة ويُنشئ حساب المالك ويُرسل بيانات الدخول."""
        from app.services.auth_service import AuthService
        import secrets
        from flask import url_for

        tenant = Tenant.query.get(tenant_id)
        if not tenant:
            return False, 'المستأجر غير موجود'

        sub = tenant.subscription
        plan = (sub.plan if sub else None) or _resolve_default_plan()
        if not plan:
            return False, 'لا توجد باقة لربط الاشتراك بها'

        trial_days = plan.trial_days or 14
        now = datetime.utcnow()
        ends_at = now + timedelta(days=trial_days)

        if sub:
            sub.plan_id = plan.id
            sub.status = 'trial'
            sub.started_at = now
            sub.trial_ends_at = ends_at
            sub.ends_at = ends_at
        else:
            sub = Subscription(
                tenant_id=tenant.id,
                plan_id=plan.id,
                status='trial',
                trial_ends_at=ends_at,
                ends_at=ends_at,
            )
            db.session.add(sub)

        ad = dict(tenant.activity_data or {})
        ad.pop('pending_admin_approval', None)
        ad['approved_at'] = now.isoformat()
        tenant.activity_data = ad
        
        # إنشاء حساب مالك المنشأة إذا لم يكن موجوداً
        from app.models.tenant_user import TenantUser
        existing_owner = TenantUser.query.filter_by(tenant_id=tenant.id, role='owner').first()
        
        username = tenant.slug.replace('-', '_')
        password = secrets.token_urlsafe(8)
        
        if not existing_owner:
            # التحقق من عدم تكرار اسم المستخدم، إذا كان مكرراً نضيف أرقام
            base_username = username
            counter = 1
            while TenantUser.query.filter_by(tenant_id=tenant.id, username=username).first():
                username = f"{base_username}{counter}"
                counter += 1

            AuthService.create_tenant_user(
                tenant_id=tenant.id,
                username=username,
                email=tenant.owner_email,
                password=password,
                full_name=tenant.owner_full_name,
                phone=tenant.owner_phone,
                role='owner',
            )

        # استكمال إعداد التاجر
        tenant.status = 'active'
        tenant.setup_completed = True
        db.session.commit()

        login_url = current_app.config.get('SITE_URL', '').rstrip('/') + '/app/login'
        sent = EmailService.send_tenant_approval_credentials(
            to_email=tenant.owner_email,
            owner_name=tenant.owner_full_name,
            business_name=tenant.business_name,
            username=username,
            password=password,
            login_url=login_url,
        )

        AuditService.log(
            actor_type='super_admin',
            action='tenant_subscription_approved',
            tenant_id=tenant.id,
            target=f'tenant:{tenant.id}',
            extra_data={'email_sent': bool(sent), 'login_url': login_url},
        )
        return True, login_url

    @staticmethod
    def reject_request(tenant_id: int, reason: str = '') -> bool:
        """رفض طلب اشتراك (يُعلَّق المستأجر)."""
        tenant = Tenant.query.get(tenant_id)
        if not tenant:
            return False
        tenant.status = 'cancelled'
        if tenant.subscription:
            tenant.subscription.status = 'cancelled'
        ad = dict(tenant.activity_data or {})
        ad.pop('pending_admin_approval', None)
        if reason:
            ad['rejected_reason'] = reason[:300]
        tenant.activity_data = ad
        db.session.commit()
        AuditService.log(
            actor_type='super_admin',
            action='tenant_subscription_rejected',
            tenant_id=tenant.id,
            target=f'tenant:{tenant.id}',
            extra_data={'reason': reason[:300]},
        )
        return True

    @staticmethod
    def complete_setup(tenant_id: int) -> bool:
        """تحديث حالة الـ tenant بعد إكمال الإعداد."""
        tenant = Tenant.query.get(tenant_id)
        if not tenant:
            return False
        tenant.status = 'active'
        tenant.setup_completed = True
        db.session.commit()

        AuditService.log(
            actor_type='tenant_user',
            action='setup_completed',
            tenant_id=tenant_id,
        )
        return True

    @staticmethod
    def suspend_tenant(tenant_id: int) -> bool:
        """تعليق مستأجر (من الأدمن)."""
        tenant = Tenant.query.get(tenant_id)
        if not tenant:
            return False
        tenant.status = 'suspended'
        db.session.commit()
        AuditService.log(
            actor_type='super_admin',
            action='tenant_suspended',
            tenant_id=tenant_id,
        )
        return True

    @staticmethod
    def activate_tenant(tenant_id: int) -> bool:
        """إعادة تفعيل مستأجر معلّق."""
        tenant = Tenant.query.get(tenant_id)
        if not tenant:
            return False
        tenant.status = 'active'
        db.session.commit()
        AuditService.log(
            actor_type='super_admin',
            action='tenant_activated',
            tenant_id=tenant_id,
        )
        return True

    @staticmethod
    def get_dashboard_stats(tenant: Tenant) -> dict:
        """إحصائيات سريعة للوحة العميل."""
        from app.models.conversation import Conversation, Message
        conv_count = Conversation.query.filter_by(tenant_id=tenant.id).count()
        msg_count = Message.query.filter_by(tenant_id=tenant.id).count()

        stats = {
            'conversations_count': conv_count,
            'messages_count': msg_count,
            'users_count': tenant.users.count(),
            'subscription': tenant.subscription.to_dict() if tenant.subscription else None,
        }
        return stats

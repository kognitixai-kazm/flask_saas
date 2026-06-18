"""
app/services/plan_service.py — إدارة الباقات + بيانات أولية.
"""
from app.extensions import db
from app.models.plan import Plan


class PlanService:

    @staticmethod
    def seed_defaults():
        """بيانات أولية للباقات (تُنفّذ مرة واحدة عبر flask init-db)."""
        from app.models.plan import PlanPricing, PlanLimit, PlanAgent, PlanModule
        defaults = [
            {
                'code': 'trial',
                'name_ar': 'تجربة مجانية',
                'name_en': 'Free Trial',
                'description': 'جرّب المنصة لمدة 14 يوم مجاناً',
                'price_monthly': 0,
                'price_yearly': 0,
                'max_chats_per_month': 100,
                'max_users': 1,
                'max_branches': 1,
                'features': {'whatsapp': False, 'analytics': False, 'custom_branding': False},
                'trial_days': 14,
                'is_active': True,
                'is_featured': False,
                'sort_order': 0,
            },
            {
                'code': 'basic',
                'name_ar': 'الأساسية',
                'name_en': 'Basic',
                'description': 'للأنشطة الصغيرة',
                'price_monthly': 99,
                'price_yearly': 990,
                'max_chats_per_month': 1000,
                'max_users': 2,
                'max_branches': 1,
                'features': {'whatsapp': False, 'analytics': True, 'custom_branding': False},
                'trial_days': 14,
                'is_active': True,
                'is_featured': False,
                'sort_order': 1,
            },
            {
                'code': 'pro',
                'name_ar': 'الاحترافية',
                'name_en': 'Pro',
                'description': 'للأنشطة المتوسطة والكبيرة',
                'price_monthly': 249,
                'price_yearly': 2490,
                'max_chats_per_month': 5000,
                'max_users': 5,
                'max_branches': 3,
                'features': {'whatsapp': True, 'analytics': True, 'custom_branding': True},
                'trial_days': 14,
                'is_active': True,
                'is_featured': True,
                'sort_order': 2,
            },
            {
                'code': 'enterprise',
                'name_ar': 'المؤسسية',
                'name_en': 'Enterprise',
                'description': 'للشركات الكبيرة',
                'price_monthly': 599,
                'price_yearly': 5990,
                'max_chats_per_month': 20000,
                'max_users': 20,
                'max_branches': 10,
                'features': {'whatsapp': True, 'analytics': True, 'custom_branding': True, 'priority_support': True},
                'trial_days': 14,
                'is_active': True,
                'is_featured': False,
                'sort_order': 3,
            },
        ]

        for data in defaults:
            if not Plan.query.filter_by(code=data['code']).first():
                plan = Plan(
                    code=data['code'],
                    name_ar=data['name_ar'],
                    name_en=data['name_en'],
                    description_ar=data['description'],
                    description_en=data['description'],
                    status='active' if data['is_active'] else 'draft',
                    is_popular=data['is_featured'],
                    sort_order=data['sort_order'],
                    trial_days=data['trial_days'],
                )
                db.session.add(plan)
                db.session.flush()

                plan.pricing = PlanPricing(
                    plan_id=plan.id,
                    price_monthly=data['price_monthly'],
                    price_yearly=data['price_yearly']
                )

                plan.limits = PlanLimit(
                    plan_id=plan.id,
                    max_users=data['max_users'],
                    max_branches=data['max_branches']
                )

                agent = PlanAgent(
                    plan_id=plan.id,
                    agent_type='chat',
                    is_enabled=True,
                    monthly_usage_limit=data['max_chats_per_month']
                )
                db.session.add(agent)

                for feat_key, is_enabled in data['features'].items():
                    mod = PlanModule(plan_id=plan.id, module_name=feat_key, is_enabled=is_enabled)
                    db.session.add(mod)

        db.session.commit()

    @staticmethod
    def get_active_plans(include_trial=False):
        """الباقات المتاحة للعرض."""
        q = Plan.query.filter_by(status='active')
        if not include_trial:
            q = q.filter(Plan.code != 'trial')
        return q.order_by(Plan.sort_order).all()

    @staticmethod
    def change_plan(tenant_id: int, new_plan_id: int) -> bool:
        """تغيير باقة المستأجر."""
        from app.models.subscription import Subscription
        from app.services.audit_service import AuditService

        sub = Subscription.query.filter_by(tenant_id=tenant_id).first()
        if not sub:
            return False

        old_plan_id = sub.plan_id
        sub.plan_id = new_plan_id
        sub.status = 'active'
        db.session.commit()

        AuditService.log(
            actor_type='tenant_user',
            action='plan_changed',
            tenant_id=tenant_id,
            extra_data={'old_plan_id': old_plan_id, 'new_plan_id': new_plan_id},
        )
        return True

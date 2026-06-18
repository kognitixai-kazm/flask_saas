"""
app/models/message_usage.py — تتبع استخدام كل خدمة لكل تاجر.

كل رسالة/صورة/صوت يُسجَّل هنا مع:
- نوع الخدمة (text/image/audio/ai)
- النموذج المستخدم (لو AI)
- السعر الذي خُصم من رصيد التاجر
- التكلفة الفعلية على المؤسس

الفائدة:
- التاجر يشوف استهلاكه التفصيلي
- المؤسس يشوف الإيرادات والربحية لكل تاجر/نموذج
"""
from datetime import datetime
from ..extensions import db


class MessageUsage(db.Model):
    """سجل استخدام لكل عملية."""
    __tablename__ = 'message_usage'

    id = db.Column(db.BigInteger, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)

    # نوع الخدمة (مرتبط بـ ServicePricing.service_key)
    # text_message | ai_message | image_send | audio_send | image_process | audio_process | whatsapp_message
    service_type = db.Column(db.String(50), nullable=False, index=True)

    # لو AI: ID النموذج المستخدم
    ai_model_id = db.Column(db.Integer, db.ForeignKey('ai_models.id'), nullable=True)

    # السعر المخصوم من التاجر
    price_charged = db.Column(db.Numeric(10, 4), default=0.0)

    # التكلفة الفعلية على المؤسس
    cost_actual = db.Column(db.Numeric(10, 4), default=0.0)

    # ربط بمحادثة/رسالة (اختياري)
    conversation_id = db.Column(db.Integer, db.ForeignKey('conversations.id', ondelete='SET NULL'), nullable=True)
    message_id = db.Column(db.Integer, nullable=True)

    # عدد الـ tokens (لو AI) — للتحليل
    tokens_in = db.Column(db.Integer, default=0)
    tokens_out = db.Column(db.Integer, default=0)

    # ملاحظات/extra
    extra = db.Column(db.JSON, default=dict)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # علاقات
    tenant = db.relationship('Tenant', backref=db.backref(
        'usage_records', lazy='dynamic', cascade='all, delete-orphan'))
    ai_model = db.relationship('AIModel', backref=db.backref('usage_records', lazy='dynamic'))

    def __repr__(self):
        return f'<Usage {self.service_type} tenant={self.tenant_id} price={self.price_charged}>'

    @staticmethod
    def record(
        tenant_id: int,
        service_type: str,
        price: float = 0.0,
        cost: float = 0.0,
        ai_model_id: int = None,
        conversation_id: int = None,
        message_id: int = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        extra: dict = None,
    ):
        """تسجيل استخدام جديد."""
        usage = MessageUsage(
            tenant_id=tenant_id,
            service_type=service_type,
            price_charged=price,
            cost_actual=cost,
            ai_model_id=ai_model_id,
            conversation_id=conversation_id,
            message_id=message_id,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            extra=extra or {},
        )
        db.session.add(usage)
        return usage

    @staticmethod
    def tenant_summary(tenant_id: int, days: int = 30):
        """ملخص استخدام التاجر."""
        from datetime import timedelta
        from sqlalchemy import func

        since = datetime.utcnow() - timedelta(days=days)
        q = db.session.query(
            MessageUsage.service_type,
            func.count(MessageUsage.id).label('count'),
            func.sum(MessageUsage.price_charged).label('total_spent'),
        ).filter(
            MessageUsage.tenant_id == tenant_id,
            MessageUsage.created_at >= since,
        ).group_by(MessageUsage.service_type).all()

        return [
            {
                'service_type': row.service_type,
                'count': row.count,
                'total_spent': float(row.total_spent or 0),
            }
            for row in q
        ]

    @staticmethod
    def tenant_total_spent(tenant_id: int, days: int = 30) -> float:
        """إجمالي المنصرف."""
        from datetime import timedelta
        from sqlalchemy import func

        since = datetime.utcnow() - timedelta(days=days)
        total = db.session.query(
            func.coalesce(func.sum(MessageUsage.price_charged), 0)
        ).filter(
            MessageUsage.tenant_id == tenant_id,
            MessageUsage.created_at >= since,
        ).scalar()
        return float(total or 0)

    @staticmethod
    def per_tenant_breakdown(days: int = 30, limit: int = 100):
        """تفصيل لكل تاجر: عدد رسائل AI + WhatsApp + إجمالي الاستهلاك.

        يستخدم في لوحة المنصة لعرض جدول استهلاك تفصيلي.
        """
        from datetime import timedelta
        from sqlalchemy import func, case
        from app.models.tenant import Tenant

        since = datetime.utcnow() - timedelta(days=days)

        ai_count = func.sum(case(
            (MessageUsage.service_type == 'ai_message', 1),
            else_=0,
        )).label('ai_count')
        ai_cost = func.sum(case(
            (MessageUsage.service_type == 'ai_message', MessageUsage.price_charged),
            else_=0,
        )).label('ai_cost')
        ai_tokens_in = func.sum(case(
            (MessageUsage.service_type == 'ai_message', MessageUsage.tokens_in),
            else_=0,
        )).label('ai_tokens_in')
        ai_tokens_out = func.sum(case(
            (MessageUsage.service_type == 'ai_message', MessageUsage.tokens_out),
            else_=0,
        )).label('ai_tokens_out')
        wa_count = func.sum(case(
            (MessageUsage.service_type == 'whatsapp_message', 1),
            else_=0,
        )).label('wa_count')
        wa_cost = func.sum(case(
            (MessageUsage.service_type == 'whatsapp_message', MessageUsage.price_charged),
            else_=0,
        )).label('wa_cost')
        total_cost = func.sum(MessageUsage.price_charged).label('total_cost')
        conv_count = func.count(func.distinct(MessageUsage.conversation_id)).label('conv_count')

        rows = (
            db.session.query(
                MessageUsage.tenant_id,
                ai_count, ai_cost, ai_tokens_in, ai_tokens_out,
                wa_count, wa_cost, total_cost, conv_count,
            )
            .filter(MessageUsage.created_at >= since)
            .group_by(MessageUsage.tenant_id)
            .order_by(total_cost.desc())
            .limit(limit)
            .all()
        )

        if not rows:
            return []

        tenant_ids = [r.tenant_id for r in rows]
        tenants_map = {
            t.id: t for t in Tenant.query.filter(Tenant.id.in_(tenant_ids)).all()
        }

        out = []
        for r in rows:
            t = tenants_map.get(r.tenant_id)
            if not t:
                continue
            out.append({
                'tenant_id': r.tenant_id,
                'tenant_name': t.business_name,
                'tenant_slug': t.slug,
                'ai_count': int(r.ai_count or 0),
                'ai_cost': float(r.ai_cost or 0),
                'ai_tokens': int((r.ai_tokens_in or 0) + (r.ai_tokens_out or 0)),
                'wa_count': int(r.wa_count or 0),
                'wa_cost': float(r.wa_cost or 0),
                'conv_count': int(r.conv_count or 0),
                'total_cost': float(r.total_cost or 0),
                'avg_per_conv': round(float(r.total_cost or 0) / max(int(r.conv_count or 1), 1), 3),
            })
        return out

    @staticmethod
    def admin_overview(days: int = 30):
        """نظرة عامة للمؤسس على كل التجار."""
        from datetime import timedelta
        from sqlalchemy import func

        since = datetime.utcnow() - timedelta(days=days)
        q = db.session.query(
            MessageUsage.tenant_id,
            func.count(MessageUsage.id).label('count'),
            func.sum(MessageUsage.price_charged).label('revenue'),
            func.sum(MessageUsage.cost_actual).label('cost'),
        ).filter(
            MessageUsage.created_at >= since,
        ).group_by(MessageUsage.tenant_id).all()

        result = []
        for row in q:
            revenue = float(row.revenue or 0)
            cost = float(row.cost or 0)
            result.append({
                'tenant_id': row.tenant_id,
                'count': row.count,
                'revenue': revenue,
                'cost': cost,
                'profit': revenue - cost,
                'margin_percent': round((revenue - cost) / revenue * 100, 1) if revenue > 0 else 0,
            })
        return result

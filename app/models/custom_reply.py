"""
app/models/custom_reply.py — ردود مخصصة لكل tenant.

نوعين:
1. manual = أنت أو التاجر أضفتها يدوياً
2. learned = النظام تعلّمها من ردود صاحب النشاط على الاستفسارات

الأولوية: ردود التاجر المخصصة ← الكلمات المفتاحية العامة ← AI ← استفسار
"""
from datetime import datetime
from ..extensions import db


class CustomReply(db.Model):
    """رد مخصص: كلمة/سؤال → جواب."""
    __tablename__ = 'custom_replies'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)

    # الكلمات المفتاحية أو السؤال (يمكن عدة كلمات مفصولة بفاصلة)
    # مثال: "جاكوزي,مسبح خاص,حوض سباحة"
    keywords = db.Column(db.Text, nullable=False)

    # الجواب
    reply_text = db.Column(db.Text, nullable=False)

    # نوع: manual (يدوي) | learned (تعلّم من استفسار)
    source = db.Column(db.String(20), default='manual', index=True)

    # إذا متعلّم — ID الاستفسار الأصلي
    inquiry_id = db.Column(db.Integer, nullable=True)

    # عدد مرات الاستخدام (كم مرة ردّ بهذا الجواب)
    usage_count = db.Column(db.Integer, default=0)

    # تقييم (هل الرد مفيد) — يمكن التاجر يقيّمه لاحقاً
    is_approved = db.Column(db.Boolean, default=True)
    is_active = db.Column(db.Boolean, default=True, index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # علاقة
    tenant = db.relationship('Tenant', backref=db.backref(
        'custom_replies', lazy='dynamic', cascade='all, delete-orphan'))

    def matches(self, message: str) -> bool:
        """هل الرسالة تتطابق مع الكلمات المفتاحية؟"""
        import re
        # تنظيف الرسالة
        msg = message.strip()
        msg = re.sub(r'[\u0610-\u061A\u064B-\u065F\u0670]', '', msg)
        msg = re.sub(r'[إأآا]', 'ا', msg)
        msg = re.sub(r'ة', 'ه', msg)
        msg = msg.lower()

        # تحقق من كل كلمة مفتاحية
        for kw in self.keywords.split(','):
            kw = kw.strip()
            if not kw:
                continue
            # نفس التنظيف
            kw_clean = kw.strip()
            kw_clean = re.sub(r'[\u0610-\u061A\u064B-\u065F\u0670]', '', kw_clean)
            kw_clean = re.sub(r'[إأآا]', 'ا', kw_clean)
            kw_clean = re.sub(r'ة', 'ه', kw_clean)
            kw_clean = kw_clean.lower()

            if kw_clean in msg:
                return True
        return False

    def __repr__(self):
        return f'<CustomReply {self.id} tenant={self.tenant_id} keywords="{self.keywords[:30]}">'

    @staticmethod
    def find_reply(tenant_id: int, message: str):
        """البحث عن رد مخصص لرسالة معيّنة."""
        replies = CustomReply.query.filter_by(
            tenant_id=tenant_id, is_active=True, is_approved=True
        ).all()

        best_match = None
        for r in replies:
            if r.matches(message):
                # إذا فيه أكثر من تطابق، نأخذ الأكثر استخداماً
                if not best_match or r.usage_count > best_match.usage_count:
                    best_match = r

        if best_match:
            best_match.usage_count += 1
            from app.extensions import db
            db.session.commit()

        return best_match

    @staticmethod
    def learn_from_inquiry(tenant_id: int, question: str, answer: str, inquiry_id: int = None):
        """
        تعلّم رد جديد من استفسار تم الرد عليه.
        يُستدعى تلقائياً عند رد صاحب النشاط على استفسار.
        """
        import re
        # استخراج كلمات مفتاحية من السؤال (الكلمات المهمة فقط)
        stop_words = {'في', 'من', 'على', 'الى', 'عن', 'هل', 'هو', 'هي',
                      'ان', 'لا', 'ما', 'يا', 'و', 'او', 'بس', 'كيف',
                      'وين', 'فين', 'ليش', 'متى', 'شو', 'وش', 'ايش'}

        words = re.sub(r'[؟?!.,،]', '', question).split()
        keywords = [w for w in words if len(w) > 2 and w not in stop_words]

        if not keywords:
            return None

        # التحقق من عدم التكرار
        existing = CustomReply.query.filter_by(
            tenant_id=tenant_id, inquiry_id=inquiry_id
        ).first()
        if existing:
            existing.reply_text = answer
            return existing

        reply = CustomReply(
            tenant_id=tenant_id,
            keywords=','.join(keywords[:5]),  # أقصى 5 كلمات مفتاحية
            reply_text=answer,
            source='learned',
            inquiry_id=inquiry_id,
            is_approved=True,
        )
        from app.extensions import db
        db.session.add(reply)
        return reply

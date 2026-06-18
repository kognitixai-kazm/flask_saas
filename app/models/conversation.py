"""
app/models/conversation.py — المحادثات والرسائل
"""
from datetime import datetime
from ..extensions import db


class Conversation(db.Model):
    """محادثة بين زائر وشات tenant."""
    __tablename__ = 'conversations'

    id = db.Column(db.Integer, primary_key=True)

    tenant_id = db.Column(
        db.Integer, db.ForeignKey('tenants.id'),
        nullable=False, index=True
    )

    # هوية الزائر (من cookie chat_visitor)
    visitor_id = db.Column(db.String(64), nullable=False, index=True)

    # web | whatsapp
    channel = db.Column(db.String(20), default='web', nullable=False, index=True)

    # بيانات إضافية عن الزائر (اختيارية)
    visitor_name = db.Column(db.String(200))
    visitor_phone = db.Column(db.String(30))
    visitor_email = db.Column(db.String(255))

    # metadata
    extra_data = db.Column(db.JSON, default=dict)

    started_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    ended_at = db.Column(db.DateTime)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow,
        onupdate=datetime.utcnow, nullable=False
    )

    # علاقات
    tenant = db.relationship('Tenant', back_populates='conversations')
    messages = db.relationship(
        'Message',
        back_populates='conversation',
        cascade='all, delete-orphan',
        order_by='Message.created_at',
        lazy='dynamic'
    )

    def __repr__(self):
        return f'<Conversation {self.id} tenant={self.tenant_id}>'

    @property
    def last_message(self):
        return self.messages.order_by(Message.created_at.desc()).first()


class Message(db.Model):
    """رسالة داخل محادثة."""
    __tablename__ = 'messages'

    id = db.Column(db.Integer, primary_key=True)

    conversation_id = db.Column(
        db.Integer, db.ForeignKey('conversations.id'),
        nullable=False, index=True
    )

    # tenant_id مكرر للأداء (filtering سريع دون join)
    tenant_id = db.Column(
        db.Integer, db.ForeignKey('tenants.id'),
        nullable=False, index=True
    )

    # visitor | bot | agent | system
    sender_type = db.Column(db.String(20), nullable=False, index=True)

    content = db.Column(db.Text, nullable=False)

    extra_data = db.Column(db.JSON, default=dict)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    # علاقات
    conversation = db.relationship('Conversation', back_populates='messages')

    def __repr__(self):
        return f'<Message {self.id} [{self.sender_type}]>'

    def to_dict(self):
        d = {
            'id': self.id,
            'sender_type': self.sender_type,
            'content': self.content,
            'created_at': self.created_at.isoformat(),
        }
        ex = self.extra_data or {}
        if isinstance(ex, dict) and ex.get('images'):
            d['images'] = ex['images']
        return d

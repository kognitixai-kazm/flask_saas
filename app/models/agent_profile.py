"""
app/models/agent_profile.py — إعدادات مخصصة لكل وكيل داخل المنشأة
يسمح للتاجر بتغيير اسم الوكيل ونبرته.
"""
from datetime import datetime
from ..extensions import db


class AgentProfile(db.Model):
    __tablename__ = 'agent_profiles'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    
    # نوع الوكيل: reception | contract | collection | analytics | accounting
    agent_type = db.Column(db.String(50), nullable=False, index=True)
    
    # الاسم المخصص (مثلاً: سارة، خالد)
    agent_name = db.Column(db.String(100), default='')
    
    # النبرة: formal | friendly | custom
    tone = db.Column(db.String(30), default='friendly')
    
    # تعليمات مخصصة تضاف لهذا الوكيل بالتحديد
    custom_instructions = db.Column(db.Text, default='')
    
    # هل الوكيل مفعل
    is_active = db.Column(db.Boolean, default=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # علاقات
    tenant = db.relationship('Tenant', backref=db.backref('agent_profiles', lazy='dynamic', cascade='all, delete-orphan'))

    # منع تكرار نفس نوع الوكيل لنفس التاجر
    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'agent_type', name='uix_tenant_agent_type'),
    )

    def __repr__(self):
        return f'<AgentProfile {self.agent_type} for tenant {self.tenant_id}>'

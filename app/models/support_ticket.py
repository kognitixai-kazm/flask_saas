from datetime import datetime
from ..extensions import db

class SupportTicket(db.Model):
    __tablename__ = 'support_tickets'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    
    subject = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    
    status = db.Column(db.String(20), default='open', index=True) # open, in_progress, resolved, closed
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = db.relationship('Tenant', backref=db.backref('support_tickets', lazy='dynamic'))

    def __repr__(self):
        return f'<SupportTicket {self.id} tenant={self.tenant_id} status={self.status}>'

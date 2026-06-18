"""
@chat_visitor_session — يقرأ/ينشئ visitor_id لزائر الشات.
يعمل على مسارات /c/* فقط.
"""
from functools import wraps
from flask import session, g, request

from app.utils.slug import generate_visitor_id


def chat_visitor_session(f):
    """يتأكد من وجود visitor_id في session الزائر."""
    @wraps(f)
    def decorated(*args, **kwargs):
        visitor_id = session.get('visitor_id')

        if not visitor_id:
            visitor_id = generate_visitor_id()
            session['visitor_id'] = visitor_id

        g.visitor_id = visitor_id
        return f(*args, **kwargs)

    return decorated

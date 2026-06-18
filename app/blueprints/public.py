"""
app/blueprints/public.py — الموقع التعريفي (/)
مفتوح لأي زائر. لا يحتاج مصادقة.
"""
from flask import Blueprint, render_template, current_app, Response, abort
from app.models.plan import Plan
from app.models.activity import Activity
from app.models.hotel_models import Unit
from app.services.ical_service import ICalService

bp = Blueprint('public', __name__, template_folder='../../templates/public')


@bp.route('/')
def home():
    """الصفحة الرئيسية (Landing Page)."""
    plans = Plan.query.filter_by(status='active').filter(
        Plan.code != 'trial'
    ).order_by(Plan.sort_order).all()
    activities = Activity.query.filter_by(is_active=True).order_by(Activity.sort_order).all()
    return render_template('public/home.html', plans=plans, activities=activities)


@bp.route('/features')
def features():
    return render_template('public/features.html')


@bp.route('/pricing')
def pricing():
    plans = Plan.query.filter_by(status='active').filter(
        Plan.code != 'trial'
    ).order_by(Plan.sort_order).all()
    return render_template('public/pricing.html', plans=plans)


@bp.route('/activities')
def activities():
    activities = Activity.query.filter_by(is_active=True).order_by(Activity.sort_order).all()
    return render_template('public/activities.html', activities=activities)


@bp.route('/faq')
def faq():
    return render_template('public/faq.html')


@bp.route('/contact')
def contact():
    return render_template('public/contact.html')


@bp.route('/terms')
def terms():
    return render_template('public/terms.html')


@bp.route('/privacy')
def privacy():
    return render_template('public/privacy.html')

@bp.route('/ical/export/<token>.ics')
def export_ical(token):
    unit = Unit.query.filter_by(ical_export_token=token).first()
    if not unit:
        abort(404)
        
    ical_data = ICalService.generate_ical(unit.id)
    if not ical_data:
        abort(404)
        
    return Response(ical_data, mimetype='text/calendar')


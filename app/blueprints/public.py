"""
app/blueprints/public.py — الموقع التعريفي (/)
مفتوح لأي زائر. لا يحتاج مصادقة.
"""
from flask import Blueprint, render_template, current_app, Response, abort, request, redirect, url_for
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
    return render_template('public/landing_v2.html', plans=plans, activities=activities)


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

@bp.route('/contract/sign/<token>', methods=['GET', 'POST'])
def sign_contract(token):
    from app.models.contract import Contract
    from app.services.contract_service import ContractService
    from app.extensions import db
    import datetime

    contract = Contract.query.filter_by(signature_token=token).first()
    if not contract:
        abort(404, "العقد غير موجود أو الرابط غير صحيح")

    if request.method == 'POST':
        if contract.status == 'signed':
            # بالفعل موقّع
            return redirect(url_for('public.sign_contract', token=token))
        
        # التقاط التوقيع
        contract.signature_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        contract.status = 'signed'
        contract.signed_at = datetime.datetime.utcnow()
        db.session.commit()

        # إعادة توليد الـ PDF مع التوقيع
        try:
            ContractService._generate_pdf_internal(contract, contract.template)
            db.session.commit()
            # إرسال إشعار التوقيع النهائي للعميل
            ContractService.send_to_customer(contract)
        except Exception as e:
            current_app.logger.error(f"Error regenerating signed contract: {e}")

        return redirect(url_for('public.sign_contract', token=token))
        
    return render_template('public/sign_contract.html', contract=contract)

@bp.route('/ical/export/<token>.ics')
def export_ical(token):
    unit = Unit.query.filter_by(ical_export_token=token).first()
    if not unit:
        abort(404)
        
    ical_data = ICalService.generate_ical(unit.id)
    if not ical_data:
        abort(404)
        
    return Response(ical_data, mimetype='text/calendar')


"""
app/blueprints/tenant_restaurant.py — إدارة بيانات المطعم (/app/restaurant/*)
التصنيفات + الأصناف + الخدمات — كلها من لوحة التحكم.
"""
import uuid
from pathlib import Path
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, current_app
from werkzeug.utils import secure_filename

from app.extensions import db
from app.decorators import tenant_required
from app.models.branch import Branch
from app.models.restaurant_models import MenuCategory, MenuItem, RestaurantService

bp = Blueprint('tenant_restaurant', __name__, template_folder='../../templates/tenant/restaurant')


_ALLOWED_IMG_EXT = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}


def _save_item_images(tenant_id: int, files) -> list:
    """يحفظ صور الصنف في Cloudinary إن مُضبط، وإلا في static/uploads. يرجع روابط."""
    from app.services.cloudinary_service import CloudinaryService
    use_cloud = CloudinaryService.is_configured()

    upload_root = None
    if not use_cloud:
        upload_root = Path(current_app.config['UPLOAD_FOLDER']) / 'menu_items' / str(tenant_id)
        upload_root.mkdir(parents=True, exist_ok=True)

    urls = []
    for up in files or []:
        if not up or not up.filename:
            continue
        safe = secure_filename(up.filename)
        if not safe or '.' not in safe:
            continue
        ext = '.' + safe.rsplit('.', 1)[1].lower()
        if ext not in _ALLOWED_IMG_EXT:
            continue

        if use_cloud:
            up.stream.seek(0)
            res = CloudinaryService.upload_image(
                file=up.stream,
                folder=f'menu_items/tenant_{tenant_id}',
                tags=['menu_item'],
            )
            if res.get('success') and res.get('url'):
                urls.append(res['url'])
            else:
                current_app.logger.warning(
                    f'[restaurant] cloudinary upload failed: {res.get("error")}'
                )
        else:
            stored = f'{uuid.uuid4().hex}{ext}'
            up.save(upload_root / stored)
            urls.append(url_for('static', filename=f'uploads/menu_items/{tenant_id}/{stored}'))
    return urls


def _ensure_restaurant(f):
    from functools import wraps
    @wraps(f)
    @tenant_required
    def decorated(*args, **kwargs):
        if g.current_tenant.activity.code != 'restaurant':
            flash('هذا القسم خاص بالمطاعم فقط', 'danger')
            return redirect(url_for('tenant.dashboard'))
        return f(*args, **kwargs)
    return decorated


# ==================== التصنيفات ====================
@bp.route('/categories')
@_ensure_restaurant
def categories():
    items = MenuCategory.query.filter_by(tenant_id=g.current_tenant.id).order_by(MenuCategory.sort_order).all()
    return render_template('tenant/restaurant/categories.html', categories=items)


@bp.route('/categories/new', methods=['GET', 'POST'])
@bp.route('/categories/<int:id>/edit', methods=['GET', 'POST'])
@_ensure_restaurant
def category_form(id=None):
    item = MenuCategory.query.filter_by(id=id, tenant_id=g.current_tenant.id).first() if id else None
    if request.method == 'POST':
        if not item:
            item = MenuCategory(tenant_id=g.current_tenant.id)
            db.session.add(item)
        item.name = request.form['name']
        item.description = request.form.get('description', '')
        item.icon = request.form.get('icon', '')
        item.sort_order = int(request.form.get('sort_order', 0))
        item.is_active = 'is_active' in request.form
        db.session.commit()
        flash('تم حفظ التصنيف', 'success')
        return redirect(url_for('tenant_restaurant.categories'))
    return render_template('tenant/restaurant/category_form.html', category=item)


@bp.route('/categories/<int:id>/delete', methods=['POST'])
@_ensure_restaurant
def category_delete(id):
    item = MenuCategory.query.filter_by(id=id, tenant_id=g.current_tenant.id).first_or_404()
    db.session.delete(item)
    db.session.commit()
    flash('تم حذف التصنيف', 'success')
    return redirect(url_for('tenant_restaurant.categories'))


# ==================== الأصناف (المنيو) ====================
@bp.route('/menu')
@_ensure_restaurant
def menu_items():
    cat_filter = request.args.get('category')
    q = MenuItem.query.filter_by(tenant_id=g.current_tenant.id)
    if cat_filter:
        q = q.filter_by(category_id=int(cat_filter))
    items = q.all()
    cats = MenuCategory.query.filter_by(tenant_id=g.current_tenant.id).all()
    return render_template('tenant/restaurant/menu_items.html', items=items, categories=cats)


@bp.route('/menu/new', methods=['GET', 'POST'])
@bp.route('/menu/<int:id>/edit', methods=['GET', 'POST'])
@_ensure_restaurant
def menu_item_form(id=None):
    item = MenuItem.query.filter_by(id=id, tenant_id=g.current_tenant.id).first() if id else None
    cats = MenuCategory.query.filter_by(tenant_id=g.current_tenant.id).all()
    branches_list = Branch.query.filter_by(tenant_id=g.current_tenant.id).all()

    if request.method == 'POST':
        if not item:
            item = MenuItem(tenant_id=g.current_tenant.id)
            db.session.add(item)
        item.category_id = int(request.form['category_id'])
        item.branch_id = int(request.form['branch_id']) if request.form.get('branch_id') else None
        item.name = request.form['name']
        item.description = request.form.get('description', '')
        item.price = float(request.form.get('price', 0))
        item.discount_price = float(request.form['discount_price']) if request.form.get('discount_price') else None
        item.calories = int(request.form['calories']) if request.form.get('calories') else None
        item.prep_time_min = int(request.form['prep_time_min']) if request.form.get('prep_time_min') else None
        item.is_spicy = 'is_spicy' in request.form
        item.is_vegetarian = 'is_vegetarian' in request.form
        item.is_popular = 'is_popular' in request.form
        item.is_available = 'is_available' in request.form

        # ====== صور الصنف (Cloudinary أو محلي) ======
        existing = list(item.images or []) if not request.form.get('clear_images') else []
        new_urls = _save_item_images(g.current_tenant.id, request.files.getlist('item_images'))
        item.images = existing + new_urls

        db.session.commit()
        flash('تم حفظ الصنف', 'success')
        return redirect(url_for('tenant_restaurant.menu_items'))

    return render_template('tenant/restaurant/menu_item_form.html',
        item=item, categories=cats, branches=branches_list)


@bp.route('/menu/<int:id>/delete', methods=['POST'])
@_ensure_restaurant
def menu_item_delete(id):
    item = MenuItem.query.filter_by(id=id, tenant_id=g.current_tenant.id).first_or_404()
    db.session.delete(item)
    db.session.commit()
    flash('تم حذف الصنف', 'success')
    return redirect(url_for('tenant_restaurant.menu_items'))


# ==================== خدمات المطعم ====================
@bp.route('/services')
@_ensure_restaurant
def services():
    items = RestaurantService.query.filter_by(tenant_id=g.current_tenant.id).all()
    return render_template('tenant/restaurant/services.html', services=items)


@bp.route('/services/new', methods=['GET', 'POST'])
@bp.route('/services/<int:id>/edit', methods=['GET', 'POST'])
@_ensure_restaurant
def service_form(id=None):
    item = RestaurantService.query.filter_by(id=id, tenant_id=g.current_tenant.id).first() if id else None
    if request.method == 'POST':
        if not item:
            item = RestaurantService(tenant_id=g.current_tenant.id)
            db.session.add(item)
        item.service_type = request.form['service_type']
        item.description = request.form.get('description', '')
        item.delivery_fee = float(request.form.get('delivery_fee', 0))
        item.min_order = float(request.form.get('min_order', 0))
        item.delivery_areas = request.form.get('delivery_areas', '')
        item.is_active = 'is_active' in request.form
        db.session.commit()
        flash('تم حفظ الخدمة', 'success')
        return redirect(url_for('tenant_restaurant.services'))

    svc_types = [('delivery','توصيل'),('reservation','حجز طاولة'),('pre_order','طلب مسبق'),('dine_in','أكل في المطعم'),('takeaway','سفري')]
    return render_template('tenant/restaurant/service_form.html', service=item, service_types=svc_types)

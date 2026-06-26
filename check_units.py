from app import create_app
from app.extensions import db
from app.models.hotel_models import Unit

app = create_app()
with app.app_context():
    units = Unit.query.all()
    for u in units:
        print(f"ID:{u.id} Tenant:{u.tenant_id} Num:{u.unit_number} Type:{u.unit_type} Beds:{u.bedrooms_count} Avail:{u.is_available} Status:{u.status}")

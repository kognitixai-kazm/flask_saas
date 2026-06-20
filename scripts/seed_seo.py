from app import create_app
from app.models.system_settings import SystemSetting

app = create_app()
with app.app_context():
    SystemSetting.seed_defaults()
    print("Seeded successfully!")

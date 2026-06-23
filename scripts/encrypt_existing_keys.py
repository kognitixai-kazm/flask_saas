import os
import sys

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.extensions import db
from app.models.bot_config import BotConfig
from app.models.integration import Integration
from app.models.tenant_integrations import TenantIntegration
from app.utils.encryption import encrypt_value, decrypt_value, get_cipher
from dotenv import load_dotenv

load_dotenv()

def is_encrypted(val: str) -> bool:
    if not val:
        return False
    if not val.startswith('gAAAAA'):
        return False
    try:
        cipher = get_cipher()
        cipher.decrypt(val.encode('utf-8'))
        return True
    except Exception:
        return False

def run_migration():
    app = create_app()
    with app.app_context():
        print("Starting encryption migration...")
        
        # 1. BotConfig
        bot_configs = BotConfig.query.all()
        bot_count = 0
        for bot in bot_configs:
            updated = False
            
            if bot.image_api_key and not is_encrypted(bot.image_api_key):
                bot.image_api_key = encrypt_value(bot.image_api_key)
                updated = True
            
            if bot.image_api_secret and not is_encrypted(bot.image_api_secret):
                bot.image_api_secret = encrypt_value(bot.image_api_secret)
                updated = True
                
            if bot.voice_api_key and not is_encrypted(bot.voice_api_key):
                bot.voice_api_key = encrypt_value(bot.voice_api_key)
                updated = True
                
            if bot.call_api_key and not is_encrypted(bot.call_api_key):
                bot.call_api_key = encrypt_value(bot.call_api_key)
                updated = True
                
            if bot.call_api_secret and not is_encrypted(bot.call_api_secret):
                bot.call_api_secret = encrypt_value(bot.call_api_secret)
                updated = True
                
            if updated:
                bot_count += 1
                
        # 2. Integration
        integrations = Integration.query.all()
        int_count = 0
        for integ in integrations:
            updated = False
            
            if integ.api_key and not is_encrypted(integ.api_key):
                integ.api_key = encrypt_value(integ.api_key)
                updated = True
                
            if integ.api_secret and not is_encrypted(integ.api_secret):
                integ.api_secret = encrypt_value(integ.api_secret)
                updated = True
                
            if integ.access_token and not is_encrypted(integ.access_token):
                integ.access_token = encrypt_value(integ.access_token)
                updated = True
                
            if integ.webhook_verify_token and not is_encrypted(integ.webhook_verify_token):
                integ.webhook_verify_token = encrypt_value(integ.webhook_verify_token)
                updated = True
                
            if updated:
                int_count += 1
                
        # 3. TenantIntegration (SMS)
        sms_configs = TenantIntegration.query.all()
        sms_count = 0
        for sms in sms_configs:
            updated = False
            
            if sms.api_key and not is_encrypted(sms.api_key):
                sms.api_key = encrypt_value(sms.api_key)
                updated = True
                
            if updated:
                sms_count += 1
                
        db.session.commit()
        print(f"Migration completed successfully.")
        print(f"- BotConfigs updated: {bot_count}")
        print(f"- Integrations updated: {int_count}")
        print(f"- TenantIntegrations (SMS) updated: {sms_count}")

if __name__ == '__main__':
    run_migration()

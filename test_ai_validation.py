import os
import sys

# إعداد مسار المشروع
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from app import create_app
from app.services.ai_service import AIService

app = create_app()

with app.app_context():
    print("Testing OpenAI with invalid key:")
    ok, reason = AIService.validate_api_key('openai', 'sk-invalid', force=True)
    print(f"OpenAI: {ok}, {reason}")

    print("Testing Anthropic with invalid key:")
    ok, reason = AIService.validate_api_key('anthropic', 'sk-ant-invalid', force=True)
    print(f"Anthropic: {ok}, {reason}")
    
    print("Testing Google with invalid key:")
    ok, reason = AIService.validate_api_key('google', 'AIza-invalid', force=True)
    print(f"Google: {ok}, {reason}")
    

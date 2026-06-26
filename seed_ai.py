import os
from dotenv import load_dotenv
load_dotenv()

from app import create_app
from app.extensions import db
from app.models.ai_provider import AIProvider
from app.models.ai_model import AIModel
from app.models.agent_profile import AgentProfile
from sqlalchemy import text

app = create_app()

with app.app_context():
    # Fix the missing has_unlimited_ai column issue using raw SQL just in case
    try:
        db.session.execute(text('ALTER TABLE tenants ADD COLUMN IF NOT EXISTS has_unlimited_ai BOOLEAN DEFAULT FALSE NOT NULL;'))
        db.session.commit()
    except Exception as e:
        print("Skipped altering tenants table:", e)
        db.session.rollback()

    # Create agent_profiles table if it does not exist (to fix any rendering errors)
    try:
        AgentProfile.__table__.create(db.engine, checkfirst=True)
        db.session.commit()
    except Exception as e:
        print("Skipped creating agent_profiles:", e)
        db.session.rollback()

    print("DB Schema checks done. Now seeding providers and models.")

    # 1. Google Gemini
    google = AIProvider.query.filter_by(slug='google').first()
    if not google:
        google = AIProvider(slug='google', name='Google Gemini', priority=4)
        db.session.add(google)
        db.session.flush()
    else:
        google.priority = 4

    # 2. Anthropic (Claude)
    anthropic = AIProvider.query.filter_by(slug='anthropic').first()
    if not anthropic:
        anthropic = AIProvider(slug='anthropic', name='Anthropic Claude', priority=2)
        db.session.add(anthropic)
        db.session.flush()
    else:
        anthropic.priority = 2

    # 3. OpenAI (GPT-4o)
    openai = AIProvider.query.filter_by(slug='openai').first()
    if not openai:
        openai = AIProvider(slug='openai', name='OpenAI', priority=3)
        db.session.add(openai)
        db.session.flush()
    else:
        openai.priority = 3



    # ADD MODELS
    models_to_add = [
        (google, 'gemini-1.5-pro', 'Gemini 1.5 Pro', True),
        (google, 'gemini-1.5-flash', 'Gemini 1.5 Flash', False),
        (anthropic, 'claude-3-opus-20240229', 'Claude 3 Opus', False),
        (anthropic, 'claude-3-5-sonnet-20240620', 'Claude 3.5 Sonnet', True),
        (anthropic, 'claude-3-haiku-20240307', 'Claude 3 Haiku', False),
        (openai, 'gpt-4o', 'GPT-4o', True),
        (openai, 'gpt-4o-mini', 'GPT-4o Mini', False)
    ]

    for prov, m_id, d_name, is_def in models_to_add:
        mod = AIModel.query.filter_by(provider_id=prov.id, model_id=m_id).first()
        if not mod:
            mod = AIModel(provider_id=prov.id, model_id=m_id, display_name=d_name, is_default=is_def)
            db.session.add(mod)
        else:
            mod.is_default = is_def

    db.session.commit()
    print("Seed completed successfully!")

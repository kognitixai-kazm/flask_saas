"""
معالجة وسائط واتساب (صوت/صورة) باستخدام مفاتيح BotConfig + مفتاح OpenAI/Gemini عند الحاجة.

- الصوت: OpenAI Whisper عبر voice_api_key أو مفتاح AI للتاجر (openai) أو مفتاح المنصة.
- الصورة: وصف بالعربية عبر رؤية OpenAI أو Gemini حسب المفتاح المتاح (بدون تكرار تخزين).
"""
from __future__ import annotations

import base64
import io
from typing import Optional, Tuple

import requests
from flask import current_app

from app.models.bot_config import BotConfig

GRAPH_API = 'https://graph.facebook.com/v21.0'


def _openai_key_for_media(bot: Optional[BotConfig]) -> str:
    """أولوية: مفتاح الصوت (Whisper) إن وُجد → مفتاح AI إن كان openai → مفتاح المنصة."""
    if bot:
        if (bot.voice_provider or '').strip() == 'openai_whisper' and (bot.voice_api_key or '').strip():
            return bot.voice_api_key.strip()
        if (bot.ai_provider or '').strip().lower() in ('openai', '') and (bot.ai_api_key or '').strip():
            from app.utils.encryption import decrypt_value
            return decrypt_value(bot.ai_api_key).strip()
    return (current_app.config.get('OPENAI_API_KEY') or '').strip()


def _gemini_key_for_media(bot: Optional[BotConfig]) -> str:
    if bot and (bot.ai_provider or '').strip().lower() in ('google_gemini', 'google'):
        k = (bot.ai_api_key or '').strip()
        if k:
            from app.utils.encryption import decrypt_value
            return decrypt_value(k).strip()
    return (current_app.config.get('GOOGLE_API_KEY') or '').strip()


def download_whatsapp_media(media_id: str, access_token: str) -> Tuple[Optional[bytes], str]:
    """تنزيل ملف وسائط من Graph API. يعيد (bytes, mime_type)."""
    if not media_id or not access_token:
        return None, ''
    try:
        h = {'Authorization': f'Bearer {access_token}'}
        r = requests.get(f'{GRAPH_API}/{media_id}', headers=h, timeout=20)
        if r.status_code != 200:
            current_app.logger.warning('[Media] graph media id failed: %s', r.text[:200])
            return None, ''
        j = r.json() or {}
        url = (j.get('url') or '').strip()
        mime = (j.get('mime_type') or 'application/octet-stream').strip()
        if not url:
            return None, ''
        r2 = requests.get(url, headers=h, timeout=60)
        if r2.status_code != 200:
            return None, mime
        return r2.content, mime
    except Exception as e:
        current_app.logger.warning('[Media] download error: %s', e)
        return None, ''


def transcribe_openai_whisper(audio_bytes: bytes, filename: str, api_key: str) -> Optional[str]:
    if not api_key or not audio_bytes:
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        buf = io.BytesIO(audio_bytes)
        buf.name = filename or 'audio.ogg'
        tr = client.audio.transcriptions.create(model='whisper-1', file=buf)
        t = (getattr(tr, 'text', None) or '').strip()
        return t or None
    except Exception as e:
        current_app.logger.warning('[Media] Whisper failed: %s', e)
        return None


def describe_image_openai(image_bytes: bytes, mime: str, api_key: str, model: str) -> Optional[str]:
    if not api_key or not image_bytes:
        return None
    m = (model or '').strip() or 'gpt-4o-mini'
    # نماذج بدون رؤية تُستبدل بأخرى آمنة
    if m in ('gpt-3.5-turbo', 'gpt-4', 'gpt-4-turbo-preview'):
        m = 'gpt-4o-mini'
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        b64 = base64.standard_b64encode(image_bytes).decode('ascii')
        data_url = f'data:{mime or "image/jpeg"};base64,{b64}'
        resp = client.chat.completions.create(
            model=m,
            messages=[
                {
                    'role': 'user',
                    'content': [
                        {
                            'type': 'text',
                            'text': (
                                'صف محتوى هذه الصورة للعميل بجملة أو جملتين بالعربية فقط. '
                                'إن كانت قائمة طعام أو فاتورة أو لقطة شاشة اذكر ذلك باختصار.'
                            ),
                        },
                        {'type': 'image_url', 'image_url': {'url': data_url}},
                    ],
                }
            ],
            max_tokens=400,
            temperature=0.3,
        )
        out = (resp.choices[0].message.content or '').strip()
        return out or None
    except Exception as e:
        current_app.logger.warning('[Media] OpenAI vision failed: %s', e)
        return None


def describe_image_gemini(image_bytes: bytes, mime: str, api_key: str, model: str) -> Optional[str]:
    if not api_key or not image_bytes:
        return None
    m = (model or '').strip() or 'gemini-2.0-flash'
    b64 = base64.standard_b64encode(image_bytes).decode('ascii')
    url = f'https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent'
    body = {
        'contents': [
            {
                'role': 'user',
                'parts': [
                    {'inline_data': {'mime_type': mime or 'image/jpeg', 'data': b64}},
                    {
                        'text': (
                            'صف هذه الصورة للعميل بجملة أو جملتين بالعربية فقط. '
                            'لا تستخدم markdown.'
                        )
                    },
                ],
            }
        ],
        'generationConfig': {'maxOutputTokens': 400, 'temperature': 0.3},
    }
    try:
        r = requests.post(url, params={'key': api_key}, json=body, timeout=90)
        r.raise_for_status()
        data = r.json()
        cands = data.get('candidates') or []
        if not cands:
            return None
        parts = ((cands[0].get('content') or {}).get('parts')) or []
        texts = [p.get('text', '') for p in parts if isinstance(p, dict)]
        out = ''.join(texts).strip()
        return out or None
    except Exception as e:
        current_app.logger.warning('[Media] Gemini vision failed: %s', e)
        return None


def enrich_whatsapp_incoming_text(
    tenant_id: int,
    msg_type: str,
    msg: dict,
    wa_access_token: str,
) -> str:
    """
    يبني نصاً يُمرَّر إلى محرك الشات/الـ AI.
    نص عادي: كما هو. صورة/صوت: تنزيل + تحليل عند توفر المفاتيح.
    """
    bot = BotConfig.query.filter_by(tenant_id=tenant_id).first()

    if msg_type == 'text':
        return (msg.get('text') or {}).get('body', '') or ''

    if msg_type == 'image':
        cap = (msg.get('image') or {}).get('caption') or ''
        mid = (msg.get('image') or {}).get('id')
        mime = (msg.get('image') or {}).get('mime_type') or 'image/jpeg'
        if not mid:
            return cap or 'أرسل صورة'
        raw, mime2 = download_whatsapp_media(mid, wa_access_token)
        mime = mime2 or mime
        if not raw:
            return cap or 'أرسل صورة'
        desc = None
        okey = _openai_key_for_media(bot)
        if okey:
            model = (bot.ai_model if bot else '') or current_app.config.get('OPENAI_MODEL', 'gpt-4o-mini')
            desc = describe_image_openai(raw, mime, okey, model)
        if not desc:
            gkey = _gemini_key_for_media(bot)
            if gkey:
                model = (bot.ai_model if bot else '') or current_app.config.get('GOOGLE_AI_MODEL', 'gemini-2.0-flash')
                desc = describe_image_gemini(raw, mime, gkey, model)
        parts = []
        if cap:
            parts.append(f'[تعليق الزائر على الصورة: {cap}]')
        if desc:
            parts.append(f'[وصف الصورة: {desc}]')
        if not parts:
            parts.append('أرسل صورة')
        return '\n'.join(parts)

    if msg_type == 'audio':
        mid = (msg.get('audio') or {}).get('id')
        mime = (msg.get('audio') or {}).get('mime_type') or 'audio/ogg'
        if not mid:
            return 'أرسل رسالة صوتية'
        prov = (bot.voice_provider if bot else '') or ''
        if prov == 'google_speech':
            current_app.logger.info('[Media] google_speech: يتطلب إعداد Google Cloud STT — استخدم OpenAI Whisper')
            return 'أرسل رسالة صوتية'
        raw, _ = download_whatsapp_media(mid, wa_access_token)
        if not raw:
            return 'أرسل رسالة صوتية'
        key = _openai_key_for_media(bot)
        if not key:
            current_app.logger.info('[Media] لا مفتاح OpenAI/Whisper — تعذر نسخ الصوت')
            return 'أرسل رسالة صوتية'
        ext = 'ogg'
        if 'mpeg' in mime or 'mp3' in mime:
            ext = 'mp3'
        elif 'wav' in mime:
            ext = 'wav'
        txt = transcribe_openai_whisper(raw, f'wa.{ext}', key)
        if txt:
            return f'[رسالة صوتية — نصها التقريبي: {txt}]'
        return 'أرسل رسالة صوتية'

    if msg_type == 'document':
        return (msg.get('document') or {}).get('caption') or 'أرسل مستند'
    if msg_type == 'location':
        return 'أرسل موقع'
    return f'رسالة ({msg_type})'

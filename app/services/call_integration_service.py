"""
ربط إعدادات الاتصال في BotConfig (Twilio أولاً — Vonage/Bland لاحقاً).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
from urllib.parse import urlparse, urlunparse

import requests
from flask import Request, current_app

from app.models.bot_config import BotConfig


def _normalize_twilio_url(url: str) -> str:
    """Twilio يوقّع على https غالباً."""
    try:
        p = urlparse(url)
        if p.scheme == 'http':
            p = p._replace(scheme='https')
        return urlunparse(p)
    except Exception:
        return url


def twilio_signature_valid(request: Request, auth_token: str) -> bool:
    """التحقق من X-Twilio-Signature (GET أو POST)."""
    sig = (request.headers.get('X-Twilio-Signature') or '').strip()
    if not sig or not auth_token:
        return False
    try:
        url = _normalize_twilio_url(request.url)
        s = url
        if request.method in ('POST', 'PUT', 'PATCH') and request.form:
            for k in sorted(request.form.keys()):
                s += str(k) + str(request.form.get(k) or '')
        mac = hmac.new(auth_token.encode('utf-8'), s.encode('utf-8'), hashlib.sha1).digest()
        expected = base64.b64encode(mac).decode('utf-8').strip()
        return hmac.compare_digest(expected, sig)
    except Exception:
        return False


def build_twiml_for_tenant(bot: BotConfig, say_text: str = None) -> str:
    """TwiML لبدء أو استكمال محادثة مع <Gather>."""
    from xml.sax.saxutils import escape

    base_url = (current_app.config.get('SITE_URL') or '').rstrip('/')
    action_url = f'{base_url}/api/v1/webhooks/twilio/voice/{bot.tenant_id}/process'
    
    greet = say_text if say_text is not None else ((bot.call_greeting or '').strip() or 'أهلاً بك، كيف نقدر نخدمك؟')
    lang = 'ar-SA'
    if (bot.call_voice or '').endswith('_en'):
        lang = 'en-US'
        
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Response>'
        f'<Gather input="speech" action="{escape(action_url)}" language="{lang}" speechTimeout="auto">'
        f'<Say language="{lang}">{escape(greet)}</Say>'
        '</Gather>'
        # إذا لم يتحدث المتصل، نعيد توجيهه لنفس المعالج بصمت (أو يمكن تشغيل رسالة وداع)
        f'<Redirect>{escape(action_url)}?timeout=1</Redirect>'
        '</Response>'
    )


def initiate_outbound_call(tenant_id: int, to_phone_e164: str) -> dict:
    """
    بدء مكالمة صادرة عبر Twilio (From = رقم Twilio المسجّل، To = العميل).
    يتطلب call_is_active + call_provider=twilio + مفاتيح ورقم.
    """
    bot = BotConfig.query.filter_by(tenant_id=tenant_id).first()
    if not bot or not bot.call_is_active:
        return {'ok': False, 'error': 'الاتصال غير مفعّل في إعدادات البوت'}
    prov = (bot.call_provider or '').strip().lower()
    if prov != 'twilio':
        if prov == 'vonage':
            return {'ok': False, 'error': 'Vonage غير مفعّل في الكود بعد — استخدم Twilio'}
        if prov == 'bland':
            return {'ok': False, 'error': 'Bland.ai يحتاج تكامل منفصل — استخدم Twilio'}
        return {'ok': False, 'error': 'لم يُحدد مزوّد اتصال'}

    from app.utils.encryption import decrypt_value
    sid = decrypt_value(bot.call_api_key).strip() if bot.call_api_key else ''
    token = decrypt_value(bot.call_api_secret).strip() if bot.call_api_secret else ''
    from_num = (bot.call_phone_number or '').strip()
    if not sid or not token or not from_num:
        return {'ok': False, 'error': 'ناقص Account SID أو Auth Token أو رقم الاتصال'}

    base = (current_app.config.get('SITE_URL') or '').rstrip('/')
    if not base:
        return {'ok': False, 'error': 'SITE_URL غير مضبوط في السيرفر'}
    twiml_url = f'{base}/api/v1/webhooks/twilio/voice/{tenant_id}'

    to_clean = to_phone_e164.replace(' ', '').replace('-', '')
    if not to_clean.startswith('+'):
        if to_clean.startswith('0'):
            to_clean = '+966' + to_clean[1:]
        elif to_clean.startswith('966'):
            to_clean = '+' + to_clean
        else:
            to_clean = '+' + to_clean

    url = f'https://api.twilio.com/2010-04-01/Accounts/{sid}/Calls.json'
    try:
        r = requests.post(
            url,
            auth=(sid, token),
            data={
                'To': to_clean,
                'From': from_num.replace(' ', ''),
                'Url': twiml_url,
                'Method': 'GET',
            },
            timeout=30,
        )
        if r.status_code in (200, 201):
            return {'ok': True, 'data': r.json() if r.text else {}}
        err = r.text[:500]
        try:
            err = r.json().get('message', err)
        except Exception:
            pass
        return {'ok': False, 'error': err}
    except Exception as e:
        return {'ok': False, 'error': str(e)}

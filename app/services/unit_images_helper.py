"""
تجهيز صور الوحدات للعرض: نص أولاً ثم صور (واتساب + شات).
لا يغيّر مخرجات محرك النوايا — معالجة بعد الرد فقط.
"""
import re
from typing import Any, Dict, List, Optional

from flask import current_app


def reply_triggers_unit_images(reply_text: str) -> bool:
    if not reply_text:
        return False
    if 'صورة متاحة' in reply_text or '360°' in reply_text:
        return True
    # يطابق نص محرك النوايا (intent_engine) بعد إضافة سطر عدد الصور
    if 'عدد الصور المتاحة' in reply_text:
        return True
    if 'available images' in reply_text.lower():
        return True
    return False


def strip_photo_count_hints(text: str) -> str:
    """يزيل أسطر تلميح عدد الصور من نص الوحدات عند إرسال الصور فعلياً."""
    if not text:
        return text
    t = re.sub(r'\n  📸 \d+ صورة متاحة', '', text)
    t = re.sub(r'\n  عدد الصور المتاحة: \d+', '', text)
    t = re.sub(r'\n  Number of available images: \d+', '', text, flags=re.IGNORECASE)
    t = re.sub(r'\n{3,}', '\n\n', t)
    return t.strip()


def absolute_media_url(url_or_path: str) -> str:
    u = (url_or_path or '').strip()
    if not u:
        return u
    if u.startswith('http://') or u.startswith('https://'):
        return u
    base = (current_app.config.get('SITE_URL') or 'http://localhost:5000').rstrip('/')
    if u.startswith('/'):
        return base + u
    return f'{base}/{u.lstrip("/")}'


def collect_unit_public_image_urls(
    tenant_id: int, unit_ids: Optional[List[int]] = None,
) -> List[str]:
    """حتى 4 صور. إن وُجدت unit_ids يُفضّل ترتيبها؛ وإلا أول وحدات متاحة لها صور."""
    from app.models.hotel_models import Unit

    out: List[str] = []
    n = 0
    if unit_ids:
        for uid in unit_ids:
            if not uid:
                continue
            u = Unit.query.filter_by(
                id=int(uid), tenant_id=tenant_id, is_available=True,
            ).first()
            if not u or not u.images:
                continue
            for raw in u.images[:2]:
                out.append(absolute_media_url(raw))
                n += 1
                if n >= 4:
                    return out
        return out

    units = Unit.query.filter_by(tenant_id=tenant_id, is_available=True).all()
    for u in units[:3]:
        if not u.images:
            continue
        for raw in u.images[:2]:
            out.append(absolute_media_url(raw))
            n += 1
            if n >= 4:
                return out
    return out


def prepare_bot_reply_delivery(
    tenant_id: int, reply_text: str, conversation=None,
) -> Dict[str, Any]:
    """
    يرجع نصاً للعرض (من دون تلميحات صور إن وُجدت صور فعلياً)
    + قائمة روابط جاهزة للعرض/ميتا.
    """
    result: Dict[str, Any] = {
        'text': reply_text,
        'images': [],
        'extra_data': {},
    }
    focus_ids: Optional[List[int]] = None
    try:
        if conversation is not None:
            ex = getattr(conversation, 'extra_data', None) or {}
            if isinstance(ex, dict):
                hc = ex.get('hotel_ctx') or {}
                if isinstance(hc, dict):
                    raw_ids = hc.get('image_delivery_unit_ids')
                    if isinstance(raw_ids, list) and raw_ids:
                        focus_ids = [int(x) for x in raw_ids if str(x).isdigit()]
    except Exception:
        focus_ids = None

    if not reply_triggers_unit_images(reply_text) and not focus_ids:
        return result
    urls = collect_unit_public_image_urls(tenant_id, focus_ids)
    if not urls:
        return result
    # لا نعيد استخدام معرّفات التركيز في الرسالة التالية
    if conversation is not None and focus_ids:
        try:
            ex = dict(conversation.extra_data or {}) if isinstance(conversation.extra_data, dict) else {}
            hc = dict(ex.get('hotel_ctx') or {}) if isinstance(ex.get('hotel_ctx'), dict) else {}
            hc.pop('image_delivery_unit_ids', None)
            ex['hotel_ctx'] = hc
            conversation.extra_data = ex
        except Exception:
            pass
    cleaned = strip_photo_count_hints(reply_text)
    if not (cleaned or '').strip():
        cleaned = 'صور الوحدات المتاحة 👇'
    result['text'] = cleaned
    result['images'] = urls
    result['extra_data'] = {'images': urls}
    return result

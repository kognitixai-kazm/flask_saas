"""
حالة محادثة خفيفة (FSM) لضبط متى تُعرض القائمة كاملة دون التداخل مع الاستفسارات.
تُخزَّن داخل conversations.extra_data فقط — بدون جداول جديدة.
"""
from __future__ import annotations

from typing import Any

MODE_GENERAL = 'general'
MODE_ORDERING = 'ordering'

# كلمات صريحة تسمح بعرض المنيو/الأسعار الكامل حتى خارج وضع الطلب
STRONG_ROOMS_MARKERS = (
    'غرف',
    'غرفه',
    'غرفة',
    'غرفتين',
    'وحده',
    'وحدات',
    'جناح',
    'شقه',
    'شقة',
    'شقق',
    'انواع الغرف',
    'نوع الغرفه',
)


STRONG_MENU_MARKERS = (
    'منيو',
    'منيوكم',
    'قائمه',
    'قائمة',
    'القائمه',
    'القائمة',
    'قائمة الطعام',
    'اصناف',
    'الاصناف',
    'الأصناف',
)


def _extra(conv) -> dict[str, Any]:
    ex = getattr(conv, 'extra_data', None) or {}
    return ex if isinstance(ex, dict) else {}


def get_mode(conv) -> str:
    if not conv:
        return MODE_GENERAL
    ex = _extra(conv)
    if isinstance(ex.get('pending_inquiry'), dict):
        return 'inquiry_pending'
    fsm = ex.get('dialog_fsm')
    if isinstance(fsm, dict):
        m = (fsm.get('mode') or MODE_GENERAL).strip()
        if m == MODE_ORDERING:
            return MODE_ORDERING
    return MODE_GENERAL


def allow_full_room_browse(conv, msg_normalized: str) -> bool:
    if not msg_normalized:
        return False
    if any(k in msg_normalized for k in STRONG_ROOMS_MARKERS):
        return True
    return get_mode(conv) == MODE_ORDERING


def allow_full_menu(conv, msg_normalized: str) -> bool:
    """عرض قائمة كاملة: إن كان الزائر في وضع طلب/تصفح طلب، أو استخدم كلمات صريحة."""
    if not msg_normalized:
        return False
    if any(k in msg_normalized for k in STRONG_MENU_MARKERS):
        return True
    return get_mode(conv) == MODE_ORDERING


def mark_ordering(conv) -> None:
    if not conv:
        return
    ex = dict(_extra(conv))
    fsm = dict(ex.get('dialog_fsm') or {})
    fsm['mode'] = MODE_ORDERING
    ex['dialog_fsm'] = fsm
    conv.extra_data = ex
    try:
        from sqlalchemy.orm.attributes import flag_modified

        flag_modified(conv, 'extra_data')
    except Exception:
        pass


def mark_general(conv) -> None:
    if not conv:
        return
    ex = dict(_extra(conv))
    fsm = dict(ex.get('dialog_fsm') or {})
    fsm['mode'] = MODE_GENERAL
    ex['dialog_fsm'] = fsm
    conv.extra_data = ex
    try:
        from sqlalchemy.orm.attributes import flag_modified

        flag_modified(conv, 'extra_data')
    except Exception:
        pass


def apply_after_intent(conv, intent: str, opened_full_menu: bool) -> None:
    """تحديث الحالة بعد معالجة نية معروفة (بدون commit)."""
    if not conv:
        return
    if opened_full_menu or intent in ('ordering', 'reservation', 'menu_item'):
        mark_ordering(conv)
        return
    if intent in ('greeting', 'goodbye', 'thanks', 'complaint'):
        mark_general(conv)
        return

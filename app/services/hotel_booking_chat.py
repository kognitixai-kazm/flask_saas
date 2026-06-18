"""
متابعة حجز الفندق من الشات: تواريخ بعد إنشاء الحجز، وربط الدفع بالعقد الإلكتروني.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from app.extensions import db
from app.models.booking import Booking
from app.models.contract_template import ContractTemplate
from app.models.conversation import Conversation
from app.models.tenant import Tenant


def _hotel_ctx(conv: Conversation) -> Dict[str, Any]:
    ex = conv.extra_data or {}
    if not isinstance(ex, dict):
        ex = {}
    hc = ex.get('hotel_ctx')
    if not isinstance(hc, dict):
        hc = {}
    return hc


def _save_hotel_ctx(conv: Conversation, hc: Dict[str, Any]) -> None:
    ex = dict(conv.extra_data or {}) if isinstance(conv.extra_data, dict) else {}
    if hc:
        ex['hotel_ctx'] = hc
    else:
        ex.pop('hotel_ctx', None)
    conv.extra_data = ex


def persist_intent_pipeline_meta(conv: Conversation, meta: Dict[str, Any]) -> None:
    """يحفظ معلومات من محرك النوايا (قائمة وحدات، حجز جديد) في المحادثة."""
    if not conv or not meta:
        return
    hc = _hotel_ctx(conv)
    lids = meta.get('listed_unit_ids')
    if isinstance(lids, list) and lids:
        clean = [int(x) for x in lids if str(x).isdigit()]
        hc['last_listed_unit_ids'] = clean[:24]
        if clean:
            hc['last_suggested_unit_id'] = clean[0]
    bid = meta.get('hotel_booking_id')
    if bid and str(bid).isdigit():
        hc['pending_booking_id'] = int(bid)
        hc['booking_stage'] = 'awaiting_details'
    img_ids = meta.get('image_delivery_unit_ids')
    if isinstance(img_ids, list) and img_ids:
        hc['image_delivery_unit_ids'] = [int(x) for x in img_ids if str(x).isdigit()]
    if meta.get('clear_image_delivery'):
        hc.pop('image_delivery_unit_ids', None)
    _save_hotel_ctx(conv, hc)


def _parse_short_dates(text: str) -> Optional[Tuple[date, date, Optional[int]]]:
    """
    يستخرج تاريخي دخول/خروج من جمل مثل: الدخول 2/5 الخروج 3/5
    يُفسَّر كيوم/شهر بالتقويم الميلادي (سنة حالية).
    """
    raw = (text or '').strip()
    if not raw:
        return None
    t = raw
    for a, b in (('أ', 'ا'), ('إ', 'ا'), ('آ', 'ا'), ('٫', '/'), ('-', '/'), ('.', '/')):
        t = t.replace(a, b)

    def _pair(pat: str) -> Optional[Tuple[int, int]]:
        m = re.search(pat, t, flags=re.IGNORECASE)
        if not m:
            return None
        a, b = int(m.group(1)), int(m.group(2))
        return a, b

    y = datetime.utcnow().year
    cin = None
    cout = None

    p_in = _pair(r'(?:دخول|الدخول|وصول|الوصول|checkin|check-in|check in|arrival)\s*:?\s*(\d{1,2})\s*/\s*(\d{1,2})')
    p_out = _pair(r'(?:خروج|الخروج|مغادره|المغادره|checkout|check-out|check out|departure)\s*:?\s*(\d{1,2})\s*/\s*(\d{1,2})')
    if p_in and p_out:
        d1, m1 = p_in
        d2, m2 = p_out
        try:
            cin = date(y, m1, d1)
            cout = date(y, m2, d2)
        except ValueError:
            return None
    else:
        pairs = re.findall(r'(\d{1,2})\s*/\s*(\d{1,2})', t)
        if len(pairs) < 2:
            return None
        d1, m1 = int(pairs[0][0]), int(pairs[0][1])
        d2, m2 = int(pairs[1][0]), int(pairs[1][1])
        try:
            cin = date(y, m1, d1)
            cout = date(y, m2, d2)
        except ValueError:
            return None

    guests = None
    mg = re.search(
        r'(?:ضيوف|اشخاص|أشخاص|نفر|نفرات|عدد|guests|persons|people)\s*:?\s*(\d{1,2})',
        t,
        flags=re.IGNORECASE,
    )
    if mg:
        guests = int(mg.group(1))

    if cin and cout and cout <= cin:
        return None
    return cin, cout, guests


def _contract_triggers_hint(tenant_id: int) -> str:
    tpls = ContractTemplate.query.filter_by(
        tenant_id=tenant_id, is_active=True,
    ).order_by(ContractTemplate.id).limit(5).all()
    if not tpls:
        return (
            'لإتمام الدفع الإلكتروني أو التحويل البنكي وإصدار عقد إلكتروني، '
            'يحتاج صاحب النشاط تفعيل «قوالب العقود» من لوحة التحكم وإضافة كلمات تفعيل تذكرها لك هنا.'
        )
    parts = []
    for tpl in tpls:
        kws = tpl.trigger_keywords_list()[:2]
        if kws:
            parts.append(' أو '.join(f'«{k}»' for k in kws))
    if not parts:
        return (
            'لإتمام الدفع والعقد الإلكتروني: من لوحة التحكم — العقود — أضف للقالب «كلمات تفعيل» ثم اكتب إحداها هنا ليبدأ البوت جمع بياناتك واختيار طريقة الدفع.'
        )
    return (
        'لإتمام الدفع والعقد الإلكتروني (المدى/البطاقة أو التحويل البنكي ثم إصدار العقد)، '
        'اكتب إحدى عبارات التفعيل التي ضبطها صاحب النشاط، مثل: '
        + '، '.join(parts[:3])
        + '.\n'
        'سيطلب منك البوت البيانات خطوة بخطوة ثم يعرض خيارات الدفع كما في إعدادات العقود.'
    )


def handle_before_contract_flow(
    tenant: Tenant, conversation: Conversation, user_message: str,
) -> Optional[str]:
    """
    يُستدعى قبل مطابقة قوالب العقود ومحرك النوايا.
    يرجع نص رد أو None.
    """
    if not tenant.activity or (tenant.activity.code or '').strip().lower() != 'hotel':
        return None

    msg = (user_message or '').strip()
    if not msg:
        return None

    hc = _hotel_ctx(conversation)
    stage = (hc.get('booking_stage') or '').strip()
    pbid = hc.get('pending_booking_id')

    if pbid and stage == 'awaiting_details':
        parsed = _parse_short_dates(msg)
        if parsed:
            cin, cout, guests = parsed
            booking = Booking.query.filter_by(
                id=int(pbid), tenant_id=tenant.id,
            ).first()
            if booking and booking.status == 'new':
                booking.checkin_date = cin
                booking.checkout_date = cout
                if guests and guests > 0:
                    booking.guests_count = min(guests, 50)
                extra_note = f"\nتواريخ من الشات: دخول {cin.isoformat()} خروج {cout.isoformat()}"
                booking.notes = (booking.notes or '') + extra_note
                hc['booking_stage'] = 'details_received'
                hc.pop('pending_booking_id', None)
                _save_hotel_ctx(conversation, hc)
                db.session.commit()
                nights = (cout - cin).days
                hint = _contract_triggers_hint(tenant.id)
                return (
                    f"تم تسجيل تواريخ إقامتك على طلب الحجز رقم {booking.booking_number}:\n"
                    f"• الدخول: {cin.day}/{cin.month}\n"
                    f"• الخروج: {cout.day}/{cout.month}\n"
                    f"• الليالي: {nights}\n"
                    f"• عدد الأشخاص: {booking.guests_count}\n\n"
                    f"{hint}"
                )

    return None

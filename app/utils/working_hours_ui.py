"""
تحويل واجهة الدوام (سبت–خميس موحّد + جمعة + ملاحظات) ↔ JSON الفرع الحالي.
لا يغيّر شكل التخزين: {sat..fri: {shift1, shift2}, notes?}
"""
import re
from typing import Any, Dict, List, Tuple

WEEKDAY_KEYS: List[str] = ['sat', 'sun', 'mon', 'tue', 'wed', 'thu']


def _norm_hhmm(t: str) -> str:
    """تطبيع وقت لـ input type=time (HH:MM)."""
    t = (t or '').strip()
    if not t:
        return ''
    m = re.match(r'^(\d{1,2}):(\d{2})$', t)
    if not m:
        return t
    h, mi = int(m.group(1)), m.group(2)
    if h < 0 or h > 23:
        return t
    return f'{h:02d}:{mi}'


def _parse_shift_pair(shift_str: Any) -> Tuple[str, str]:
    if not shift_str or not isinstance(shift_str, str):
        return '', ''
    s = shift_str.strip()
    if '-' not in s:
        return '', ''
    left, right = s.split('-', 1)
    return _norm_hhmm(left.strip()), _norm_hhmm(right.strip())


def _compose_shift(open_t: Any, close_t: Any) -> str:
    o = (open_t or '').strip() if open_t is not None else ''
    c = (close_t or '').strip() if close_t is not None else ''
    if not o or not c:
        return ''
    return f'{o}-{c}'


def working_hours_from_request(form) -> Dict[str, Any]:
    """يبني dict ساعات العمل من حقول النموذج الجديدة."""
    hours: Dict[str, Any] = {}

    s1 = _compose_shift(form.get('week_s1_open'), form.get('week_s1_close'))
    s2 = ''
    if form.get('week_shift2'):
        s2 = _compose_shift(form.get('week_s2_open'), form.get('week_s2_close'))

    for d in WEEKDAY_KEYS:
        if s1 or s2:
            hours[d] = {}
            if s1:
                hours[d]['shift1'] = s1
            if s2:
                hours[d]['shift2'] = s2

    fri1 = _compose_shift(form.get('fri_s1_open'), form.get('fri_s1_close'))
    if fri1:
        hours['fri'] = {'shift1': fri1}

    notes = (form.get('hours_notes') or '').strip()
    if notes:
        hours['notes'] = notes[:2000]

    return hours


def working_hours_form_defaults(working_hours: Any) -> Dict[str, Any]:
    """قيم افتراضية للقالب من JSON محفوظ (مرجع السبت للأسبوع الموحّد)."""
    wh = working_hours or {}
    sat = wh.get('sat') or {}
    s1o, s1c = _parse_shift_pair(sat.get('shift1', ''))
    s2o, s2c = _parse_shift_pair(sat.get('shift2', ''))
    fri = wh.get('fri') or {}
    fo, fc = _parse_shift_pair(fri.get('shift1', ''))
    week_shift2 = bool(s2o and s2c)
    notes = wh.get('notes') or ''
    if not isinstance(notes, str):
        notes = str(notes)
    return {
        'week_s1_open': s1o,
        'week_s1_close': s1c,
        'week_s2_open': s2o,
        'week_s2_close': s2c,
        'week_shift2': week_shift2,
        'fri_s1_open': fo,
        'fri_s1_close': fc,
        'hours_notes': notes,
    }

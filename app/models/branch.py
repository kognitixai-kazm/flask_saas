"""
app/models/branch.py — الفروع: مشترك بين كل الأنشطة.
كل فرع مرتبط بـ tenant_id = عزل كامل.
"""
import re
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from ..extensions import db

_DAY_ORDER = ('sat', 'sun', 'mon', 'tue', 'wed', 'thu', 'fri')
_DAY_AR = {
    'sat': 'السبت', 'sun': 'الأحد', 'mon': 'الاثنين',
    'tue': 'الثلاثاء', 'wed': 'الأربعاء', 'thu': 'الخميس', 'fri': 'الجمعة',
}
_PY_WEEKDAY_TO_KEY = {0: 'mon', 1: 'tue', 2: 'wed', 3: 'thu', 4: 'fri', 5: 'sat', 6: 'sun'}


def _lrm_wrap(s: str) -> str:
    t = (s or '').strip()
    if not t:
        return t
    return f'\u200e{t}\u200e'


def _split_shift_segment(seg: str):
    if not seg or not isinstance(seg, str):
        return None
    s = seg.replace('–', '-').replace('−', '-').replace('—', '-').strip()
    parts = re.split(r'\s*-\s*', s, maxsplit=1)
    if len(parts) != 2:
        return None
    a, b = parts[0].strip(), parts[1].strip()
    if not a or not b:
        return None
    return a, b


def _to_minutes(hhmm: str):
    m = re.match(r'^(\d{1,2})\s*[:.]\s*(\d{2})$', (hhmm or '').strip())
    if not m:
        return None
    h, mm = int(m.group(1)), int(m.group(2))
    if h > 23 or mm > 59:
        return None
    return h * 60 + mm


def _format_shift_phrase(seg: str) -> str:
    sp = _split_shift_segment(seg)
    if not sp:
        return f"من الساعة {_lrm_wrap(seg)}"
    a, b = sp
    return f"من الساعة {_lrm_wrap(a)} إلى الساعة {_lrm_wrap(b)}"


def _day_data(wh: dict, key: str) -> dict:
    slot = (wh or {}).get(key)
    return slot if isinstance(slot, dict) else {}


def _signature_for_day(wh: dict, key: str):
    d = _day_data(wh, key)
    s1 = (d.get('shift1') or '').strip()
    s2 = (d.get('shift2') or '').strip()
    if not s1 and not s2:
        return ('closed',)
    return ('open', s1, s2)


def _day_range_ar(keys: list) -> str:
    if len(keys) == 1:
        return _DAY_AR[keys[0]]
    return f"من {_DAY_AR[keys[0]]} إلى {_DAY_AR[keys[-1]]}"


def _describe_signature(sig: tuple) -> str:
    if sig == ('closed',):
        return 'مغلق'
    parts = []
    if sig[1]:
        parts.append(f"الفترة الأولى {_format_shift_phrase(sig[1])}")
    if len(sig) > 2 and sig[2]:
        parts.append(f"الفترة الثانية {_format_shift_phrase(sig[2])}")
    return '؛ '.join(parts) if parts else 'مغلق'


class Branch(db.Model):
    __tablename__ = 'branches'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)

    name = db.Column(db.String(200), nullable=False)
    address = db.Column(db.Text, default='')
    city = db.Column(db.String(100), default='')
    map_link = db.Column(db.String(500), default='')
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)

    phone = db.Column(db.String(30), default='')
    whatsapp = db.Column(db.String(30), default='')
    email = db.Column(db.String(255), default='')
    complaints_email = db.Column(db.String(255), default='')

    # ساعات العمل مهيكلة (JSON)
    # الشكل: {"sun": {"shift1": "8:00-14:00", "shift2": "16:00-22:00"},
    #          "fri": {"shift1": "16:00-23:00"}, ...}
    working_hours = db.Column(db.JSON, default=dict)

    is_main = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # علاقات
    tenant = db.relationship('Tenant', backref=db.backref('branches', lazy='dynamic', cascade='all, delete-orphan'))

    # علاقات الفندق
    floors = db.relationship('Floor', back_populates='branch', cascade='all, delete-orphan', lazy='dynamic')
    units = db.relationship('Unit', back_populates='branch', cascade='all, delete-orphan', lazy='dynamic')

    # علاقات المطعم
    menu_items = db.relationship('MenuItem', back_populates='branch', cascade='all, delete-orphan', lazy='dynamic')

    # الاستفسارات
    inquiries = db.relationship('Inquiry', back_populates='branch', cascade='all, delete-orphan', lazy='dynamic')

    def get_hours_display(self, day_key: str) -> str:
        """عرض ساعات يوم معين بشكل نصي."""
        hours = (self.working_hours or {}).get(day_key, {})
        if not hours:
            return 'مغلق'
        parts = []
        if hours.get('shift1'):
            parts.append(f"الفترة الأولى: {hours['shift1']}")
        if hours.get('shift2'):
            parts.append(f"الفترة الثانية: {hours['shift2']}")
        return ' | '.join(parts) if parts else 'مغلق'

    def get_all_hours_text(self) -> str:
        """نص كامل لساعات العمل."""
        DAY_NAMES = {
            'sat': 'السبت', 'sun': 'الأحد', 'mon': 'الاثنين',
            'tue': 'الثلاثاء', 'wed': 'الأربعاء', 'thu': 'الخميس', 'fri': 'الجمعة'
        }
        if not self.working_hours:
            return "   لم تُحدد ساعات العمل"
        lines = []
        for key, name in DAY_NAMES.items():
            display = self.get_hours_display(key)
            lines.append(f"   {name}: {display}")
        notes = (self.working_hours or {}).get('notes')
        if notes and isinstance(notes, str) and notes.strip():
            lines.append(f"   ملاحظات: {notes.strip()}")
        return "\n".join(lines)

    def _has_scheduled_hours(self) -> bool:
        wh = self.working_hours if isinstance(self.working_hours, dict) else {}
        for k in _DAY_ORDER:
            if _signature_for_day(wh, k) != ('closed',):
                return True
        return False

    def is_open_at_local(self, now: Optional[datetime] = None, timezone_name: Optional[str] = None) -> bool:
        """هل الوقت الحالي (بتوقيت المنشأة) ضمن فترات الدوام المسجّلة."""
        wh = self.working_hours if isinstance(self.working_hours, dict) else {}
        if not wh:
            return False
        tzname = (timezone_name or '').strip() or 'Asia/Riyadh'
        try:
            zi = ZoneInfo(tzname)
        except Exception:
            zi = ZoneInfo('Asia/Riyadh')
        if now is None:
            now = datetime.now(zi)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=ZoneInfo('UTC')).astimezone(zi)
        else:
            now = now.astimezone(zi)

        now_min = now.hour * 60 + now.minute
        wd = now.weekday()
        today_key = _PY_WEEKDAY_TO_KEY[wd]
        yesterday_key = _PY_WEEKDAY_TO_KEY[(wd - 1) % 7]

        d_prev = _day_data(wh, yesterday_key)
        for sk in ('shift1', 'shift2'):
            seg = (d_prev.get(sk) or '').strip()
            if not seg:
                continue
            sp = _split_shift_segment(seg)
            if not sp:
                continue
            ma, mb = _to_minutes(sp[0]), _to_minutes(sp[1])
            if ma is None or mb is None:
                continue
            if mb <= ma and now_min < mb:
                return True

        d_today = _day_data(wh, today_key)
        for sk in ('shift1', 'shift2'):
            seg = (d_today.get(sk) or '').strip()
            if not seg:
                continue
            sp = _split_shift_segment(seg)
            if not sp:
                continue
            ma, mb = _to_minutes(sp[0]), _to_minutes(sp[1])
            if ma is None or mb is None:
                continue
            if mb > ma:
                if ma <= now_min < mb:
                    return True
            else:
                if now_min >= ma or now_min < mb:
                    return True
        return False

    @staticmethod
    def _visitor_hours_status_phrase(activity_code: str, open_ok: bool) -> str:
        ac = (activity_code or '').strip().lower()
        if open_ok:
            if ac == 'hotel':
                return (
                    'حاليًا ضمن أوقات الدوام أعلاه — الاستقبال يخدمك ويمكنك متابعة الحجز أو الاستفسار من هنا.'
                )
            if ac == 'restaurant':
                return (
                    'حاليًا ضمن أوقات الدوام أعلاه — المطعم يخدمك ويمكنك متابعة الطلب أو الاستفسار من هنا.'
                )
            return 'حاليًا ضمن أوقات الدوام أعلاه — تحت خدمتك للرد على استفسارك.'

        if ac == 'hotel':
            return (
                'حاليًا خارج أوقات الفتح ضمن الجدول أعلاه؛ تقدر تترك استفسارك هنا أو التواصل خلال الدوام.'
            )
        if ac == 'restaurant':
            return (
                'حاليًا خارج أوقات الفتح ضمن الجدول أعلاه؛ تقدر تكتب طلبك هنا ويتابع معك الفريق عند التوفر.'
            )
        return 'حاليًا خارج أوقات الفتح ضمن الجدول أعلاه؛ يمكنك ترك استفسارك هنا.'

    def format_working_hours_visitor_ar(self, activity_code: str = '', timezone_name: Optional[str] = None) -> str:
        """نص عربي للزائر: تجميع الأيام المتشابهة + فترتان + حالة الفتح حسب الوقت الفعلي."""
        wh = self.working_hours if isinstance(self.working_hours, dict) else {}
        if not self._has_scheduled_hours():
            return 'لم تُحدد ساعات العمل في لوحة التحكم بعد.'

        lines = []
        i = 0
        keys = list(_DAY_ORDER)
        while i < len(keys):
            sig = _signature_for_day(wh, keys[i])
            j = i
            while j + 1 < len(keys) and _signature_for_day(wh, keys[j + 1]) == sig:
                j += 1
            group = keys[i : j + 1]
            label = _day_range_ar(group)
            body = _describe_signature(sig)
            lines.append(f'• {label}: {body}.')
            i = j + 1
        notes = wh.get('notes')
        if notes and isinstance(notes, str) and notes.strip():
            lines.append(f'• ملاحظات: {notes.strip()}')

        open_ok = self.is_open_at_local(timezone_name=timezone_name)
        status = self._visitor_hours_status_phrase(activity_code, open_ok)
        return '\n'.join(lines) + '\n\n' + status

    def __repr__(self):
        return f'<Branch {self.name} tenant={self.tenant_id}>'

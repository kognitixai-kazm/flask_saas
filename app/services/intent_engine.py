"""
app/services/intent_engine.py — محرك الردود الذكية (مُصلح).

الخوارزمية الجديدة:
- إذا تطابقت كلمة مفتاحية واحدة على الأقل → النية مكتشفة
- الأولوية للنية الأكثر تطابقاً (عدد الكلمات المطابقة)
- لا يقسم على إجمالي الكلمات (هذا كان سبب المشكلة)
"""
import re
from difflib import SequenceMatcher
from typing import Optional, Tuple
from app.extensions import db


class IntentResult:
    def __init__(
        self,
        reply=None,
        needs_inquiry=False,
        inquiry_question='',
        intent='',
        inquiry_meta=None,
        pipeline_meta=None,
    ):
        self.reply = reply
        self.needs_inquiry = needs_inquiry
        self.inquiry_question = inquiry_question
        self.intent = intent
        self.inquiry_meta = inquiry_meta or {}
        self.pipeline_meta = pipeline_meta or {}


class IntentEngine:
    def __init__(self, tenant):
        self.tenant = tenant
        self.tenant_id = tenant.id
        self.activity_code = tenant.activity.code if tenant.activity else ''
        self.business_name = tenant.business_name
        self._active_conversation = None
        self._agent_gender = 'neutral'
        self._bot_name = ''

    def _load_agent_voice(self):
        """صياغة الوكيل (ذكر/أنثى/محايد) + اسم اختياري من إعدادات البوت."""
        self._agent_gender = 'neutral'
        self._bot_name = ''
        try:
            from app.models.bot_config import BotConfig
            bc = BotConfig.query.filter_by(tenant_id=self.tenant_id).first()
            if bc:
                g = (getattr(bc, 'agent_gender', None) or 'neutral').strip().lower()
                if g in ('male', 'female', 'neutral'):
                    self._agent_gender = g
                self._bot_name = (bc.bot_name or '').strip()
        except Exception:
            pass

    def _tenant_timezone(self) -> str:
        try:
            s = getattr(self.tenant, 'settings', None) or {}
            if isinstance(s, dict):
                tz = (s.get('timezone') or s.get('time_zone') or '').strip()
                if tz:
                    return tz
        except Exception:
            pass
        return 'Asia/Riyadh'

    def _is_first_visitor_message(self) -> bool:
        """أول رسالة زائر في هذه المحادثة (بعد حفظ الرسالة الحالية في قاعدة البيانات)."""
        conv = getattr(self, '_active_conversation', None)
        if not conv or not getattr(conv, 'id', None):
            return True
        try:
            from app.models.conversation import Message
            n = Message.query.filter_by(
                conversation_id=conv.id,
                sender_type='visitor',
            ).count()
            return n <= 1
        except Exception:
            return True

    def _ready_phrase(self) -> str:
        if self._is_first_visitor_message():
            if self._agent_gender == 'female':
                return 'يشرّفنا نخدمك، من أي استفسار تحبّين نبدأ؟'
            if self._agent_gender == 'male':
                return 'يشرّفنا نخدمك، من أي استفسار تحبّ نبدأ؟'
            return 'يشرّفنا نخدمك، من أي استفسار نبدأ به؟'
        if self._agent_gender == 'female':
            return 'جاهزة أكمّل معك في أي استفسار.'
        if self._agent_gender == 'male':
            return 'جاهز أكمّل معك في أي استفسار.'
        return 'نكمل معك في أي استفسار بكل ود.'

    def _thanks_body(self, activity_hint: str) -> str:
        if self._bot_name:
            base = f"العفو، وشكراً لتواصلك معنا. معك {self._bot_name} من {self.business_name}."
        elif self._agent_gender == 'female':
            base = f"العفو، وشكراً لتواصلك مع {self.business_name}. يسعدني أخدمك."
        elif self._agent_gender == 'male':
            base = f"العفو، وشكراً لتواصلك مع {self.business_name}. يسعدني أخدمك."
        else:
            base = f"العفو، وشكراً لتواصلك مع {self.business_name}. نتشرّف بخدمتك."
        return f"{base} {activity_hint}".strip()

    def _goodbye_body(self) -> str:
        if self._agent_gender == 'female':
            return (
                f"مع السلامة، ونتمنى لك يوم طيّب. {self.business_name} حاضرة "
                "لو احتجت أي شيء لاحقاً."
            )
        if self._agent_gender == 'male':
            return (
                f"مع السلامة، ونتمنى لك يوم طيّب. {self.business_name} حاضر "
                "لو احتجت أي شيء لاحقاً."
            )
        return (
            f"مع السلامة، ونتمنى لك يوم طيّب. نرحّب بك في {self.business_name} "
            "في أي وقت."
        )

    def _small_talk_body(self) -> str:
        line1 = "الحمد لله بخير، وأسأل الله يحفظك."
        if self._agent_gender == 'female':
            line2 = f"وش اللي يهمّك الآن بخصوص {self.business_name}؟ أقدر أرتّب لك المعلومة."
        elif self._agent_gender == 'male':
            line2 = f"وش اللي يهمّك الآن بخصوص {self.business_name}؟ أقدر أرتّب لك المعلومة."
        else:
            line2 = f"وش اللي يهمّك الآن بخصوص {self.business_name}؟ نرتّب لك المعلومة بسرعة."
        return f"{line1}\n{line2}"

    def _apply_fsm_hint(self, res: IntentResult) -> None:
        conv = getattr(self, '_active_conversation', None)
        if not conv:
            return
        try:
            from app.services.dialog_fsm_service import apply_after_intent

            pm = getattr(res, 'pipeline_meta', None) or {}
            apply_after_intent(conv, res.intent or '', pm.get('fsm_opened_full_menu') is True)
        except Exception:
            pass

    def _booking_customer_context(self):
        """بيانات العميل وربط الحجز بالمحادثة (ويب / واتساب)."""
        conv = getattr(self, '_active_conversation', None)
        if not conv:
            return {
                'customer_name': '',
                'customer_phone': '',
                'customer_email': '',
                'conversation_id': None,
                'visitor_id': '',
                'source': 'chat',
            }
        name = (conv.visitor_name or '').strip() or 'عميل'
        phone = (conv.visitor_phone or '').strip() or ''
        email = (conv.visitor_email or '').strip() or ''
        ch = getattr(conv, 'channel', None) or 'web'
        source = 'whatsapp' if ch == 'whatsapp' else 'chat'
        return {
            'customer_name': name,
            'customer_phone': phone,
            'customer_email': email,
            'conversation_id': conv.id,
            'visitor_id': (conv.visitor_id or '').strip(),
            'source': source,
        }

    def process(self, message: str, conversation=None) -> IntentResult:
        self._active_conversation = conversation
        try:
            self._load_agent_voice()
            msg = self._normalize(message)

            def _trace(msg_txt: str):
                try:
                    from flask import current_app

                    current_app.logger.info(
                        '[IntentEngine] tenant=%s %s', self.tenant_id, msg_txt,
                    )
                except Exception:
                    pass

            _trace('start')

            # ==========================================
            # 1️⃣ ردود التاجر المخصصة (أعلى أولوية)
            # ==========================================
            try:
                from app.models.custom_reply import CustomReply

                _trace('before custom_reply')
                custom = CustomReply.find_reply(self.tenant_id, message)
                _trace('after custom_reply')
                if custom:
                    return IntentResult(reply=custom.reply_text, intent='custom_reply')
            except Exception:
                pass

            # ==========================================
            # 2.5 — مطعم: مطابقة اسم صنف من القائمة (قبل النيات؛ نفس tenant فقط)
            # ==========================================
            if self.activity_code == 'restaurant':
                try:
                    dish_reply = self._restaurant_menu_item_quick_reply(message, msg)
                    if dish_reply:
                        return IntentResult(reply=dish_reply, intent='menu_item')
                except Exception:
                    pass

            # ==========================================
            # 2.6 — فندق: اختيار وحدة بالرقم («تمام رقم 101»، «ابغى الشقة 205»)
            # نفحصها قبل كشف النية لأن «تمام» وحدها لا تطابق أي نية.
            # ==========================================
            if self.activity_code == 'hotel':
                try:
                    pick = self._handle_unit_pick(msg, message)
                    if pick is not None:
                        return self._finalize_result(pick)
                except Exception as _e:
                    _trace(f'unit_pick error: {_e}')

            # ==========================================
            # 3️⃣ الكلمات المفتاحية والقواعد الثابتة
            # ==========================================
            _trace('before _detect_intent')
            intent = self._detect_intent(msg)
            _trace(f'after _detect_intent intent={intent}')

            if not intent:
                quick_ack = msg in ('لا', 'مو', 'مش', 'لاا', 'لأ', 'لا لا')
                short = len(msg) <= 12 and msg.count(' ') <= 2
                if quick_ack or short:
                    return IntentResult(
                        reply='تمام، خلّيني أساعدك — اكتب سؤالك في جملة قصيرة لو تكرّمت.',
                        needs_inquiry=False,
                        intent='unknown',
                    )
                return IntentResult(
                    reply='',
                    needs_inquiry=False,
                    intent='unknown',
                )

            if self.activity_code not in ('hotel', 'restaurant') and intent == 'inquiry':
                return self._finalize_result(
                    IntentResult(
                        reply=(
                            'اذكر استفسارك باختصار، وبنكمّل معك من هنا. '
                            'إذا تحب نرفعه للفريق اكتب: نعم.'
                        ),
                        intent='inquiry',
                    )
                )

            if self.activity_code == 'hotel':
                _trace(f'before _hotel_respond intent={intent}')
                res = self._finalize_result(self._hotel_respond(intent, msg, message))
                _trace('after _hotel_respond')
            elif self.activity_code == 'restaurant':
                _trace(f'before _restaurant_respond intent={intent}')
                res = self._finalize_result(self._restaurant_respond(intent, msg, message))
                _trace('after _restaurant_respond')
            else:
                # نشاط عام: نرد محلياً للنوايا الشائعة بدل تصعيد كل شيء.
                generic_reply = self._generic_respond(intent, msg, message)
                if generic_reply:
                    res = self._finalize_result(IntentResult(reply=generic_reply, intent=intent))
                else:
                    # ليست لدينا إجابة محلية واضحة → نترك المسار لـ AI ثم للتصعيد.
                    res = IntentResult(reply='', intent='unknown')

            self._apply_fsm_hint(res)
            return res
        finally:
            self._active_conversation = None

    def _normalize(self, text: str) -> str:
        text = text.strip()
        text = re.sub(r'[\u0610-\u061A\u064B-\u065F\u0670]', '', text)
        text = re.sub(r'[إأآا]', 'ا', text)
        text = re.sub(r'ة', 'ه', text)
        text = re.sub(r'[؟?!.,،؛:()…\-_\"\']', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def _restaurant_menu_item_quick_reply(self, raw_message: str, msg_normalized: str) -> Optional[str]:
        """يطابق اسم صنف من جدول المنيو لنفس المستأجر (تقريب بسيط للأخطاء الإملائية)."""
        if not msg_normalized or len(msg_normalized) < 3:
            return None
        raw_lower = (raw_message or '').strip().lower()
        from app.models.restaurant_models import MenuItem

        items = (
            MenuItem.query.filter_by(tenant_id=self.tenant_id, is_available=True)
            .order_by(MenuItem.id.desc())
            .limit(400)
            .all()
        )
        if not items:
            return None
        tokens = [t for t in msg_normalized.split() if len(t) >= 3]
        if not tokens:
            tokens = [msg_normalized]
        best = None
        best_score = 0.0
        for it in items:
            nm = self._normalize(it.name or '')
            if len(nm) < 3:
                continue
            nm_lower = (it.name or '').strip().lower()
            if nm in msg_normalized:
                score = 1.0
            elif nm_lower and nm_lower in raw_lower:
                score = 0.99
            else:
                chunk_scores = [SequenceMatcher(None, msg_normalized, nm).ratio()]
                chunk_scores.extend(SequenceMatcher(None, tok, nm).ratio() for tok in tokens)
                score = max(chunk_scores)
            if score > best_score and score >= 0.84:
                best_score = score
                best = it
        if not best:
            return None
        price = best.discount_price or best.price
        return (
            f"نعم، عندنا {best.name} — {price} ريال.\n"
            "لو حاب تكمّل الطلب أو أي إضافة، اكتب هنا."
        )

    @staticmethod
    def _kw_matches(msg: str, kw: str) -> bool:
        """تطابق كلمة قصيرة كاملة فقط؛ الباقي substring كما كان."""
        kw = (kw or '').strip()
        if not kw:
            return False
        if len(kw) <= 2:
            for tok in msg.split():
                t = re.sub(r'[.,،؛:!?؟…]', '', tok)
                if t == kw:
                    return True
            return False
        return kw in msg

    def _conversation_intent_context(self, conversation, current_norm: str) -> str:
        """آخر رسائل الزائر (بدون الحالية) لدعم كشف النية دون فقد السياق."""
        if not conversation or not getattr(conversation, 'id', None):
            return ''
        from app.models.conversation import Message

        try:
            rows = (
                Message.query.filter_by(
                    conversation_id=conversation.id,
                    sender_type='visitor',
                )
                .order_by(Message.created_at.desc())
                .limit(5)
                .all()
            )
        except Exception:
            return ''
        if rows and current_norm:
            first_n = self._normalize(rows[0].content or '')
            if first_n == current_norm:
                rows = rows[1:]
        chunks = []
        for m in reversed(rows):
            t = self._normalize(m.content or '')
            if t:
                chunks.append(t)
        joined = ' '.join(chunks)
        if len(joined) > 400:
            joined = joined[-400:].lstrip()
        return joined.strip()

    def _personalize_reply(self, reply: Optional[str]) -> Optional[str]:
        """نداء مهني مرة واحدة فقط عند بداية المحادثة."""
        if not reply:
            return reply
        conv = getattr(self, '_active_conversation', None)
        if not conv:
            return reply
        raw = (conv.visitor_name or '').strip()
        if not raw:
            return reply
        first = raw.split()[0][:40]
        if not first or first.isdigit():
            return reply
        if not self._is_first_visitor_message():
            return reply
        head = reply[:80]
        if first in head:
            return reply
        title = 'أستاذة' if self._agent_gender == 'female' else 'أستاذ'
        caller = f"{title} {first}"
        if reply.startswith('وعليكم'):
            parts = reply.split('\n', 1)
            if len(parts) == 2:
                return f"{parts[0]}\n{caller}،\n{parts[1]}"
            return f"{caller}،\n{reply}"
        return f"{caller}،\n{reply}"

    def _finalize_result(self, res: IntentResult) -> IntentResult:
        # تخطّي التخصيص للترحيب لأن النداء يكون في الفقاعة الثانية المنفصلة
        skip = False
        if isinstance(res.pipeline_meta, dict) and res.pipeline_meta.get('skip_personalize'):
            skip = True
        if res.reply and not skip:
            res.reply = self._personalize_reply(res.reply)
        return res

    def _detect_intent(self, msg: str) -> Optional[str]:
        """كشف النية: أعلى نقاط تطابق؛ عند التعادل يُفضّل الأهم (دوام/موقع قبل التحية)."""
        intents = {**COMMON_INTENTS}
        if self.activity_code == 'hotel':
            intents.update(HOTEL_INTENTS)
        elif self.activity_code == 'restaurant':
            intents.update(RESTAURANT_INTENTS)

        scored = {}
        for intent_name, keywords in intents.items():
            matches = 0
            for kw in keywords:
                if IntentEngine._kw_matches(msg, kw):
                    matches += 1
                    if len(kw) > 4:
                        matches += 1  # وزن إضافي للكلمات الطويلة
            if matches > 0:
                scored[intent_name] = matches

        if not scored:
            return None

        best_matches = max(scored.values())
        tied = [name for name, m in scored.items() if m == best_matches]

        def _tie_rank(name: str) -> int:
            try:
                return INTENT_TIE_PRIORITY.index(name)
            except ValueError:
                return len(INTENT_TIE_PRIORITY) + 1

        tied.sort(key=_tie_rank)
        return tied[0]

    def _hotel_room_prefs(self, msg: str) -> Tuple[Optional[int], bool]:
        """عدد غرف النوم المطلوب (إن وُجد) + طلب صالة/مجلس."""
        want_br: Optional[int] = None
        wants_lv = bool(re.search(r'صاله|مجلس', msg))
        # ملاحظة مهمة: «غرفه/غرفة» وحدها = طلب وحدة من نوع غرفة (وليس غرف نوم).
        # نشترط وجود كلمات تدل على غرف النوم: «غرف نوم»/«غرفتين نوم»/«٢ غرف» إلخ.
        if re.search(r'غرفتين\s*(نوم)?', msg) or re.search(r'غرفتان\s*(نوم)?', msg):
            want_br = 2
        elif re.search(r'ثلاث\s*غرف|٣\s*غرف|3\s*غرف', msg):
            want_br = 3
        elif re.search(r'اربع\s*غرف|٤\s*غرف|4\s*غرف', msg):
            want_br = 4
        elif re.search(r'(\d+)\s*غرف\s*نوم', msg):
            m = re.search(r'(\d+)\s*غرف\s*نوم', msg)
            if m:
                want_br = int(m.group(1))
        return want_br, wants_lv

    @staticmethod
    def _detect_unit_type(msg: str) -> Optional[str]:
        """يحدّد نوع الوحدة المطلوبة من نص الزائر — يعيد القيمة الداخلية أو None.
        room | apartment | suite | villa
        ملاحظة: لا نستخدم word boundaries لأن «ال» تلتصق بالكلمة في العربية.
        """
        m = msg or ''
        # شقة (يجب فحصها قبل غرفة)
        if re.search(r'شقه|شقة|شقق', m):
            return 'apartment'
        # جناح / سويت
        if re.search(r'جناح|اجنحه|أجنحة|سويت|سوت', m):
            return 'suite'
        # فيلا
        if re.search(r'فيلا|فلل', m):
            return 'villa'
        # غرفة (مجردة، ليس «غرف نوم»)
        if re.search(r'غرفه|غرفة', m) and not re.search(r'غرف\s*نوم', m):
            return 'room'
        return None

    @staticmethod
    def _detect_branch_hint(msg: str) -> Optional[str]:
        """يستخرج اسم الفرع من جمل مثل «في الفرع X» أو «في الزويس»."""
        m = re.search(r'(?:في|ب)\s+(?:الفرع\s+|فرع\s+)?([\u0600-\u06ff]{3,30})', msg or '')
        if m:
            return m.group(1).strip()
        return None

    @staticmethod
    def _detect_unit_number(msg: str) -> Optional[str]:
        """يستخرج رقم وحدة محدد من جمل مثل «ابغى رقم 101» / «تمام رقم 205» / «ابغى الشقة 305»."""
        m = re.search(r'رقم\s+([0-9٠-٩]{1,8})', msg or '')
        if not m:
            # بعد كلمة نوع وحدة (مع أو بدون «ال»): «ابغى الشقة 305» / «تمام شقة 305»
            m = re.search(
                r'(?:شقه|شقة|غرفه|غرفة|جناح|سويت|فيلا)\s+([0-9٠-٩]{1,8})',
                msg or '',
            )
        if not m:
            # «ابغى 101» / «ابي 101» / «تمام 205»
            m = re.search(
                r'(?:ابغى|ابي|تمام|اخذ|احجز)\s+([0-9٠-٩]{2,8})\b',
                msg or '',
            )
        if not m:
            return None
        raw = m.group(1)
        normalized = raw.translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))
        return normalized.strip()

    def _hotel_wants_gallery(self, msg: str) -> bool:
        return any(
            h in msg
            for h in (
                'صور', 'صوره', 'صورة', 'اشوف', 'أشوف', 'شوف', 'معاينه',
                'معاينة', 'طلعها', 'عرض', 'ارسل صور', 'أرسل صور',
            )
        )

    def _hotel_gallery_for_units(self, unit_ids: list) -> Optional[IntentResult]:
        from app.models.hotel_models import Unit

        ids = [int(x) for x in unit_ids if str(x).isdigit()]
        if not ids:
            return None
        units = Unit.query.filter(
            Unit.id.in_(ids),
            Unit.tenant_id == self.tenant_id,
            Unit.is_available == True,  # noqa: E712
        ).order_by(Unit.id).all()
        if not units:
            return None
        lines = ['معاينة الوحدات التي كانت ضمن آخر قائمة عرضناها لك:\n']
        focus: list = []
        for u in units:
            line = f"• {u.type_label} رقم {u.unit_number}"
            if u.floor:
                line += f" (طابق {u.floor.number})"
            if u.images and len(u.images) > 0:
                line += f"\n  عدد الصور المتاحة: {len(u.images)}"
                focus.append(u.id)
            else:
                line += (
                    '\n  الصور لهذه الوحدة لسه ما رفعها الفريق — '
                    'لو تحب أرتّب لك تواصل من الفرع لإرسال صور مباشرة، '
                    'اكتب «أبي صور» وراح نحوّلها لهم.'
                )
            lines.append(line)
        lines.append('\nإذا حاب تكمّل حجز أو عقد، اكتب لي باختصار.')
        meta = {'listed_unit_ids': ids}
        if focus:
            meta['image_delivery_unit_ids'] = focus
        return IntentResult(reply='\n'.join(lines), intent='rooms', pipeline_meta=meta)

    # ========================================
    # اختيار وحدة بالرقم — يبدأ تدفق حجز للوحدة المطلوبة مباشرة
    # ========================================
    def _handle_unit_pick(self, msg: str, original: str) -> Optional[IntentResult]:
        """يكتشف «ابغى/تمام رقم 101» ويربطها بوحدة محددة لبدء الحجز."""
        if self.activity_code != 'hotel':
            return None

        unit_num = self._detect_unit_number(msg)
        if not unit_num:
            return None

        # تأكّد أن في نية شراء/حجز/تأكيد (لا نريد أن نلتقط أرقام عشوائية)
        intent_words = (
            'ابغى', 'ابي', 'تمام', 'موافق', 'اخذ', 'احجز', 'حجز', 'اقفل', 'اعتمد',
        )
        if not any(w in msg for w in intent_words):
            # لو قال «رقم 101» وحدها بدون نية، نعتبرها استفسار عن وحدة
            if 'رقم' not in msg:
                return None

        from app.models.hotel_models import Unit
        from app.models.booking import Booking

        # حاول إيجاد الوحدة:
        # 1) أولاً ضمن آخر وحدات معروضة (سياق المحادثة) — أدق
        # 2) ثم بحث عام في وحدات التاجر
        candidates = []
        conv = getattr(self, '_active_conversation', None)
        last_ids = []
        if conv and isinstance(conv.extra_data, dict):
            hc = conv.extra_data.get('hotel_ctx') or {}
            if isinstance(hc, dict):
                lids = hc.get('last_listed_unit_ids') or []
                if isinstance(lids, list):
                    last_ids = [int(x) for x in lids if str(x).isdigit()]

        if last_ids:
            candidates = Unit.query.filter(
                Unit.id.in_(last_ids),
                Unit.tenant_id == self.tenant_id,
                Unit.unit_number == unit_num,
                Unit.is_available == True,  # noqa: E712
            ).all()

        if not candidates:
            candidates = Unit.query.filter(
                Unit.tenant_id == self.tenant_id,
                Unit.unit_number == unit_num,
                Unit.is_available == True,  # noqa: E712
            ).all()

        if not candidates:
            return IntentResult(
                reply=(
                    f"ما لقينا وحدة متاحة برقم {unit_num} في فروعنا الحالية. "
                    "تحب أعرض لك الوحدات المتاحة الآن؟"
                ),
                intent='rooms',
            )

        # إن ذكر الزائر نوع الوحدة في رسالته، نُضيّق الاختيار
        wanted_type_hint = self._detect_unit_type(msg)
        if wanted_type_hint and len(candidates) > 1:
            narrowed = [u for u in candidates if u.unit_type == wanted_type_hint]
            if narrowed:
                candidates = narrowed

        # تضييق إضافي بفرع لو ذكر الزائر اسم الفرع
        branch_hint = self._detect_branch_hint(msg)
        if branch_hint and len(candidates) > 1:
            from app.models.branch import Branch
            branches_map = {
                b.id: (b.name or '').strip()
                for b in Branch.query.filter_by(tenant_id=self.tenant_id).all()
            }
            narrowed_b = [
                u for u in candidates
                if branch_hint in branches_map.get(u.branch_id, '')
                or branches_map.get(u.branch_id, '') in branch_hint
            ]
            if narrowed_b:
                candidates = narrowed_b

        # عند وجود أكثر من وحدة بنفس الرقم (مثلاً غرفة 101 وشقة 101) — اطلب التوضيح
        if len(candidates) > 1:
            type_label_ar = {
                'room': 'غرفة', 'apartment': 'شقة',
                'suite': 'جناح', 'villa': 'فيلا',
            }
            opts = []
            for u in candidates:
                lbl = type_label_ar.get(u.unit_type, u.unit_type)
                br = (u.branch.name if u.branch else '').strip()
                tail = f" — فرع {br}" if br else ''
                opts.append(f"• {lbl} رقم {u.unit_number}{tail}")
            return IntentResult(
                reply=(
                    f"عندنا أكثر من وحدة برقم {unit_num}. حدد لي الي تبيها:\n"
                    + "\n".join(opts)
                    + "\n(اكتب: ابغى الغرفة، أو ابغى الشقة، أو حدد اسم الفرع.)"
                ),
                intent='rooms',
            )

        unit = candidates[0]

        # أنشئ حجز جديد مرتبط بهذه الوحدة
        ctx = self._booking_customer_context()
        booking = Booking(
            tenant_id=self.tenant_id,
            booking_number=Booking.generate_booking_number(),
            booking_type='hotel_room',
            customer_name=ctx['customer_name'],
            customer_phone=ctx['customer_phone'],
            customer_email=ctx['customer_email'],
            conversation_id=ctx['conversation_id'],
            visitor_id=ctx['visitor_id'],
            source=ctx['source'],
            status='new',
            unit_id=unit.id,
            branch_id=unit.branch_id,
            requested_unit_type=unit.unit_type,
            notes=f"طلب وحدة محددة من الشات: {original}",
        )
        db.session.add(booking)
        db.session.commit()

        # رسالة موجّهة حسب نمط الفندق
        tenant_obj = getattr(self, 'tenant', None)
        mode = getattr(tenant_obj, 'hotel_mode', 'both') if tenant_obj else 'both'
        type_label_ar = {
            'room': 'الغرفة', 'apartment': 'الشقة',
            'suite': 'الجناح', 'villa': 'الفيلا',
        }
        nice_type = type_label_ar.get(unit.unit_type, 'الوحدة')

        prices = []
        if unit.daily_price and float(unit.daily_price) > 0 and mode != 'monthly':
            prices.append(f"{unit.daily_price} ريال/يوم")
        if unit.monthly_price and float(unit.monthly_price) > 0 and mode != 'daily':
            # في النمط اليومي قد تكون متاحة، نتركها
            prices.append(f"{unit.monthly_price} ريال/شهر")
        elif unit.monthly_price and float(unit.monthly_price) > 0 and mode == 'daily':
            prices.append(f"{unit.monthly_price} ريال/شهر")

        lines = [
            f"تمام، تم تسجيل طلبك على {nice_type} رقم {unit.unit_number} برقم حجز {booking.booking_number}.",
        ]
        if prices:
            lines.append("السعر: " + " | ".join(prices))

        if mode == 'monthly':
            # شهري → نتجه مباشرة لتدفق العقد
            from app.models.contract_template import ContractTemplate
            tpls = ContractTemplate.query.filter_by(
                tenant_id=self.tenant_id, is_active=True,
            ).first()
            if tpls:
                kws = tpls.trigger_keywords_list()[:1]
                kw = kws[0] if kws else 'عقد'
                lines.append(
                    f"\nلإصدار العقد الشهري والدفع: اكتب كلمة «{kw}» "
                    "وراح نبدأ بجمع بياناتك خطوة بخطوة."
                )
            else:
                lines.append(
                    "\nنرتّب لك العقد الشهري الآن. "
                    "اكتب «عقد» لبدء جمع البيانات الرسمية."
                )
        else:
            lines.append(
                "\nأرسل لي تواريخ الدخول والخروج (مثال: الدخول 5/2 الخروج 7/2) "
                "وعدد الأشخاص لو حاب تحدّد."
            )

        meta = {
            'hotel_booking_id': booking.id,
            'listed_unit_ids': [unit.id],
        }
        if unit.images:
            meta['image_delivery_unit_ids'] = [unit.id]

        return IntentResult(reply="\n".join(lines), intent='booking', pipeline_meta=meta)

    # ========================================
    # ردود عامة (لأي نشاط غير الفندق/المطعم) — تردّ على النوايا الشائعة محلياً
    # ========================================
    def _generic_respond(self, intent: str, msg: str, original: str) -> Optional[str]:
        from app.models.branch import Branch

        if intent == 'greeting':
            if ('السلام' in msg and 'عليكم' in msg) or ('سلام' in msg and 'عليكم' in msg):
                return (
                    f"وعليكم السلام ورحمة الله. أهلاً في {self.business_name}. "
                    f"{self._ready_phrase()}"
                )
            return f"أهلاً وسهلاً في {self.business_name}. {self._ready_phrase()}"

        if intent == 'thanks':
            return self._thanks_body('نتشرّف بخدمتك في أي وقت.')

        if intent == 'goodbye':
            return self._goodbye_body()

        if intent == 'location':
            branch = Branch.query.filter_by(
                tenant_id=self.tenant_id, is_active=True, is_main=True,
            ).first() or Branch.query.filter_by(
                tenant_id=self.tenant_id, is_active=True,
            ).first()
            if not branch:
                return None
            parts = [f"موقع {self.business_name}:"]
            if (branch.address or '').strip():
                parts.append(branch.address.strip())
            if (branch.location_url or '').strip():
                parts.append(f"خرائط جوجل: {branch.location_url.strip()}")
            if (branch.phone or '').strip():
                parts.append(f"للتواصل: {branch.phone.strip()}")
            if len(parts) == 1:
                return None
            return '\n'.join(parts)

        if intent == 'contact':
            branch = Branch.query.filter_by(
                tenant_id=self.tenant_id, is_active=True, is_main=True,
            ).first() or Branch.query.filter_by(
                tenant_id=self.tenant_id, is_active=True,
            ).first()
            if not branch or not (branch.phone or '').strip():
                return None
            return f"تواصل مع {self.business_name} على: {branch.phone.strip()}"

        if intent == 'working_hours':
            branch = Branch.query.filter_by(
                tenant_id=self.tenant_id, is_active=True, is_main=True,
            ).first() or Branch.query.filter_by(
                tenant_id=self.tenant_id, is_active=True,
            ).first()
            if not branch:
                return None
            try:
                return branch.format_working_hours_visitor_ar(
                    activity_code=self.activity_code or '',
                    timezone_name=self._tenant_timezone(),
                )
            except Exception:
                return None

        # نية لم نوفّر لها رداً محلياً → نتركها لـ AI ثم للتصعيد
        return None

    # ========================================
    # ردود الفنادق
    # ========================================
    def _hotel_respond(self, intent, msg, original):
        from app.models.branch import Branch
        from app.models.hotel_models import Unit, HotelService

        branches = Branch.query.filter_by(tenant_id=self.tenant_id, is_active=True).all()

        conv = getattr(self, '_active_conversation', None)
        if conv:
            try:
                ex = conv.extra_data or {}
                hc0 = ex.get('hotel_ctx') if isinstance(ex, dict) else None
                if isinstance(hc0, dict):
                    last_ids = hc0.get('last_listed_unit_ids') or []
                    if isinstance(last_ids, list) and last_ids and self._hotel_wants_gallery(msg):
                        gal = self._hotel_gallery_for_units(last_ids)
                        if gal:
                            return gal
            except Exception:
                pass

        if intent == 'greeting':
            # رسالة الترحيب أولاً، ثم رسالة منفصلة تدعو للاستفسار
            visitor_first = ''
            try:
                conv2 = getattr(self, '_active_conversation', None)
                vn = (conv2.visitor_name or '').strip() if conv2 else ''
                if vn:
                    visitor_first = vn.split()[0][:30]
            except Exception:
                visitor_first = ''
            title = 'أستاذة' if self._agent_gender == 'female' else 'أستاذ'

            if ('السلام' in msg and 'عليكم' in msg) or (
                'سلام' in msg and 'عليكم' in msg
            ):
                first_reply = "وعليكم السلام ورحمة الله وبركاته."
            else:
                first_reply = f"أهلاً وسهلاً في {self.business_name}."

            caller = f"{title} {visitor_first}، " if visitor_first else ""
            second_reply = (
                f"{caller}تفضّل بطلبك. تقدر تسأل عن الغرف، الشقق، الأسعار، التوفر، أو تفاصيل الحجز."
            )

            return IntentResult(
                reply=first_reply,
                intent=intent,
                pipeline_meta={
                    'extra_replies': [second_reply],
                    # نمنع التخصيص التلقائي حتى لا يتكرّر اسم الزائر في الفقاعة الأولى
                    'skip_personalize': True,
                },
            )

        if intent == 'small_talk':
            return IntentResult(reply=self._small_talk_body(), intent=intent)

        if intent == 'thanks':
            return IntentResult(
                reply=self._thanks_body('نتمنى لك إقامة طيبة.'),
                intent=intent,
            )

        if intent == 'goodbye':
            return IntentResult(reply=self._goodbye_body(), intent=intent)

        if intent == 'inquiry':
            return IntentResult(
                reply=(
                    f"أسعد أخدمك. اذكر استفسارك باختصار (موقع، خدمات، غرف، أسعار…) "
                    f"— أو اكتب «غرف» لو تبي تشوف أنواع الوحدات المتاحة."
                ),
                intent='inquiry',
            )

        if intent == 'pricing':
            units = Unit.query.filter_by(tenant_id=self.tenant_id, is_available=True).all()
            if not units:
                return IntentResult(
                    reply="لحظات، أراجع مع الفريق ونرجع لك هنا بأقرب وقت.",
                    intent=intent,
                )
            lines = [f"أسعار {self.business_name}:\n"]
            seen = set()
            for u in units[:15]:
                key = f"{u.type_label}-{u.daily_price}"
                if key in seen:
                    continue
                seen.add(key)
                line = f"• {u.type_label}"
                if u.title:
                    line += f" ({u.title})"
                prices = []
                if u.daily_price and float(u.daily_price) > 0:
                    prices.append(f"{u.daily_price} ريال/يوم")
                if u.monthly_price and float(u.monthly_price) > 0:
                    prices.append(f"{u.monthly_price} ريال/شهر")
                if prices:
                    line += f" — {' | '.join(prices)}"
                line += f"  [{u.branch.name}]" if u.branch else ''
                lines.append(line)
            lines.append("\nإذا حاب تكمّل خطوة الحجز أو عندك استفسار، اكتب لي هنا وأنا معك.")
            return IntentResult(reply="\n".join(lines), intent=intent)

        if intent == 'rooms':
            from app.services.dialog_fsm_service import allow_full_room_browse

            conv = getattr(self, '_active_conversation', None)
            if not allow_full_room_browse(conv, msg):
                return IntentResult(
                    reply=(
                        "أقدر أرتّب لك المعلومة: كم شخص؟ وهل تبي صالة أو غرف نوم محددة؟ "
                        "اكتب تفاصيلك، أو اكتب «غرف» لو تبي تشوف قائمة الوحدات المتاحة."
                    ),
                    intent='rooms',
                )

            units = Unit.query.filter_by(tenant_id=self.tenant_id, is_available=True).all()
            if not units:
                return IntentResult(
                    reply="لحظات، أتحقق من الغرف المتاحة وأرجع لك هنا.",
                    intent=intent,
                )

            want_br, wants_lv = self._hotel_room_prefs(msg)
            wanted_type = self._detect_unit_type(msg)
            branch_hint = self._detect_branch_hint(msg)
            had_criteria = (
                want_br is not None or wants_lv or wanted_type is not None or branch_hint is not None
            )

            # خريطة أسماء الفروع لمقارنة فضفاضة
            branch_lookup = {}
            if branch_hint:
                for b in branches:
                    branch_lookup[b.id] = (b.name or '').strip()

            def _branch_matches(u):
                if not branch_hint:
                    return True
                bname = branch_lookup.get(u.branch_id, '')
                # مقارنة فضفاضة (يحتوي/مطابق جزئي)
                return branch_hint in bname or bname in branch_hint

            def _unit_matches(u):
                if wanted_type is not None and u.unit_type != wanted_type:
                    return False
                if want_br is not None and (u.bedrooms_count or 0) < want_br:
                    return False
                if wants_lv and (u.living_rooms or 0) < 1 and (u.halls or 0) < 1:
                    return False
                if not _branch_matches(u):
                    return False
                return True

            filtered = [u for u in units if _unit_matches(u)] if had_criteria else units
            no_exact = had_criteria and not filtered

            type_label_ar = {
                'room': 'غرف', 'apartment': 'شقق',
                'suite': 'أجنحة', 'villa': 'فلل',
            }

            if no_exact:
                spec_parts = []
                if wanted_type:
                    spec_parts.append(type_label_ar.get(wanted_type, wanted_type))
                if want_br is not None:
                    spec_parts.append(f"{want_br} غرف نوم")
                if wants_lv:
                    spec_parts.append("صالة")
                if branch_hint:
                    spec_parts.append(f"فرع «{branch_hint}»")
                spec_txt = " + ".join(spec_parts) if spec_parts else "هذا الطلب"
                # عند تحديد نوع غير متوفر، لا نخلط بأنواع أخرى
                if wanted_type:
                    lines = [
                        f"حالياً ما عندنا {type_label_ar.get(wanted_type, wanted_type)} متاحة"
                        + (f" في {spec_txt}" if (wants_lv or want_br or branch_hint) else "")
                        + ".",
                        "تحب أعرض لك الأنواع الأخرى المتاحة (شقق/أجنحة/...)؟",
                    ]
                    return IntentResult(reply="\n".join(lines), intent=intent)
                lines = [
                    f"حالياً ما عندنا وحدة بالضبط على ({spec_txt}).",
                    "هذي أقرب الخيارات المتاحة عندنا:",
                    "",
                ]
                # عند تحديد فرع غير موجود لا نعرض فروع أخرى
                if branch_hint and not any(_branch_matches(u) for u in units):
                    return IntentResult(
                        reply=f"ما لقينا فرع باسم «{branch_hint}» ضمن فروعنا الحالية. تحب أرسل لك أقرب فرع؟",
                        intent=intent,
                    )
                display = [u for u in units if _branch_matches(u)][:12]
            else:
                header = "الوحدات المتاحة"
                if wanted_type:
                    header = f"{type_label_ar.get(wanted_type, 'الوحدات')} المتاحة"
                if branch_hint:
                    header += f" — فرع «{branch_hint}»"
                lines = [f"{header}:\n"]
                display = filtered[:12]

            for u in display:
                line = f"• {u.type_label} رقم {u.unit_number}"
                if u.floor:
                    line += f" (طابق {u.floor.number})"
                # التفاصيل الداخلية
                details = []
                if u.bedrooms_count:
                    details.append(f"{u.bedrooms_count} غرف نوم")
                if u.living_rooms:
                    details.append(f"{u.living_rooms} صالة")
                if u.halls:
                    details.append(f"{u.halls} مجلس")
                if u.bathrooms_count:
                    details.append(f"{u.bathrooms_count} حمام")
                if u.kitchens:
                    details.append(f"{u.kitchens} مطبخ")
                if details:
                    line += f"\n  تفاصيل: {', '.join(details)}"
                if u.extra_rooms:
                    line += f" + {u.extra_rooms}"
                if u.max_guests:
                    line += f"\n  حتى {u.max_guests} ضيف"
                if u.daily_price and float(u.daily_price) > 0:
                    line += f"\n  {u.daily_price} ريال/يوم"
                if u.monthly_price and float(u.monthly_price) > 0:
                    line += f" | {u.monthly_price} ريال/شهر"
                if u.amenities:
                    line += f"\n  ملاحظات: {u.amenities}"
                if u.image_360_link:
                    line += f"\n  جولة 360: {u.image_360_link}"
                if u.images and len(u.images) > 0:
                    line += f"\n  عدد الصور المتاحة: {len(u.images)}"
                lines.append(line)
            lines.append("\nلو حاب نكمّل الحجز أو عندك سؤال عن وحدة معيّنة، قلّي هنا.")
            listed_ids = [u.id for u in display]
            with_photos = [u.id for u in display if u.images]
            meta_rm = {
                'fsm_opened_full_menu': True,
                'listed_unit_ids': listed_ids,
            }
            if with_photos:
                meta_rm['image_delivery_unit_ids'] = with_photos
            return IntentResult(reply="\n".join(lines), intent=intent, pipeline_meta=meta_rm)

        if intent in ('booking', 'availability'):
            # إنشاء حجز تلقائي إذا الزائر يبغى يحجز
            from app.models.booking import Booking
            ctx = self._booking_customer_context()
            unit_hint_id = None
            conv2 = getattr(self, '_active_conversation', None)
            if conv2 and isinstance(conv2.extra_data, dict):
                hc2 = conv2.extra_data.get('hotel_ctx') or {}
                if isinstance(hc2, dict):
                    uid = hc2.get('last_suggested_unit_id')
                    if uid and str(uid).isdigit():
                        unit_hint_id = int(uid)
            booking = Booking(
                tenant_id=self.tenant_id,
                booking_number=Booking.generate_booking_number(),
                booking_type='hotel_room',
                customer_name=ctx['customer_name'],
                customer_phone=ctx['customer_phone'],
                customer_email=ctx['customer_email'],
                conversation_id=ctx['conversation_id'],
                visitor_id=ctx['visitor_id'],
                source=ctx['source'],
                status='new',
                notes=f"طلب حجز من الشات: {original}",
                unit_id=unit_hint_id,
            )
            # نحفظه مبدئياً عشان يظهر في لوحة التاجر
            db.session.add(booking)
            db.session.commit()

            lines = [f"تم تسجيل طلب حجزك برقم {booking.booking_number}.\n"]
            if unit_hint_id:
                lines.append('ربطنا طلبك بآخر وحدة كانت ضمن عرضنا لك (يمكنك تصحيح الرقم لو لزم).')
            lines.append("يرجى تزويدنا بالتالي في سطر واحد أو أكثر:")
            lines.append("• تاريخ الدخول والخروج (مثال: الدخول 5/2 الخروج 7/2)")
            lines.append("• عدد الأشخاص (اختياري)")
            lines.append("• نوع الوحدة إن لم تكن محدداً بعد")
            lines.append(
                "\nبعد ما ترسل التواريخ نربطها بطلبك تلقائياً، "
                "ثم يمكنك إكمال الدفع والعقد الإلكتروني بعبارة تفعيل العقد التي يضبطها صاحب النشاط."
            )
            lines.append("التأكيد النهائي للإقامة يبقى من الفريق بعد المراجعة.")
            return IntentResult(
                reply="\n".join(lines),
                intent=intent,
                pipeline_meta={'hotel_booking_id': booking.id},
            )

        if intent in ('services', 'amenities'):
            services = HotelService.query.filter_by(tenant_id=self.tenant_id, is_active=True).all()
            if services:
                lines = [f"خدمات {self.business_name}:\n"]
                for s in services:
                    price_text = "مجاني" if s.is_free else f"{s.price} ريال"
                    icon_txt = (s.icon or '').strip()
                    if icon_txt and len(icon_txt) <= 2 and ord(icon_txt[0]) > 0x1F000:
                        icon_txt = ''
                    prefix = f"{icon_txt} " if icon_txt else ""
                    lines.append(f"• {prefix}{s.name} ({price_text})")
                    if s.description:
                        lines.append(f"  {s.description}")
                return IntentResult(reply="\n".join(lines), intent=intent)
            return IntentResult(
                reply="لحظات، أراجع الخدمات المتاحة مع الفريق وأرجع لك.",
                intent=intent,
            )

        if intent == 'location':
            if not branches:
                return IntentResult(
                    reply="حالياً ما عندي بيانات موقع كافية. إذا تحب أرسل استفسارك للفرع اكتب: نعم.",
                    intent=intent,
                )
            lines = [f"مواقع {self.business_name}:\n"]
            for b in branches:
                lines.append(f"— {b.name}")
                if b.address:
                    lines.append(f"   العنوان: {b.address}")
                if b.city:
                    lines.append(f"   المدينة: {b.city}")
                if b.map_link:
                    lines.append(f"   الخريطة: {b.map_link}")
            return IntentResult(reply="\n".join(lines), intent=intent)

        if intent == 'contact':
            lines = [f"أرقام التواصل — {self.business_name}:\n"]
            for b in branches:
                lines.append(f"— {b.name}")
                if b.phone:
                    lines.append(f"   هاتف: {b.phone}")
                if b.whatsapp:
                    lines.append(f"   واتساب: {b.whatsapp}")
                if b.email:
                    lines.append(f"   بريد: {b.email}")
            return IntentResult(reply="\n".join(lines), intent=intent)

        if intent == 'working_hours':
            if not branches:
                return IntentResult(
                    reply="حالياً ما عندي ساعات عمل مسجلة. إذا تحب أرسل استفسارك للفرع اكتب: نعم.",
                    intent=intent,
                )
            lines = ["ساعات العمل:\n"]
            tz = self._tenant_timezone()
            for b in branches:
                lines.append(f"— {b.name}:")
                lines.append(b.format_working_hours_visitor_ar(self.activity_code, tz))
            return IntentResult(reply="\n".join(lines), intent=intent)

        if intent == 'complaint':
            parts = [
                "نأسف لو وصلتك تجربة مو مريحة، هذا مو اللي نتمناه لضيوفنا.",
                "اكتب لنا تفاصيل أكثر إذا تقدر، وفريقنا يتابع معك بأسرع ما يمكن.",
            ]
            if len(branches) > 1:
                parts.append("وبالذكر: الشكوى عن أي فرع؟ (اكتب اسم الفرع أو المنطقة)")
            parts.append("نقدر نتابع معك من هنا، ولو حاب رقم مباشر للفرع قلّي.")
            return IntentResult(
                reply="\n".join(parts),
                needs_inquiry=True,
                inquiry_question=f"شكوى: {original}",
                intent=intent,
                inquiry_meta={'kind': 'complaint'},
            )

        return IntentResult(reply="وضّح لي أكثر طلبك، وإذا تحب أرسله للفرع اكتب: نعم.", intent=intent)

    # ========================================
    # ردود المطاعم
    # ========================================
    def _restaurant_respond(self, intent, msg, original):
        from app.models.branch import Branch
        from app.models.restaurant_models import MenuCategory, MenuItem, RestaurantService

        branches = Branch.query.filter_by(tenant_id=self.tenant_id, is_active=True).all()

        if intent == 'greeting':
            if ('السلام' in msg and 'عليكم' in msg) or (
                'سلام' in msg and 'عليكم' in msg
            ):
                return IntentResult(reply=(
                    "وعليكم السلام ورحمة الله وبركاته.\n"
                    f"أهلاً في {self.business_name}. {self._ready_phrase()}"
                ), intent=intent)
            who = (
                f"معك {self._bot_name} من {self.business_name}. "
                if self._bot_name
                else f"من {self.business_name}. "
            )
            return IntentResult(reply=(
                f"أهلاً وسهلاً، {who}"
                "تقدر تسأل عن القائمة والأسعار والتوصيل، أو حجز طاولة والموقع.\n"
                f"{self._ready_phrase()}"
            ), intent=intent)

        if intent == 'small_talk':
            return IntentResult(reply=self._small_talk_body(), intent=intent)

        if intent == 'thanks':
            return IntentResult(
                reply=self._thanks_body('بالهنا والعافية.'),
                intent=intent,
            )

        if intent == 'goodbye':
            return IntentResult(reply=self._goodbye_body(), intent=intent)

        if intent == 'inquiry':
            return IntentResult(
                reply=(
                    f"أكيد أساعدك. اذكر الاستفسار باختصار (موقع، توصيل، أسعار، حجز…) "
                    f"— أو اكتب «قائمة» أو «منيو» لو تبي تشوف أصناف {self.business_name} كاملة."
                ),
                intent='inquiry',
            )

        if intent == 'menu':
            from app.services.dialog_fsm_service import allow_full_menu

            conv = getattr(self, '_active_conversation', None)
            if not allow_full_menu(conv, msg):
                return IntentResult(
                    reply=(
                        f"أقدر أوجّهك بدل ما أطلع قائمة طويلة الآن: وش تبي بالضبط؟ "
                        f"(موقع، توصيل، أسعار، أو طلب) — أو اكتب «قائمة» أو «منيو» لو تبي تشوف كل الأصناف."
                    ),
                    intent='menu',
                )

            categories = MenuCategory.query.filter_by(tenant_id=self.tenant_id, is_active=True).order_by(MenuCategory.sort_order).all()
            if not categories:
                return IntentResult(
                    reply="لحظات، أتحقق من القائمة وأرجع لك هنا.",
                    intent=intent,
                )
            lines = [f"قائمة {self.business_name}:\n"]
            for cat in categories:
                items = cat.items.filter_by(is_available=True).all()
                if items:
                    lines.append(f"\n{cat.name}:")
                    for item in items[:10]:
                        line = f"  • {item.name}"
                        if item.discount_price:
                            line += f" — {item.discount_price} ريال (بدل {item.price})"
                        else:
                            line += f" — {item.price} ريال"
                        tags = []
                        if item.is_popular:
                            tags.append("مشهور")
                        if item.is_spicy:
                            tags.append("حار")
                        if tags:
                            line += f" ({'، '.join(tags)})"
                        lines.append(line)
            lines.append("\nإذا تبغى تكمّل الطلب أو عندك تفضيل، اكتب هنا.")
            return IntentResult(
                reply="\n".join(lines),
                intent=intent,
                pipeline_meta={'fsm_opened_full_menu': True},
            )

        if intent == 'pricing':
            items = MenuItem.query.filter_by(tenant_id=self.tenant_id, is_available=True).all()
            if items:
                lines = [f"أسعار {self.business_name}:\n"]
                for item in items[:20]:
                    price = item.discount_price or item.price
                    lines.append(f"• {item.name}: {price} ريال")
                return IntentResult(reply="\n".join(lines), intent=intent)
            return IntentResult(
                reply="لحظات، أتحقق من الأسعار مع الفريق وأرجع لك.",
                intent=intent,
            )

        if intent == 'delivery':
            svc = RestaurantService.query.filter_by(tenant_id=self.tenant_id, service_type='delivery', is_active=True).first()
            if svc:
                lines = ["خدمة التوصيل متاحة.\n"]
                if svc.delivery_fee and float(svc.delivery_fee) > 0:
                    lines.append(f"رسوم التوصيل: {svc.delivery_fee} ريال")
                if svc.min_order and float(svc.min_order) > 0:
                    lines.append(f"الحد الأدنى للطلب: {svc.min_order} ريال")
                if svc.delivery_areas:
                    lines.append(f"مناطق التغطية: {svc.delivery_areas}")
                return IntentResult(reply="\n".join(lines), intent=intent)
            return IntentResult(
                reply=f"للأسف خدمة التوصيل غير متاحة حالياً.\n"
                f"زورونا: {branches[0].address if branches else ''}\n"
                "لو حاب رقم للتواصل أو عنوان أوضح قلّي.",
                intent=intent,
            )

        if intent in ('ordering', 'reservation'):
            from app.models.booking import Booking
            lines = []
            if intent == 'reservation':
                ctx = self._booking_customer_context()
                booking = Booking(
                    tenant_id=self.tenant_id,
                    booking_number=Booking.generate_booking_number(),
                    booking_type='restaurant_table',
                    customer_name=ctx['customer_name'],
                    customer_phone=ctx['customer_phone'],
                    customer_email=ctx['customer_email'],
                    conversation_id=ctx['conversation_id'],
                    visitor_id=ctx['visitor_id'],
                    source=ctx['source'],
                    status='new',
                    notes=f"طلب حجز طاولة من الشات: {original}",
                )
                db.session.add(booking)
                db.session.commit()

                lines.append(f"تم تسجيل طلب حجزك برقم {booking.booking_number}.\n")
                lines.append("يرجى تزويدنا بالتالي:")
                lines.append("• التاريخ")
                lines.append("• الوقت")
                lines.append("• عدد الأشخاص")
                lines.append("• أي طلبات خاصة")
            else:
                lines.append(f"للطلب من {self.business_name}:\n")
            lines.append("اكتب تفاصيل طلبك هنا، والفريق يكمّل معك. إذا تحتاج رقم تواصل قلّي.")
            if intent == 'reservation':
                lines.append("التأكيد يتم من الفريق بعد مراجعة الطلب.")
            return IntentResult(reply="\n".join(lines), intent=intent)

        # مشتركة
        if intent == 'location':
            if not branches:
                return IntentResult(
                    reply="حالياً ما عندي بيانات موقع كافية. إذا تحب أرسل استفسارك للفرع اكتب: نعم.",
                    intent=intent,
                )
            lines = [f"مواقع {self.business_name}:\n"]
            for b in branches:
                lines.append(f"— {b.name}")
                if b.address:
                    lines.append(f"   {b.address}")
                if b.map_link:
                    lines.append(f"   رابط الخريطة: {b.map_link}")
            return IntentResult(reply="\n".join(lines), intent=intent)

        if intent == 'contact':
            lines = [f"أرقام التواصل — {self.business_name}:\n"]
            for b in branches:
                lines.append(f"— {b.name}: {b.phone}")
                if b.whatsapp:
                    lines.append(f"   واتساب: {b.whatsapp}")
            return IntentResult(reply="\n".join(lines), intent=intent)

        if intent == 'working_hours':
            if not branches:
                return IntentResult(
                    reply="حالياً ما عندي ساعات عمل مسجلة. إذا تحب أرسل استفسارك للفرع اكتب: نعم.",
                    intent=intent,
                )
            lines = ["ساعات العمل:\n"]
            tz = self._tenant_timezone()
            for b in branches:
                lines.append(f"— {b.name}:")
                lines.append(b.format_working_hours_visitor_ar(self.activity_code, tz))
            return IntentResult(reply="\n".join(lines), intent=intent)

        if intent == 'complaint':
            return IntentResult(
                reply=(
                    "نعتذر لو كانت التجربة دون المستوى اللي نتمناه.\n"
                    "شاركنا التفاصيل هنا، وفريقنا يتابع معك بأسرع وقت.\n"
                    "إذا تحتاج رقم مباشر للفرع قلّي."
                ),
                needs_inquiry=True,
                inquiry_question=f"شكوى: {original}",
                intent=intent,
                inquiry_meta={'kind': 'complaint'},
            )

        return IntentResult(reply="وضّح لي أكثر طلبك، وإذا تحب أرسله للفرع اكتب: نعم.", intent=intent)


# ========================================
# قواميس الكلمات المفتاحية
# ========================================
COMMON_INTENTS = {
    'small_talk': [
        'كيفك', 'كيف الحال', 'شلونك', 'شخبارك', 'كيف امورك', 'زينك',
    ],
    'greeting': [
        'سلام', 'مرحبا', 'اهلا', 'هلا', 'هاي', 'صباح', 'مساء',
        'السلام', 'عليكم', 'الو', 'حياك', 'اهلين',
        'يا هلا', 'مرحب', 'حيا', 'هلو', 'hello', 'hi',
    ],
    'thanks': [
        'شكرا', 'مشكور', 'يعطيك', 'العافيه', 'تسلم', 'ممتن',
        'جزاك', 'يسلمو', 'ثانكس', 'thanks', 'thank',
    ],
    'goodbye': [
        'سلامه', 'باي', 'اللقاء', 'وداع', 'امان الله', 'سلامتك',
        'bye', 'مع السلامه',
    ],
    'contact': [
        'رقم', 'هاتف', 'جوال', 'تلفون', 'اتصل', 'تواصل',
        'ايميل', 'بريد', 'واتساب', 'واتس', 'كيف اتواصل',
        'رقمكم', 'تلفونكم', 'جوالكم',
    ],
    'location': [
        'وين', 'فين', 'موقع', 'عنوان', 'مكان', 'خريطه',
        'كيف اوصل', 'الموقع', 'العنوان', 'موقعكم',
        'عنوانكم', 'مكانكم', 'فينكم', 'وينكم', 'لوكيشن',
    ],
    'complaint': [
        'شكوى', 'مشكله', 'سيء', 'زعلان', 'ماعجبني', 'خرب',
        'مكسور', 'قذر', 'وسخ', 'بارد', 'متاخر', 'اشتكي',
        'شكوه', 'ملاحظه', 'ابلاغ', 'مشاكل',
    ],
    'working_hours': [
        'ساعات', 'اوقات', 'تفتحون', 'تقفلون', 'مفتوح', 'مقفل',
        'دوام', 'الدوام', 'ساعات العمل', 'وقت الدوام', 'متى',
        'الافتتاح', 'الاغلاق', 'فتره', 'فترات',
    ],
}

HOTEL_INTENTS = {
    'pricing': [
        'سعر', 'اسعار', 'تكلفه', 'قيمه', 'بكم', 'كم سعر', 'كم السعر',
        'يومي', 'شهري', 'سنوي', 'ليله', 'الليله', 'ارخص',
        'اغلى', 'عرض', 'خصم', 'تخفيض', 'السعر', 'الاسعار',
    ],
    'rooms': [
        'غرفه', 'غرف', 'جناح', 'اجنحه', 'شقه', 'شقق',
        'سرير', 'مزدوج', 'مفرد', 'فاميلي', 'عائلي', 'سويت',
        'ديلوكس', 'فيلا', 'وحده', 'وحدات', 'عندكم',
        'عندك', 'ابغى', 'ابي', 'يوجد',
    ],
    'booking': [
        'حجز', 'احجز', 'ابي احجز', 'ابغى احجز', 'كيف احجز',
        'طريقه الحجز', 'حجوزات', 'بوكنج', 'booking',
    ],
    'availability': [
        'متاح', 'متوفر', 'فاضي', 'فاضيه', 'توفر',
        'في غرف', 'فيه اماكن', 'موجود', 'متاحه',
    ],
    'services': [
        'خدمات', 'خدمه', 'مرافق', 'مسبح', 'جيم', 'صاله',
        'واي فاي', 'انترنت', 'غسيل', 'نظافه', 'روم سيرفس',
        'مواقف', 'باركنج', 'سبا', 'ساونا', 'مساج', 'ملعب',
    ],
}

# عند تعادل نقاط النية: الأسبق هنا يُفضّل (دوام/موقع قبل التحية العامة).
# delivery قبل menu حتى لا تربح «عندكم» (قائمة) على «توصيل» في جمل مثل «عندكم توصيل؟».
INTENT_TIE_PRIORITY = (
    'working_hours', 'location', 'contact', 'complaint',
    'delivery', 'menu', 'pricing', 'ordering', 'reservation',
    'rooms', 'booking', 'availability', 'services',
    'small_talk', 'thanks', 'goodbye', 'greeting',
)

RESTAURANT_INTENTS = {
    'menu': [
        'منيو', 'قائمه', 'اصناف', 'وش عندكم', 'ايش عندكم',
        'الاكل', 'الوجبات', 'المشروبات', 'حلويات', 'مقبلات',
        'عصير', 'قهوه', 'شاي', 'كابتشينو', 'كباتشينو', 'لاتيه', 'برجر',
        'بيتزا', 'شاورما', 'سلطه', 'رز', 'القائمه', 'عندكم',
        'cappuccino', 'latte',
    ],
    'pricing': [
        'سعر', 'اسعار', 'بكم', 'كم سعر', 'كم السعر', 'تكلفه', 'ارخص',
        'اغلى', 'عرض', 'خصم', 'اوفر', 'السعر',
    ],
    'delivery': [
        'توصيل', 'دليفري', 'يوصلون', 'توصلون', 'طلب خارجي',
        'رسوم التوصيل', 'مناطق التوصيل', 'كم التوصيل',
    ],
    'ordering': [
        'طلب', 'اطلب', 'ابي اطلب', 'ابغى اطلب',
        'كيف اطلب', 'طريقه الطلب', 'اوردر',
    ],
    'reservation': [
        'حجز', 'احجز', 'طاوله', 'حجز طاوله', 'بوكنج',
        'حفله', 'مناسبه', 'عشاء', 'غداء', 'فطور',
    ],
}

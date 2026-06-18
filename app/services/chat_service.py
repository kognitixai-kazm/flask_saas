"""
app/services/chat_service.py — خدمة الشات الكاملة.

الترتيب (المرحلة 2B):
1️⃣ IntentEngine → ردود محلية (مجانية أو سعر رسالة عادية)
2️⃣ الذكاء الخارجي إن لم يُطابق المحرك المحلي نيةً واضحة أو احتاج استفساراً
3️⃣ يخصم من رصيد التاجر حسب نوع الرد (نص / ذكاء)
4️⃣ استفسار إذا فشل كل شيء
"""
from datetime import datetime

from flask import current_app

from app.extensions import db
from app.models.tenant import Tenant
from app.models.branch import Branch
from app.models.inquiry import Inquiry
from app.models.conversation import Conversation, Message
from app.services.intent_engine import IntentEngine
from app.services.email_service import EmailService


# فاصل خاص لتقسيم الرد إلى عدة فقاعات (يُستخدم بين الواجهة والباك إند فقط)
REPLY_SPLIT = '\x1eKOG\x1e'


class ChatService:

    @staticmethod
    def generate_reply(tenant: Tenant, conversation: Conversation, user_message: str) -> str:
        """معالجة رسالة وتوليد رد + خصم تكلفة من رصيد التاجر."""
        current_app.logger.info(
            '[Chat] generate_reply enter tenant=%s conv=%s',
            getattr(tenant, 'slug', tenant.id),
            getattr(conversation, 'id', None),
        )
        db.session.flush()

        confirmed = ChatService._consume_inquiry_confirmation(conversation, user_message)
        if confirmed:
            ChatService._create_inquiry(
                tenant=tenant,
                conversation=conversation,
                question=confirmed.get('question') or user_message,
                visitor_id=conversation.visitor_id,
                inquiry_meta=confirmed.get('meta') or {},
            )
            return (
                f"تم تمرير سؤالك لفريق {tenant.business_name}، ويرجّعون لك هنا بأقرب وقت.\n"
                "إذا تحب تضيف تفاصيل أكثر، اكتبها في نفس المحادثة."
            )

        # طلب صور لوحدة لم تُرفَع لها صور بعد → تصعيد ذكي للفرع
        if ChatService._is_image_request_followup(user_message):
            ChatService._create_inquiry(
                tenant=tenant,
                conversation=conversation,
                question='طلب صور لوحدة لم تُرفع صورها — يرجى إرسال صور مباشرة من الفرع.',
                visitor_id=conversation.visitor_id,
                inquiry_meta={'kind': 'general', 'topic': 'unit_images_request'},
            )
            ChatService._charge_message(tenant.id, 'text_message', conversation.id)
            return (
                'تمام، رتّبنا الطلب وحوّلناه للفرع. '
                'بيرجعون لك بأقرب وقت بصور مباشرة في نفس المحادثة.'
            )

        # ==========================================
        # طلب بيانات الحساب البنكي (سؤال مستقل)
        # ==========================================
        if ChatService.is_bank_info_request(user_message):
            info = ChatService._tenant_bank_info(tenant)
            ChatService._charge_message(tenant.id, 'text_message', conversation.id)
            return f'بيانات التحويل البنكي:\n\n{info}\n\nبعد التحويل أرسل صورة الإيصال.'

        # ==========================================
        # فندق: متابعة تواريخ الحجز قبل العقد وقبل النوايا
        # ==========================================
        try:
            from app.services.hotel_booking_chat import handle_before_contract_flow

            hotel_early = handle_before_contract_flow(tenant, conversation, user_message)
            if hotel_early is not None:
                ChatService._charge_message(tenant.id, 'text_message', conversation.id)
                return hotel_early
        except Exception as e:
            current_app.logger.warning(f'[Chat] hotel booking followup error: {e}')

        # ==========================================
        # 0️⃣ تدفق العقد النشط (إذا كان لدينا عقد جارٍ في هذه المحادثة)
        # ==========================================
        try:
            reply = ChatService._handle_active_contract(tenant, conversation, user_message)
            if reply is not None:
                ChatService._charge_message(tenant.id, 'text_message', conversation.id)
                return reply
        except Exception as e:
            current_app.logger.warning(f'[Chat] active contract flow error: {e}')

        # 0️⃣.1 — لو الرسالة تطابق قالب عقد، نبدأ تدفقاً جديداً
        # ملاحظة: العقود الإلكترونية متاحة فقط لنمط الإيجار الشهري
        try:
            from app.services.contract_service import ContractService
            contracts_allowed = True
            if (tenant.activity and tenant.activity.code == 'hotel'
                    and not tenant.hotel_supports_contracts):
                contracts_allowed = False

            matching_template = (
                ContractService.find_matching_template(tenant.id, user_message)
                if contracts_allowed else None
            )
            if matching_template:
                contract = ContractService.start_contract(
                    tenant_id=tenant.id,
                    template_id=matching_template.id,
                    conversation_id=conversation.id,
                )
                contract.payment_amount = float(matching_template.base_price or 0)
                db.session.flush()

                ex = dict(conversation.extra_data or {})
                ex['contract_state'] = {
                    'active_contract_id': contract.id,
                    'contract_stage': 'collect_fields',
                }
                conversation.extra_data = ex

                welcome = (
                    f"تمام، نبدأ في {matching_template.name}.\n"
                    f"بحتاج منك بعض المعلومات خطوة بخطوة."
                )
                next_field = ContractService.get_next_required_field(contract)
                if next_field:
                    welcome += f"\n\n{ContractService.field_prompt(next_field)}"
                db.session.commit()

                ChatService._charge_message(tenant.id, 'text_message', conversation.id)
                return welcome
        except Exception as e:
            current_app.logger.warning(f'[Chat] contract match error: {e}')

        # ==========================================
        # 1️⃣ المحاولة المحلية (IntentEngine)
        # ==========================================
        try:
            current_app.logger.info('[Chat] before IntentEngine.process')
            engine = IntentEngine(tenant)
            result = engine.process(user_message, conversation=conversation)
            current_app.logger.info(
                '[Chat] after IntentEngine.process intent=%s has_reply=%s',
                getattr(result, 'intent', None),
                bool(getattr(result, 'reply', None)),
            )

            # رد جاهز من القواعد المحلية → نسلّمه مباشرة (Hybrid Logic Gate: AI لا يُستدعى)
            if result.reply and not result.needs_inquiry:
                current_app.logger.info(f'[Chat] local reply for tenant={tenant.slug} intent={result.intent}')

                if getattr(result, 'pipeline_meta', None):
                    try:
                        from app.services.hotel_booking_chat import persist_intent_pipeline_meta

                        persist_intent_pipeline_meta(conversation, result.pipeline_meta or {})
                        db.session.commit()
                    except Exception as e:
                        current_app.logger.warning(f'[Chat] persist pipeline_meta error: {e}')
                        db.session.rollback()

                ChatService._charge_message(
                    tenant_id=tenant.id,
                    service_key='text_message',
                    conversation_id=conversation.id,
                )
                # إذا كانت النية تطلب إرسال أكثر من فقاعة (مثل الترحيب)،
                # ندمجها بفاصل خاص يقسّمها الواجهة الأمامية إلى رسائل منفصلة.
                extras = []
                if isinstance(result.pipeline_meta, dict):
                    extras = result.pipeline_meta.get('extra_replies') or []
                if extras:
                    parts = [result.reply] + [str(x) for x in extras if x]
                    return REPLY_SPLIT.join(parts)
                return result.reply

            # رد + يحتاج استفسار
            if result.needs_inquiry:
                meta = result.inquiry_meta or {}

                # شكوى → ترفع مباشرة
                if (meta.get('kind') or '').strip() == 'complaint':
                    ChatService._create_inquiry(
                        tenant=tenant,
                        conversation=conversation,
                        question=result.inquiry_question or user_message,
                        visitor_id=conversation.visitor_id,
                        inquiry_meta=meta,
                    )
                    if result.reply:
                        ChatService._charge_message(tenant.id, 'text_message', conversation.id)
                        return result.reply
                    return ChatService._not_found_reply(tenant, user_message)

                # جرّب الذكاء الخارجي قبل تمرير الاستفسار للفرع
                ai_text = ChatService._try_ai_reply(tenant, conversation, user_message)
                if ai_text:
                    return ai_text

                # غير ذلك → طلب موافقة لتمرير استفسار
                ChatService._set_pending_inquiry(
                    conversation=conversation,
                    question=result.inquiry_question or user_message,
                    meta=meta,
                )
                if result.reply:
                    ChatService._charge_message(tenant.id, 'text_message', conversation.id)
                    return result.reply

                ChatService._charge_message(tenant.id, 'text_message', conversation.id)
                return (
                    'فهمت عليك، وراح أحوّل سؤالك لفريق المتابعة عندنا الحين، '
                    'ويرجّعون لك في نفس المحادثة بأقرب وقت. '
                    'لو فيه تفاصيل تحب تضيفها، اكتبها هنا وراح توصلهم معك.'
                )

        except Exception as e:
            current_app.logger.warning(f'[Chat] IntentEngine error: {e}')

        # ==========================================
        # 3️⃣ احتياطي: الذكاء الخارجي (مثلاً بعد خطأ المحرك المحلي)
        # ==========================================
        ai_text = ChatService._try_ai_reply(tenant, conversation, user_message)
        if ai_text:
            return ai_text

        # ==========================================
        # 4️⃣ خط أخير: طلب استفسار
        # ==========================================
        # تصعيد ذكي مباشر: نسجّل استفساراً وننوّه الفريق دون مطالبة الزائر بكتابة "نعم"
        ChatService._create_inquiry(
            tenant=tenant,
            conversation=conversation,
            question=user_message,
            visitor_id=conversation.visitor_id,
            inquiry_meta={'kind': 'general', 'auto_escalated': True},
        )
        ChatService._charge_message(tenant.id, 'text_message', conversation.id)
        return (
            f'أبشر، خلّيني أتأكد لك من فريق {tenant.business_name} وأرجّع لك بأقرب وقت في نفس المحادثة. '
            'لو فيه تفاصيل تحب تضيفها، اكتبها هنا وراح توصلهم معك.'
        )

    # ========================================
    # خصم تكلفة الرسالة
    # ========================================
    @staticmethod
    def _charge_message(tenant_id: int, service_key: str, conversation_id: int = None,
                       ai_model_id: int = None, tokens_in: int = 0, tokens_out: int = 0):
        """خصم تكلفة الخدمة من رصيد التاجر."""
        try:
            from app.services.pricing_service import PricingService
            ok, msg, charged = PricingService.charge(
                tenant_id=tenant_id,
                service_key=service_key,
                ai_model_id=ai_model_id,
                conversation_id=conversation_id,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
            if not ok:
                current_app.logger.warning(f'[Chat] charge failed tenant={tenant_id} svc={service_key}: {msg}')
        except Exception as e:
            current_app.logger.warning(f'[Chat] charge error: {e}')

    # ========================================
    # محاولة AI
    # ========================================
    @staticmethod
    def _try_ai_reply(tenant: Tenant, conversation: Conversation, user_message: str) -> str:
        """محاولة استدعاء AI — يخصم تلقائياً عند النجاح. لا يُستدعى إلا بعد فشل القواعد المحلية."""
        try:
            from app.services.ai_service import AIService
            from app.services.pricing_service import PricingService

            # جلب النموذج المختار
            model = AIService.get_tenant_model(tenant.id)
            if not model:
                current_app.logger.warning(f'[Chat] no AI model available for tenant={tenant.slug}')
                return None

            # التحقق من رصيد التاجر قبل الاستدعاء
            ok, msg, price = PricingService.can_afford(
                tenant_id=tenant.id,
                service_key='ai_message',
                ai_model_id=model.id,
            )
            if not ok:
                current_app.logger.warning(f'[Chat] insufficient balance for AI tenant={tenant.slug}: {msg}')
                return None

            # فحص خفيف وسريع لصلاحية المفتاح (مع كاش TTL)
            api_key = AIService._get_api_key(model.provider, tenant.id)
            if not api_key:
                current_app.logger.warning(
                    f'[Chat] no API key for provider={model.provider} tenant={tenant.slug}'
                )
                return None
            key_ok, key_reason = AIService.validate_api_key(model.provider, api_key)
            if not key_ok:
                current_app.logger.warning(
                    f'[Chat] AI key invalid provider={model.provider} tenant={tenant.slug} reason={key_reason}'
                )
                return None

            system_prompt = ChatService._build_prompt(tenant, conversation)
            history = ChatService._build_history(conversation)

            current_app.logger.info(
                '[Chat] before AIService.generate tenant=%s provider=%s timeout=%s',
                tenant.slug,
                model.provider,
                AIService.http_timeout(),
            )
            result = AIService.generate(
                tenant_id=tenant.id,
                user_message=user_message,
                system_prompt=system_prompt,
                history=history,
                model_override=model,
            )
            current_app.logger.info(
                '[Chat] after AIService.generate tenant=%s success=%s',
                tenant.slug,
                bool(result.success and result.text),
            )

            if not result.success or not result.text:
                current_app.logger.warning(f'[Chat] AI failed: {result.error}')
                return None

            ChatService._charge_message(
                tenant_id=tenant.id,
                service_key='ai_message',
                conversation_id=conversation.id,
                ai_model_id=model.id,
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
            )

            return ChatService._sanitize_ai_text(result.text)

        except Exception as e:
            current_app.logger.exception(f'[Chat] AI error: {e}')
            return None

    @staticmethod
    def _sanitize_ai_text(text: str) -> str:
        """إزالة أي تسرّب تقني في رد الـ AI قبل عرضه للزائر."""
        if not text:
            return text
        cleaned = text.strip()
        bad_starts = ('error', 'http', 'traceback', '[', '{')
        if any(cleaned.lower().startswith(b) for b in bad_starts):
            return ''
        return cleaned

    # ========================================
    # رد عدم وجود المعلومة
    # ========================================
    @staticmethod
    def _not_found_reply(tenant: Tenant, message: str) -> str:
        return (
            f"تمام، وصلت ملاحظتك لفريق {tenant.business_name} وراح يرجّعون لك هنا بأقرب وقت.\n"
            "لو عندك تفاصيل إضافية تساعدنا، اكتبها في نفس المحادثة."
        )

    @staticmethod
    def _normalize_yes_no(text: str) -> str:
        t = (text or '').strip().lower()
        for a, b in (
            ('أ', 'ا'),
            ('إ', 'ا'),
            ('آ', 'ا'),
            ('ة', 'ه'),
            ('ى', 'ي'),
        ):
            t = t.replace(a, b)
        return t

    @staticmethod
    def _is_affirmative(text: str) -> bool:
        t = ChatService._normalize_yes_no(text)
        yes_words = {
            'نعم', 'اي', 'ايوه', 'ايوا', 'اوافق', 'موافق', 'تمام',
            'تم', 'اوكي', 'okay', 'ok', 'ارسل', 'ارسله', 'حول', 'حولها',
        }
        return t in yes_words

    @staticmethod
    def _is_negative(text: str) -> bool:
        t = ChatService._normalize_yes_no(text)
        no_words = {'لا', 'مو', 'مش', 'لا شكرا', 'خلاص', 'لا ترسل', 'الغ'}
        return t in no_words

    @staticmethod
    def _set_pending_inquiry(conversation: Conversation, question: str, meta: dict | None = None) -> None:
        ex = conversation.extra_data or {}
        if not isinstance(ex, dict):
            ex = {}
        ex['pending_inquiry'] = {
            'question': (question or '').strip(),
            'meta': meta or {'kind': 'general'},
            'at': datetime.utcnow().isoformat(),
        }
        conversation.extra_data = ex
        db.session.commit()

    @staticmethod
    def _consume_inquiry_confirmation(conversation: Conversation, user_message: str):
        ex = conversation.extra_data or {}
        if not isinstance(ex, dict):
            return None
        pending = ex.get('pending_inquiry')
        if not isinstance(pending, dict):
            return None
        if ChatService._is_affirmative(user_message):
            ex.pop('pending_inquiry', None)
            conversation.extra_data = ex
            db.session.commit()
            return pending
        if ChatService._is_negative(user_message):
            ex.pop('pending_inquiry', None)
            conversation.extra_data = ex
            db.session.commit()
        return None

    # ========================================
    # إنشاء استفسار + إرسال إيميل
    # ========================================
    @staticmethod
    def _create_inquiry(tenant: Tenant, conversation: Conversation,
                        question: str, visitor_id: str, inquiry_meta=None):
        """إنشاء استفسار جديد + إرسال إيميل لصاحب النشاط."""
        meta = inquiry_meta or {}
        kind = (meta.get('kind') or 'general').strip() or 'general'
        if kind not in ('general', 'complaint'):
            kind = 'general'
        cat_slug = (meta.get('category') or '').strip() if kind == 'complaint' else ''
        if kind == 'complaint' and not cat_slug:
            cat_slug = 'other'

        # اختيار الفرع المناسب (الرئيسي أو الأول)
        branch = Branch.query.filter_by(
            tenant_id=tenant.id, is_active=True, is_main=True
        ).first()
        if not branch:
            branch = Branch.query.filter_by(
                tenant_id=tenant.id, is_active=True
            ).first()

        # إنشاء الاستفسار
        inquiry = Inquiry(
            tenant_id=tenant.id,
            branch_id=branch.id if branch else None,
            conversation_id=conversation.id,
            visitor_id=visitor_id,
            visitor_name=conversation.visitor_name or '',
            visitor_phone=(conversation.visitor_phone or '').strip(),
            visitor_email=(conversation.visitor_email or '').strip(),
            question=question,
            inquiry_kind=kind,
            complaint_category=cat_slug if kind == 'complaint' else '',
            status='new',
        )
        db.session.add(inquiry)
        db.session.commit()

        # إرسال إيميل
        target_email = ''
        branch_name = ''
        if branch:
            target_email = branch.complaints_email or branch.email
            branch_name = branch.name
        if not target_email:
            target_email = tenant.owner_email

        ch = (getattr(conversation, 'channel', None) or 'web').strip() or 'web'
        ch_ar = 'واتساب' if ch == 'whatsapp' else 'الويب'
        v_lines = []
        if (conversation.visitor_name or '').strip():
            v_lines.append(f"الاسم: {(conversation.visitor_name or '').strip()}")
        if (conversation.visitor_phone or '').strip():
            v_lines.append(f"الجوال: {(conversation.visitor_phone or '').strip()}")
        if (conversation.visitor_email or '').strip():
            v_lines.append(f"البريد: {(conversation.visitor_email or '').strip()}")
        v_lines.append(f"القناة: {ch_ar}")
        vid = (visitor_id or '').strip()
        if vid:
            short = vid if len(vid) <= 24 else vid[:24] + '…'
            v_lines.append(f"معرّف الزائر: {short}")
        visitor_info = '<br>'.join(v_lines) if v_lines else ''

        cat_label_ar = ''
        if kind == 'complaint':
            cat_label_ar = Inquiry.COMPLAINT_CATEGORY_LABELS_AR.get(cat_slug, cat_slug or 'أخرى')

        if target_email:
            sent = EmailService.send_inquiry_notification(
                to_email=target_email,
                business_name=tenant.business_name,
                branch_name=branch_name,
                question=question,
                visitor_info=visitor_info,
                inquiry_id=inquiry.id,
                inquiry_kind=kind,
                complaint_category_ar=cat_label_ar,
            )
            inquiry.email_sent = sent
            inquiry.email_sent_to = target_email
            inquiry.status = 'pending'
            db.session.commit()

        current_app.logger.info(
            f'[Chat] Inquiry #{inquiry.id} created for tenant={tenant.slug}, '
            f'email_sent={inquiry.email_sent} to={target_email}'
        )

    @staticmethod
    def deliver_inquiry_agent_response(tenant: Tenant, inquiry: Inquiry, answer: str) -> None:
        """يوصّل رد صاحب النشاط للزائر: رسالة في المحادثة + إيميل + واتساب حسب التوفر."""
        notified = False
        conv = None
        if inquiry.conversation_id:
            conv = Conversation.query.filter_by(
                id=inquiry.conversation_id,
                tenant_id=tenant.id,
            ).first()
        if conv:
            db.session.add(
                Message(
                    conversation_id=conv.id,
                    tenant_id=tenant.id,
                    sender_type='agent',
                    content=answer,
                    extra_data={'inquiry_id': inquiry.id},
                )
            )
            conv.updated_at = datetime.utcnow()
            notified = True

        email_to = (inquiry.visitor_email or '').strip()
        if not email_to and conv and (conv.visitor_email or '').strip():
            email_to = conv.visitor_email.strip()
        if email_to:
            try:
                if EmailService.send_visitor_inquiry_answer(
                    to_email=email_to,
                    business_name=tenant.business_name,
                    question=inquiry.question or '',
                    answer=answer,
                ):
                    notified = True
            except Exception as e:
                current_app.logger.warning(f'Visitor inquiry email failed: {e}')

        phone_to = (inquiry.visitor_phone or '').strip()
        if not phone_to and conv:
            vid = (conv.visitor_id or '').strip()
            if vid.startswith('wa_'):
                phone_to = vid[3:]
            elif (conv.visitor_phone or '').strip():
                phone_to = conv.visitor_phone.strip()
        if phone_to:
            try:
                from app.services.whatsapp_service import WhatsAppService

                intro = f"رد من {tenant.business_name}:\n\n"
                r = WhatsAppService.send_text(tenant.id, phone_to, intro + answer)
                if not r.get('error'):
                    notified = True
            except Exception as e:
                current_app.logger.warning(f'Visitor inquiry WA failed: {e}')

        inquiry.visitor_notified = notified

    # ========================================
    # AI احتياطي
    # ========================================
    @staticmethod
    def _load_bot_config(tenant_id: int):
        from app.models.bot_config import BotConfig

        return BotConfig.query.filter_by(tenant_id=tenant_id).first()

    _ACTIVITY_PERSONA = {
        'hotel': {
            'role': 'موظّف استقبال في فندق/شقق فندقية',
            'scope': (
                'الإجابة عن الغرف والوحدات والأسعار العامة والموقع والخدمات وساعات الاستقبال، '
                'وتوجيه العميل لإكمال الحجز عبر النموذج الموجود في المحادثة.'
            ),
            'avoid': 'لا تتحدث عن قوائم طعام أو حجوزات طاولات؛ هذه ليست مهمتنا هنا.',
        },
        'restaurant': {
            'role': 'مضيف/موظف خدمة عملاء في مطعم',
            'scope': (
                'الإجابة عن الأصناف والأسعار العامة وتوصيل الطلب أو حجز طاولة والموقع وأرقام التواصل.'
            ),
            'avoid': 'لا تتحدث عن غرف فندق أو إيجار وحدات سكنية؛ هذا خارج نشاطنا.',
        },
    }

    @staticmethod
    def _activity_persona(activity_code: str):
        return ChatService._ACTIVITY_PERSONA.get(
            (activity_code or '').strip().lower(),
            {
                'role': 'موظّف خدمة عملاء',
                'scope': 'الإجابة عن خدمات المنشأة العامة والموقع وأرقام التواصل وساعات العمل.',
                'avoid': 'التزم بنشاط هذه المنشأة فقط ولا تخلطه بأي نشاط آخر.',
            },
        )

    @staticmethod
    def _build_prompt(tenant, conversation=None):
        activity_code = (tenant.activity.code if getattr(tenant, 'activity', None) else '') or ''
        persona = ChatService._activity_persona(activity_code)
        business = (tenant.business_name or '').strip()

        visitor_line = ''
        if conversation and (conversation.visitor_name or '').strip():
            vn = (conversation.visitor_name or '').strip()
            visitor_line = (
                f"\nاسم الزائر: {vn}. ناده باسمه مرة واحدة عند البدء فقط، بدون مبالغة."
            )

        scope_block = (
            f"النطاق المسموح: {persona['scope']}\n"
            f"خارج النطاق: {persona['avoid']} عند خروج السؤال عن نطاق المنشأة، اعتذر بلطف "
            "واطلب توضيحاً، ولا تقدّم معلومات لا تخصّ هذه المنشأة."
        )

        style_block = (
            "أسلوب الرد: عربي طبيعي، ودود، مختصر (2-4 أسطر غالبًا)، يبدأ بجملة ربط "
            "بشرية مثل «أبشر،» أو «فهمت عليك،» أو «تمام، خلّيني أوضح لك،» حسب السياق. "
            "لا تذكر أنك نموذج لغة أو ذكاء اصطناعي. لا تستخدم إيموجي ولا أكواد أو أرقام أخطاء. "
            "إذا لم تعرف المعلومة بالضبط، اعتذر بلباقة وقل إنك ستحوّلها للفريق المختص."
        )

        identity = (
            f"أنت {persona['role']} لدى «{business}» (نشاط: {activity_code or 'عام'}). "
            f"معرّف المنشأة الداخلي: T{tenant.id}. تكلّم بصيغة فريق المنشأة "
            f"(«نحن» / «عندنا») ولا تذكر أي منشأة أخرى."
        )

        # سياق نمط الفندق (شهري بحت / يومي يشمل الشهري)
        hotel_mode_block = ''
        if activity_code == 'hotel':
            mode = getattr(tenant, 'hotel_mode', 'daily')
            if mode == 'monthly':
                hotel_mode_block = (
                    "\n\nنوع الإيجار المتاح: شهري فقط (مع عقود رسمية). لا تعرض حجوزات الليلة الواحدة "
                    "ولا تذكر أسعاراً يومية. "
                    "إذا سأل العميل عن إيجار يومي، وضّح بلطف أن النشاط متخصّص في الإيجار الشهري."
                )
            else:
                # daily = الفندق العادي: يدعم اليومي ويعرض الشهري كذلك للإقامات الطويلة
                hotel_mode_block = (
                    "\n\nنوع الإيجار المتاح: يومي وشهري. ابدأ بالخيار المناسب لمدة إقامة العميل، "
                    "وإذا ذكر إقامة طويلة (شهر+) اعرض السعر الشهري والعقد الرسمي."
                )

        base = identity + hotel_mode_block + "\n\n" + scope_block + "\n\n" + style_block + visitor_line

        bot = ChatService._load_bot_config(tenant.id)
        if bot:
            ci = (bot.custom_instructions or '').strip()
            if ci:
                base += "\n\n— تعليمات صاحب النشاط (التزم بها أولًا) —\n" + ci
            bt = (bot.blocked_topics or '').strip()
            if bt:
                base += "\n\nتجنّب مناقشة هذه المواضيع نهائياً: " + bt

        return base

    # ========================================
    # تدفق العقد النشط: جمع الحقول → اختيار الدفع → تحويل بنكي / دفع إلكتروني
    # ========================================
    @staticmethod
    def _handle_active_contract(tenant: Tenant, conversation: Conversation, user_message: str):
        """يدير حالة عقد جارٍ. يرجع نص الرد أو None لو لا يوجد تدفق نشط."""
        ex = conversation.extra_data or {}
        if not isinstance(ex, dict):
            return None
        sd = ex.get('contract_state') or {}
        contract_id = sd.get('active_contract_id') if isinstance(sd, dict) else None
        if not contract_id:
            return None

        from app.services.contract_service import ContractService
        from app.models.contract import Contract

        def _save_state(new_sd):
            ex2 = dict(conversation.extra_data or {})
            if new_sd:
                ex2['contract_state'] = new_sd
            else:
                ex2.pop('contract_state', None)
            conversation.extra_data = ex2

        contract = Contract.query.filter_by(id=contract_id, tenant_id=tenant.id).first()
        if not contract or contract.status not in ('draft', 'pending_payment'):
            _save_state(None)
            db.session.commit()
            return None

        msg = (user_message or '').strip()
        stage = sd.get('contract_stage', 'collect_fields')

        # كلمة إلغاء عامة (مرنة: عربي/إنجليزي/دارج)
        low_msg = msg.lower()
        cancel_tokens = (
            'الغاء', 'إلغاء', 'الغ', 'وقف', 'cancel',
            'كنسل', 'خلاص', 'انهاء', 'إنهاء', 'رجوع', 'back', 'stop',
        )
        if any(tok in low_msg for tok in cancel_tokens):
            contract.status = 'cancelled'
            _save_state(None)
            db.session.commit()
            return 'تم إلغاء العقد. لو احتجت أي شيء ثاني أنا موجود.'

        # ====== مرحلة جمع الحقول ======
        if stage == 'collect_fields':
            from app.services.ai_service import AIService
            import json
            import re
            
            missing_fields = []
            if contract.template and contract.template.required_fields:
                for f in contract.template.required_fields:
                    if f.get('key') not in contract.field_values or not contract.field_values[f.get('key')]:
                        missing_fields.append(f)

            if missing_fields and msg:
                # محاولة استخراج الحقول بالذكاء الاصطناعي
                fields_json_str = json.dumps([{ 'key': f['key'], 'label': f['label'], 'type': f['type'] } for f in missing_fields], ensure_ascii=False)
                prompt = (
                    "أنت مساعد استخراج بيانات ذكي. العميل يقوم بتعبئة عقد إيجار/خدمة. "
                    f"نحن بحاجة للحقول التالية:\n{fields_json_str}\n\n"
                    "مهمتك: اقرأ رسالة العميل واستخرج أي من هذه الحقول إن وُجدت. "
                    "بالنسبة للتواريخ، حولها لصيغة YYYY-MM-DD. "
                    "بالنسبة للمدة (duration)، استنتجها بالأشهر إن أمكن. "
                    "يجب أن يكون الرد عبارة عن كائن JSON صالح فقط (بدون أي نص إضافي أو markdown) "
                    "يحتوي على المفاتيح التي تم العثور عليها وقيمها."
                )
                
                ai_res = AIService.generate(
                    tenant_id=tenant.id,
                    user_message=msg,
                    system_prompt=prompt
                )
                
                if ai_res.success and ai_res.text:
                    try:
                        json_str = re.sub(r'```json\n?|```\n?', '', ai_res.text).strip()
                        extracted = json.loads(json_str)
                        if isinstance(extracted, dict):
                            for k, v in extracted.items():
                                if v and str(v).lower() not in ('null', 'none', ''):
                                    ContractService.add_field_value(contract, k, v)
                    except Exception as e:
                        current_app.logger.warning(f"[Chat] Failed to parse AI extraction JSON: {e}")
                        
                # احتياطي: إذا كان هناك حقل معلق ولم يُستخرج، نعتبر الرسالة إجابة له
                pending_key = sd.get('pending_field_key')
                if pending_key and (not contract.field_values.get(pending_key)):
                    ContractService.add_field_value(contract, pending_key, msg)

            next_field = ContractService.get_next_required_field(contract)
            if next_field:
                sd2 = dict(sd)
                sd2['pending_field_key'] = next_field['key']
                _save_state(sd2)
                db.session.commit()
                return ContractService.field_prompt(next_field)

            sd2 = dict(sd)
            sd2['contract_stage'] = 'choose_payment'
            sd2.pop('pending_field_key', None)
            _save_state(sd2)
            db.session.commit()
            amt = float(contract.payment_amount or 0)
            return (
                f"تمام، تم جمع كل البيانات ✅\n"
                f"المبلغ المطلوب: {amt:.2f} ر.س\n\n"
                "اختر طريقة الدفع:\n"
                "1️⃣ دفع إلكتروني (مدى/فيزا)\n"
                "2️⃣ تحويل بنكي (ترسل صورة الإيصال)"
            )

        # ====== مرحلة اختيار الدفع ======
        if stage == 'choose_payment':
            low = msg.lower()
            if '1' in low or 'الكترون' in low or 'إلكترون' in low or 'مدى' in low or 'فيزا' in low:
                from app.services.payment_service import PaymentService
                pay = PaymentService.create_payment_link(
                    tenant_id=tenant.id,
                    amount=float(contract.payment_amount or 0),
                    description=f'عقد {contract.contract_number}',
                    customer_name=contract.customer_name or '',
                    customer_email=contract.customer_email or '',
                    customer_phone=contract.customer_phone or '',
                )
                if not pay.get('success'):
                    return (
                        'تعذّر إنشاء رابط الدفع الإلكتروني حالياً '
                        f"({pay.get('error', '—')}).\n"
                        'تقدر تختار 2 للتحويل البنكي.'
                    )
                contract.status = 'pending_payment'
                contract.payment_reference = pay.get('payment_id') or ''
                sd2 = dict(sd)
                sd2['contract_stage'] = 'awaiting_online_payment'
                _save_state(sd2)
                db.session.commit()
                return (
                    'افتح الرابط لإتمام الدفع الإلكتروني:\n'
                    f"{pay.get('payment_url')}\n\n"
                    'بعد الدفع سيُرسَل لك العقد مباشرة.'
                )
            if '2' in low or 'تحويل' in low or 'بنك' in low:
                sd2 = dict(sd)
                sd2['contract_stage'] = 'awaiting_transfer_proof'
                _save_state(sd2)
                db.session.commit()
                bank_info = ChatService._tenant_bank_info(tenant)
                return (
                    'تمام — حوّل المبلغ على الحساب التالي:\n'
                    f'{bank_info}\n\n'
                    'بعد التحويل أرسل صورة الإيصال هنا (رابط الصورة) لمراجعتها من الفريق.'
                )
            return 'اختر رقم: 1 للدفع الإلكتروني، 2 للتحويل البنكي.'

        # ====== مرحلة استلام إيصال التحويل ======
        if stage == 'awaiting_transfer_proof':
            url = msg.strip()
            if not (url.startswith('http://') or url.startswith('https://')):
                return (
                    'أرسل رابط صورة الإيصال (يبدأ بـ http) — أو اضغط على زر إرفاق الصورة.\n'
                    'وللخروج من هذه الخطوة اكتب: كنسل'
                )

            contract.bank_transfer_proof_url = url[:500]
            contract.status = 'awaiting_approval'
            contract.payment_status = 'awaiting_approval'
            _save_state(None)
            db.session.commit()

            # إشعار التاجر بالبريد
            try:
                from app.services.email_service import EmailService
                if tenant.owner_email:
                    EmailService._send(
                        to=tenant.owner_email,
                        subject=f'تحويل بنكي بانتظار الموافقة — {contract.contract_number}',
                        body_html=(
                            f'<div dir="rtl" style="font-family:Tahoma">'
                            f'<p>عميل أرسل تحويلاً بنكياً للعقد <b>{contract.contract_number}</b>.</p>'
                            f'<p>المبلغ: <b>{float(contract.payment_amount or 0):.2f} ر.س</b></p>'
                            f'<p><a href="{contract.bank_transfer_proof_url}">عرض الإيصال</a></p>'
                            f'<p>راجعه من لوحة التاجر → العقود → تحويلات بانتظار الموافقة.</p>'
                            f'</div>'
                        ),
                    )
            except Exception as e:
                current_app.logger.warning(f'[Chat] tenant transfer email failed: {e}')

            return (
                'تم استلام الإيصال ✅\n'
                'سيُراجَع من فريق التاجر، وسيصلك العقد بعد الموافقة.'
            )

        return None

    @staticmethod
    def _tenant_bank_info(tenant: Tenant) -> str:
        """بيانات الحساب البنكي للتاجر — تُرسَل للعميل عند طلب التحويل."""
        parts = []
        for attr, label in (
            ('bank_name', '🏦 البنك'),
            ('bank_account_name', '👤 اسم صاحب الحساب'),
            ('bank_account_number', '🔢 رقم الحساب'),
            ('bank_iban', '🆔 الآيبان'),
        ):
            v = (getattr(tenant, attr, '') or '').strip()
            if v:
                parts.append(f'{label}: {v}')
        if not parts:
            return 'لم يضِف التاجر بياناته البنكية بعد. تواصل معه مباشرة.'
        return '\n'.join(parts)

    @staticmethod
    def _is_image_request_followup(text: str) -> bool:
        """يلتقط طلب الزائر لصور بعد إخباره أن الصور لم تُرفع."""
        if not text:
            return False
        t = text.strip().lower()
        for a, b in (('أ', 'ا'), ('إ', 'ا'), ('آ', 'ا'), ('ة', 'ه'), ('ى', 'ي')):
            t = t.replace(a, b)
        triggers = (
            'ابي صور', 'ابغى صور', 'ابغي صور', 'ودي صور',
            'محتاج صور', 'حابب صور', 'حاب صور', 'ارسلوا صور',
            'ارسلولي صور', 'ابي اشوف', 'صور مباشره',
        )
        return any(k in t for k in triggers)

    @staticmethod
    def is_bank_info_request(text: str) -> bool:
        """هل الرسالة تطلب بيانات الحساب البنكي؟"""
        if not text:
            return False
        t = text.strip().lower()
        for a, b in (('أ','ا'),('إ','ا'),('آ','ا'),('ة','ه'),('ى','ي')):
            t = t.replace(a, b)
        keys = (
            'وش حسابك', 'وش الحساب', 'الحساب البنكي', 'حسابك البنكي',
            'كيف احول', 'كيف احولك', 'بحول', 'ابي احول', 'ابغى احول',
            'ايبان', 'الايبان', 'iban', 'رقم الحساب', 'حساب بنكي',
            'وش رقم حسابك', 'عطني الحساب', 'ودي احول',
        )
        return any(k in t for k in keys)

    @staticmethod
    def _build_history(conversation):
        """تاريخ المحادثة بصيغة AIService."""
        msgs = conversation.messages.order_by(Message.created_at).limit(20).all()
        return [
            {'sender_type': m.sender_type, 'content': m.content}
            for m in msgs
        ]

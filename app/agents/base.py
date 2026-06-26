"""
app/agents/base.py — الطبقة الأساسية لجميع وكلاء الذكاء الاصطناعي.

توفر:
- تهيئة LangChain LLM تلقائياً حسب نموذج التاجر
- تتبع الاستهلاك (Tokens) وتسجيله في MessageUsage + خصمه من المحفظة
- إدارة ذاكرة المحادثة (ConversationBufferWindowMemory)
- معالجة الأخطاء بشكل موحد
"""
import logging
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.tools import BaseTool
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from app.extensions import db
from app.models.message_usage import MessageUsage
from app.models.conversation import Conversation, Message
from app.services.pricing_service import PricingService
from .model_resolver import ModelResolver, ResolvedModel

logger = logging.getLogger(__name__)


@dataclass
class AgentResponse:
    """نتيجة تشغيل وكيل."""
    success: bool = False
    text: str = ''
    error: str = ''
    tokens_in: int = 0
    tokens_out: int = 0
    price_charged: float = 0.0
    tool_calls: List[Dict] = field(default_factory=list)
    agent_type: str = ''


class BaseAgent:
    """
    الطبقة الأساسية لجميع الوكلاء — يمتد منها كل وكيل متخصص.

    الاستخدام:
        class FrontDeskAgent(BaseAgent):
            AGENT_TYPE = 'front_desk'
            SYSTEM_PROMPT = '...'
            def get_tools(self): return [...]

        agent = FrontDeskAgent(tenant_id=1)
        result = agent.run("أريد حجز غرفة")
    """

    AGENT_TYPE: str = 'general'
    SYSTEM_PROMPT: str = ''
    MAX_HISTORY: int = 10     # عدد الرسائل المحفوظة في الذاكرة
    MAX_ITERATIONS: int = 5   # الحد الأقصى لخطوات التفكير
    SERVICE_KEY: str = 'ai_message'  # مفتاح الخدمة في جدول التسعير

    def __init__(self, tenant_id: int, conversation_id: int = None):
        self.tenant_id = tenant_id
        self.conversation_id = conversation_id
        self._resolved_model: Optional[ResolvedModel] = None

    def get_tools(self) -> List[BaseTool]:
        """يُعرِّف الأدوات المتاحة لهذا الوكيل — يُنفَّذ في كل فئة فرعية."""
        return []

    def get_system_prompt(self) -> str:
        """يُرجع System Prompt مع إمكانية التخصيص لكل تاجر."""
        from app.services.facility_memory_service import FacilityMemoryService
        
        base_prompt = self.SYSTEM_PROMPT
        memory_context = FacilityMemoryService.get_context_for_agent(self.tenant_id, self.AGENT_TYPE)
        
        if memory_context:
            return f"{base_prompt}\n\n[معلومات إضافية ومهمة عن المنشأة]:\n{memory_context}"
        return base_prompt

    def _resolve_model(self) -> Optional[ResolvedModel]:
        """تحديد النموذج والمفتاح المناسب."""
        if not self._resolved_model:
            self._resolved_model = ModelResolver.resolve(
                self.tenant_id, agent_type=self.AGENT_TYPE
            )
        return self._resolved_model

    def _build_llm(self):
        """بناء LLM من LangChain بناءً على النموذج المحدد."""
        resolved = self._resolve_model()
        if not resolved:
            return None

        if resolved.provider == 'openai':
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=resolved.model_id,
                api_key=resolved.api_key,
                temperature=resolved.temperature,
                max_tokens=1024,
            )
        elif resolved.provider == 'anthropic':
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(
                model=resolved.model_id,
                api_key=resolved.api_key,
                temperature=resolved.temperature,
                max_tokens=1024,
            )
        elif resolved.provider == 'google':
            from langchain_google_genai import ChatGoogleGenerativeAI
            return ChatGoogleGenerativeAI(
                model=resolved.model_id,
                google_api_key=resolved.api_key,
                temperature=resolved.temperature,
                max_output_tokens=1024,
            )
        else:
            logger.error(f'[Agent] مزوّد غير مدعوم: {resolved.provider}')
            return None

    def _load_history(self) -> List:
        """تحميل تاريخ المحادثة من قاعدة البيانات."""
        if not self.conversation_id:
            return []

        messages = Message.query.filter_by(
            conversation_id=self.conversation_id
        ).order_by(
            Message.created_at.desc()
        ).limit(self.MAX_HISTORY).all()

        # عكس الترتيب ليكون من الأقدم للأحدث
        messages = list(reversed(messages))

        history = []
        for msg in messages:
            if msg.sender_type in ('visitor', 'user'):
                history.append(HumanMessage(content=msg.content))
            elif msg.sender_type in ('bot', 'agent'):
                history.append(AIMessage(content=msg.content))
        return history

    def _track_usage(self, tokens_in: int, tokens_out: int) -> float:
        """تسجيل الاستهلاك وخصم التكلفة من محفظة التاجر."""
        resolved = self._resolve_model()
        if not resolved or not resolved.ai_model_db_id:
            return 0.0

        try:
            success, msg, charged = PricingService.charge(
                tenant_id=self.tenant_id,
                service_key=self.SERVICE_KEY,
                ai_model_id=resolved.ai_model_db_id,
                conversation_id=self.conversation_id,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                extra={'agent_type': self.AGENT_TYPE},
            )
            if success:
                return charged
            else:
                logger.warning(f'[Agent] فشل الخصم: {msg}')
                return 0.0
        except Exception as e:
            logger.exception(f'[Agent] خطأ في تسجيل الاستهلاك: {e}')
            return 0.0

    def _check_balance(self) -> tuple:
        """التحقق من رصيد التاجر قبل تشغيل الوكيل."""
        resolved = self._resolve_model()
        if not resolved:
            return False, 'لا يوجد نموذج AI متاح'

        # إذا المفتاح خاص بالتاجر → لا نخصم
        if resolved.is_tenant_key:
            return True, 'مفتاح خاص'

        ok, msg, price = PricingService.can_afford(
            self.tenant_id, self.SERVICE_KEY, resolved.ai_model_db_id
        )
        return ok, msg

    def run(self, user_message: str, channel: str = 'web',
            visitor_id: str = '', extra_context: dict = None) -> AgentResponse:
        """
        تشغيل الوكيل على رسالة المستخدم.

        Args:
            user_message: نص رسالة المستخدم
            channel: القناة (web, whatsapp, facebook, tiktok, snapchat, google_reviews)
            visitor_id: معرف الزائر
            extra_context: سياق إضافي (مثل بيانات الهوية، صور)

        Returns:
            AgentResponse مع النتيجة
        """
        logger.info(f'[Agent RUN] type={self.AGENT_TYPE}')
        # 1. التحقق من الرصيد
        can_run, balance_msg = self._check_balance()
        if not can_run:
            return AgentResponse(
                success=False,
                error=balance_msg,
                agent_type=self.AGENT_TYPE,
            )

        # 2. بناء LLM
        llm = self._build_llm()
        if not llm:
            return AgentResponse(
                success=False,
                error='لم يتم ضبط نموذج AI. تواصل مع الدعم.',
                agent_type=self.AGENT_TYPE,
            )

        # 3. جلب الأدوات
        tools = self.get_tools()

        # 4. بناء الرسائل
        messages = []
        system_prompt = self.get_system_prompt()
        
        language_directive = "\n\n[هام جداً]: التزم دائماً بالرد بنفس لغة المستخدم. إذا تحدث بالإنجليزية أجب بالإنجليزية، وإذا تحدث بالعربية أجب بالعربية، وهكذا لجميع اللغات."
        
        if system_prompt:
            system_prompt += language_directive
            messages.append(SystemMessage(content=system_prompt))

        # تحميل التاريخ
        history = self._load_history()
        messages.extend(history)

        # إضافة سياق إضافي إن وجد
        if extra_context:
            context_text = '\n'.join([f'{k}: {v}' for k, v in extra_context.items()])
            messages.append(SystemMessage(content=f'سياق إضافي:\n{context_text}'))

        # رسالة المستخدم
        messages.append(HumanMessage(content=user_message))

        try:
            # 5. تشغيل الوكيل
            if tools:
                # وكيل مع أدوات
                llm_with_tools = llm.bind_tools(tools)

                prompt = ChatPromptTemplate.from_messages([
                    ("system", system_prompt),
                    MessagesPlaceholder(variable_name="chat_history"),
                    ("human", "{input}"),
                    MessagesPlaceholder(variable_name="agent_scratchpad"),
                ])

                agent = create_tool_calling_agent(llm, tools, prompt)
                executor = AgentExecutor(
                    agent=agent,
                    tools=tools,
                    max_iterations=self.MAX_ITERATIONS,
                    verbose=False,
                    return_intermediate_steps=True,
                    handle_parsing_errors=True,
                )

                result = executor.invoke({
                    "input": user_message,
                    "chat_history": history,
                })
                response_text = result.get('output', '')
                tool_calls_info = []

                # استخراج معلومات الأدوات المستدعاة من الخطوات الوسيطة
                for step in result.get('intermediate_steps', []):
                    if len(step) >= 2:
                        action = step[0]
                        tool_calls_info.append({
                            'tool': getattr(action, 'tool', 'unknown'),
                            'input': str(getattr(action, 'tool_input', ''))[:200],
                        })

            else:
                # محادثة بسيطة بدون أدوات
                response = llm.invoke(messages)
                response_text = response.content
                tool_calls_info = []

            # 6. حساب التوكنز (تقريبي إذا لم يوفره المزوّد)
            tokens_in = len(user_message) // 4 + sum(len(m.content) // 4 for m in messages)
            tokens_out = len(response_text) // 4

            # محاولة جلب قيم دقيقة من metadata
            if hasattr(response, 'response_metadata') if not tools else False:
                meta = response.response_metadata or {}
                usage = meta.get('usage', meta.get('token_usage', {}))
                if usage:
                    tokens_in = usage.get('input_tokens', usage.get('prompt_tokens', tokens_in))
                    tokens_out = usage.get('output_tokens', usage.get('completion_tokens', tokens_out))

            # 7. تسجيل الاستهلاك
            price_charged = self._track_usage(tokens_in, tokens_out)

            return AgentResponse(
                success=True,
                text=response_text,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                price_charged=price_charged,
                tool_calls=tool_calls_info,
                agent_type=self.AGENT_TYPE,
            )

        except Exception as e:
            logger.exception(f'[{self.AGENT_TYPE}] خطأ في تشغيل الوكيل: {e}')
            return AgentResponse(
                success=False,
                error=f'حدث خطأ أثناء المعالجة: {str(e)[:150]}',
                agent_type=self.AGENT_TYPE,
            )

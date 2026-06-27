"""
app/agents/agent_manager.py — AIRouter (موزع المهام)

يقرأ رسالة المستخدم ويحدد النية (Intent) بناءً عليها لتحويل المحادثة إلى الوكيل المختص.
"""
import logging
from typing import Dict, Type
from langchain_core.messages import HumanMessage, SystemMessage

from .base import BaseAgent, AgentResponse
from .front_desk_agent import FrontDeskAgent
from .accounting_agent import AccountingAgent
from .collection_agent import CollectionAgent

logger = logging.getLogger(__name__)

class AgentManager(BaseAgent):
    """
    موجه الذكاء الاصطناعي الذي يحدد الوكيل المناسب بناءً على رسالة المستخدم وتاريخ المحادثة.
    """
    AGENT_TYPE = 'router'
    SYSTEM_PROMPT = """أنت موجه ذكي (Router) في نظام فندقي/عقاري متعدد الوكلاء.
مهمتك الوحيدة هي تحديد الوكيل المناسب للرد على رسالة المستخدم بناءً على نيته.
يجب أن يكون ردك عبارة عن كلمة واحدة فقط من الخيارات التالية:
- reception : إذا كان المستخدم يستفسر عن الغرف، التوفر، الأسعار، يريد البدء بحجز جديد، إتمام الحجز، إرسال الهوية، إصدار العقد، أو الدفع.
- accounting : إذا كان المستخدم (أو التاجر) يسأل عن الأرباح، القيود المحاسبية، الإيرادات والمصروفات، الإشغال أو تقارير مالية.
- collection : إذا كان المستخدم يسأل عن المديونيات، المتأخرات، أو سداد دفعات سابقة.

لا تضف أي نص آخر، فقط اكتب اسم الوكيل (reception, accounting, collection).
"""

    AGENT_MAP: Dict[str, Type[BaseAgent]] = {
        "reception": FrontDeskAgent,
        "contract": FrontDeskAgent,
        "accounting": AccountingAgent,
        "collection": CollectionAgent,
    }

    def __init__(self, tenant_id: int, conversation_id: int = None, channel: str = "web"):
        super().__init__(tenant_id, conversation_id)
        self.channel = channel

    def _determine_intent_with_llm(self, user_message: str) -> str:
        llm = self._build_llm()
        if not llm:
            return "reception"
        
        try:
            messages = [
                SystemMessage(content=self.SYSTEM_PROMPT),
                HumanMessage(content=user_message)
            ]
            response = llm.invoke(messages)
            intent = response.content.strip().lower()
            
            for key in self.AGENT_MAP.keys():
                if key in intent:
                    return key
            return "reception"
        except Exception as e:
            logger.error(f"[AgentManager] Error determining intent: {e}")
            return "reception"

    def _validate_agents(self):
        """التحقق الاستباقي من صحة خريطة الوكلاء (Fail-Fast Validation)"""
        # التحقق من الوكيل الافتراضي
        default_agent = FrontDeskAgent
        if not default_agent or not issubclass(default_agent, BaseAgent):
            raise TypeError("Default agent 'FrontDeskAgent' is not properly defined or does not inherit from BaseAgent.")
            
        # التحقق من خريطة الوكلاء
        for intent, agent_cls in self.AGENT_MAP.items():
            if not agent_cls:
                raise ValueError(f"Agent class for intent '{intent}' is None.")
            if not issubclass(agent_cls, BaseAgent):
                raise TypeError(f"Agent class '{agent_cls.__name__}' for intent '{intent}' must inherit from BaseAgent.")

    def route_and_run(self, user_message: str, visitor_id: str = "", extra_context: dict = None) -> AgentResponse:
        # تنفيذ التحقق الاستباقي قبل التشغيل
        self._validate_agents()
        
        intent = self._determine_intent_with_llm(user_message)
        logger.info(f"[AgentManager] Routed message to: {intent}")
        
        # الاعتماد على FrontDeskAgent كوكيل افتراضي بدلاً من ReceptionAgent المحذوف
        agent_class = self.AGENT_MAP.get(intent, FrontDeskAgent)
        agent = agent_class(tenant_id=self.tenant_id, conversation_id=self.conversation_id, channel=self.channel)
        
        if extra_context is None:
            extra_context = {}
        extra_context["routed_intent"] = intent
        
        return agent.run(user_message, channel=self.channel, visitor_id=visitor_id, extra_context=extra_context)


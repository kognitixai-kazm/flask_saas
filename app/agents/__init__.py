"""
app/agents/__init__.py — وكلاء الذكاء الاصطناعي (AI Agents Layer)

يحتوي هذا الموديول على:
- base: الطبقة الأساسية لجميع الوكلاء
- model_resolver: تحديد النموذج والمفتاح لكل تاجر
- tools/: أدوات الوكلاء (غرف، عقود، دفع، تحليلات)
- front_desk_agent: وكيل الاستقبال والتعاقد القديم
- manager_agent: وكيل الإدارة والتحليلات (شريط البحث الذكي)
- agent_manager: موزع المهام للوكلاء المتخصصين
- reception_agent: وكيل الاستقبال
- contract_agent: وكيل التعاقد
- accounting_agent: الوكيل المحاسبي
- collection_agent: وكيل التحصيل
"""

from .base import BaseAgent
from .model_resolver import ModelResolver, ResolvedModel
from .front_desk_agent import FrontDeskAgent
from .manager_agent import ManagerAgent
from .agent_manager import AgentManager
from .reception_agent import ReceptionAgent
from .contract_agent import ContractAgent
from .accounting_agent import AccountingAgent
from .collection_agent import CollectionAgent

__all__ = [
    'BaseAgent',
    'ModelResolver',
    'ResolvedModel',
    'FrontDeskAgent',
    'ManagerAgent',
    'AgentManager',
    'ReceptionAgent',
    'ContractAgent',
    'AccountingAgent',
    'CollectionAgent',
]

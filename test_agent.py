import os
import sys
sys.stdout.reconfigure(encoding='utf-8')
from app import create_app, db
from app.models.tenant import Tenant
from app.models.conversation import Conversation
from app.agents.front_desk_agent import FrontDeskAgent

app = create_app()

with app.app_context():
    # الحصول على أول تاجر مفعل
    tenants = Tenant.query.all()
    tenant = next((t for t in tenants if t.activity and t.activity.code == 'hotel'), None)
    if not tenant:
        print("لا يوجد تاجر نشاطه فندق.")
        exit()
        
    print(f"Test Tenant: {tenant.business_name} (ID: {tenant.id})")
    
    # محاكاة محادثة جديدة
    conv = Conversation(
        tenant_id=tenant.id,
        channel='web',
        visitor_id='test_visitor_123',
        visitor_name='أحمد الزائر',
        visitor_phone='0501234567'
    )
    db.session.add(conv)
    db.session.commit()
    
    print(f"Test Conversation ID: {conv.id}")
    
    # رسالة الزائر
    user_message = "اريد حجز الغرفة 101 لمدة شهر. اسمي أحمد ورقمي 0501234567. وسأدفع تحويل بنكي. سوي العقد الان."
    print(f"\nUser Message: {user_message}\n")
    
    # تشغيل الوكيل
    agent = FrontDeskAgent(tenant_id=tenant.id, conversation_id=conv.id)
    response = agent.run(user_message=user_message)
    
    print("=== Agent Response ===")
    print(f"Success: {response.success}")
    if not response.success:
        print(f"Error: {response.error}")
    print("Content:")
    print(response.text)
    print("Tool Calls:", getattr(response, "tool_calls", []))
    print("======================")

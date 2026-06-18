import os
from pathlib import Path
from flask import current_app

# Load environment
from dotenv import load_dotenv
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')

from app import create_app
from app.services.email_service import EmailService

def send_test_reminder():
    app = create_app()
    with app.app_context():
        to_email = "almthnykazmnjyb@gmail.com"
        subject = "تذكير: اقتراب موعد سداد الإيجار - (نسخة تجريبية)"
        
        # Example data for the template
        tenant_name = "مؤسسة كوجنيتكس العقارية"
        contract_number = "CON-1-2026-0010"
        amount = "1,500"
        due_date = "2026-06-17"
        
        # Bank info example
        bank_name = "بنك الراجحي"
        bank_account_name = "مؤسسة كوجنيتكس العقارية"
        bank_iban = "SA12345678901234567890"
        
        # Payment link example (assuming electronic payment is enabled)
        payment_link = f"{app.config.get('SITE_URL', 'http://localhost:5000')}/pay/{contract_number}"
        
        body_html = f"""
        <div dir="rtl" style="font-family:Tahoma,Arial,sans-serif; padding:20px; max-width:600px; margin:0 auto; border:1px solid #e2e8f0; border-radius:10px; background-color:#f8fafc;">
            <div style="text-align:center; padding-bottom:15px; border-bottom:2px solid #2563eb;">
                <h2 style="color:#2563eb; margin:0;">{tenant_name}</h2>
            </div>
            
            <div style="padding:20px 0; color:#333; line-height:1.6;">
                <h3 style="color:#eab308; margin-top:0;">تذكير بسداد دفعة الإيجار ⏰</h3>
                <p>عزيزي العميل،</p>
                <p>نود تذكيركم باقتراب موعد سداد الإيجار الخاص بالعقد رقم <strong>{contract_number}</strong>.</p>
                
                <table style="width:100%; border-collapse:collapse; margin:20px 0; background:#fff; border-radius:5px; overflow:hidden;">
                    <tr>
                        <td style="padding:10px; border:1px solid #e2e8f0; font-weight:bold; width:40%;">المبلغ المستحق:</td>
                        <td style="padding:10px; border:1px solid #e2e8f0; color:#b91c1c; font-weight:bold;">{amount} ر.س</td>
                    </tr>
                    <tr>
                        <td style="padding:10px; border:1px solid #e2e8f0; font-weight:bold;">تاريخ الاستحقاق:</td>
                        <td style="padding:10px; border:1px solid #e2e8f0;">{due_date}</td>
                    </tr>
                </table>

                <h4 style="color:#1e40af; border-bottom:1px solid #cbd5e1; padding-bottom:5px;">💳 خيارات الدفع المتاحة:</h4>
                
                <div style="background:#eff6ff; padding:15px; border-radius:8px; border-right:4px solid #3b82f6; margin-bottom:15px;">
                    <p style="margin:0 0 10px 0; font-weight:bold; color:#1d4ed8;">1. الدفع الإلكتروني المباشر (مدى، فيزا، ماستركارد، أبل باي):</p>
                    <a href="{payment_link}" style="display:inline-block; background:#2563eb; color:#fff; padding:10px 20px; text-decoration:none; border-radius:5px; font-weight:bold;">ادفع الآن بأمان</a>
                </div>

                <div style="background:#f1f5f9; padding:15px; border-radius:8px; border-right:4px solid #64748b;">
                    <p style="margin:0 0 10px 0; font-weight:bold; color:#334155;">2. التحويل البنكي:</p>
                    <ul style="list-style-type:none; padding:0; margin:0; color:#475569;">
                        <li style="margin-bottom:5px;"><strong>البنك:</strong> {bank_name}</li>
                        <li style="margin-bottom:5px;"><strong>اسم الحساب:</strong> {bank_account_name}</li>
                        <li style="margin-bottom:5px;"><strong>رقم الآيبان (IBAN):</strong> <span dir="ltr">{bank_iban}</span></li>
                    </ul>
                    <p style="margin-top:10px; font-size:12px; color:#ef4444;">* يرجى إرسال إيصال التحويل بعد إتمام العملية أو رفعه عبر النظام.</p>
                </div>
                
                <p style="margin-top:25px; font-size:14px; text-align:center; color:#64748b;">
                    نشكر لكم ثقتكم وحسن تعاونكم،<br>
                    <strong>إدارة {tenant_name}</strong>
                </p>
            </div>
        </div>
        """
        
        try:
            EmailService._send(to_email, subject, body_html)
            print("✅ تم إرسال رسالة التذكير التجريبية بنجاح إلى", to_email)
        except Exception as e:
            print("❌ فشل إرسال البريد:", str(e))

if __name__ == "__main__":
    send_test_reminder()

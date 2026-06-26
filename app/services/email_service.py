"""
app/services/email_service.py — إرسال الإيميلات.
يُستخدم لإبلاغ صاحب النشاط عند وصول استفسار جديد + رابط إعداد المستأجر.
في التطوير (MAIL_ENABLED=False): لا إرسال SMTP؛ دوال الإعداد ترجع False لتُظهر الرابط في الواجهة.
"""
import html as html_module
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import current_app


class EmailService:

    @staticmethod
    def send_inquiry_notification(
        to_email: str,
        business_name: str,
        branch_name: str,
        question: str,
        visitor_info: str = '',
        inquiry_id: int = None,
        inquiry_kind: str = 'general',
        complaint_category_ar: str = '',
    ) -> bool:
        """إرسال إيميل لصاحب النشاط عند استفسار جديد."""
        is_complaint = (inquiry_kind or '').strip() == 'complaint'
        subject = (
            f"⚠️ شكوى جديدة — {business_name}" if is_complaint
            else f"📩 استفسار جديد — {business_name}"
        )
        heading = "⚠️ شكوى جديدة" if is_complaint else "📩 استفسار جديد"
        heading_color = "#b45309" if is_complaint else "#2563eb"
        btn_bg = "#b45309" if is_complaint else "#2563eb"

        dashboard_url = current_app.config['SITE_URL'] + '/app/inquiries'

        meta_block = ''
        if is_complaint and complaint_category_ar:
            meta_block = f"<p><strong>تصنيف الشكوى:</strong> {complaint_category_ar}</p>"
        elif is_complaint:
            meta_block = "<p><strong>النوع:</strong> شكوى</p>"

        body_html = f"""
        <div dir="rtl" style="font-family:Tahoma,Arial;padding:20px;background:#f8f9fa;border-radius:12px;">
            <h2 style="color:{heading_color};">{heading}</h2>
            <p><strong>النشاط:</strong> {business_name}</p>
            <p><strong>الفرع:</strong> {branch_name}</p>
            {meta_block}
            {f'<p><strong>بيانات المشتكي / الزائر:</strong><br>{visitor_info}</p>' if visitor_info else ''}
            <div style="background:#fff;padding:16px;border-radius:8px;border:1px solid #e5e7eb;margin:16px 0;">
                <p style="font-size:15px;">{question}</p>
            </div>
            <a href="{dashboard_url}" style="display:inline-block;background:{btn_bg};color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold;">
                الرد من لوحة التحكم
            </a>
            <p style="color:#9ca3af;font-size:12px;margin-top:20px;">
                هذا الإيميل مُرسل تلقائياً من منصة خدمة العملاء.
            </p>
        </div>
        """

        return EmailService._send(to_email, subject, body_html)

    @staticmethod
    def send_tenant_setup_link(
        to_email: str,
        owner_name: str,
        business_name: str,
        setup_url: str,
    ) -> bool:
        """
        إرسال رابط إعداد الحساب للمالك.
        يرجع True فقط عند MAIL_ENABLED ونجاح SMTP.
        إذا البريد غير مفعّل: لا يُعتبر إرسالاً — يرجع False (لعرض الرابط في صفحة النجاح).
        """
        if not current_app.config.get('MAIL_ENABLED', False):
            return False

        site_name = html_module.escape(
            (current_app.config.get('SITE_NAME') or '').strip() or 'المنصة'
        )
        safe_owner = html_module.escape((owner_name or '').strip())
        safe_biz = html_module.escape((business_name or '').strip())
        safe_url = html_module.escape(setup_url or '', quote=True)

        subject = f'إكمال إعداد حسابك — {business_name}'
        body_html = f"""
        <div dir="rtl" style="font-family:Tahoma,Arial;padding:20px;background:#f8f9fa;border-radius:12px;">
            <h2 style="color:#2563eb;">مرحباً {safe_owner}</h2>
            <p>تم إنشاء حساب <strong>{safe_biz}</strong> على {site_name}.</p>
            <p>اضغط الزر أدناه لإكمال الإعداد (الرابط صالح لفترة محدودة):</p>
            <a href="{safe_url}" style="display:inline-block;background:#2563eb;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold;">
                إكمال الإعداد
            </a>
            <p style="color:#6b7280;font-size:13px;margin-top:16px;">إذا لم يعمل الزر، انسخ الرابط والصقه في المتصفح:<br><span style="word-break:break-all;">{safe_url}</span></p>
        </div>
        """
        return EmailService._send(to_email, subject, body_html)

    @staticmethod
    def send_tenant_credentials(
        to_email: str,
        owner_name: str,
        business_name: str,
        username: str,
        password: str,
    ) -> bool:
        """
        إرسال معلومات الدخول الافتراضية للمالك بعد الموافقة.
        """
        if not current_app.config.get('MAIL_ENABLED', False):
            return False

        site_name = html_module.escape(
            (current_app.config.get('SITE_NAME') or '').strip() or 'المنصة'
        )
        safe_owner = html_module.escape((owner_name or '').strip())
        safe_biz = html_module.escape((business_name or '').strip())
        safe_user = html_module.escape(username)
        safe_pass = html_module.escape(password)
        login_url = f"{current_app.config['SITE_URL'].rstrip('/')}/app/login"

        subject = f'معلومات دخول حسابك — {business_name}'
        body_html = f"""
        <div dir="rtl" style="font-family:Tahoma,Arial;padding:20px;background:#f8f9fa;border-radius:12px;">
            <h2 style="color:#2563eb;">مرحباً {safe_owner}</h2>
            <p>تمت الموافقة على طلب انضمام <strong>{safe_biz}</strong> إلى منصة {site_name}.</p>
            <p>تم إنشاء حسابك بنجاح، وإليك معلومات الدخول الافتراضية لتتمكن من الوصول للوحة التحكم الخاصة بك:</p>
            <div style="background:#fff;padding:16px;border-radius:8px;border:1px solid #e5e7eb;margin:16px 0; max-width: 450px;">
                <p style="margin: 4px 0;"><strong>رابط تسجيل الدخول:</strong> <a href="{login_url}">{login_url}</a></p>
                <p style="margin: 4px 0;"><strong>اسم المستخدم:</strong> <span style="font-family: monospace; font-size: 15px; font-weight: bold; color: #1e3a8a;">{safe_user}</span></p>
                <p style="margin: 4px 0;"><strong>كلمة المرور:</strong> <span style="font-family: monospace; font-size: 15px; font-weight: bold; color: #b91c1c;">{safe_pass}</span></p>
            </div>
            <p style="color:#ef4444; font-weight:bold; font-size:13px;">تنبيه: يمكنك تعديل اسم المستخدم وكلمة المرور في أي وقت بعد الدخول من خلال لوحة التحكم (الملف الشخصي).</p>
        </div>
        """
        return EmailService._send(to_email, subject, body_html)

    @staticmethod
    def send_visitor_inquiry_answer(
        to_email: str,
        business_name: str,
        question: str,
        answer: str,
    ) -> bool:
        """إرسال رد الفريق للزائر على بريده (بعد الرد من لوحة الاستفسارات)."""
        import html as _html

        subject = f"رد من {business_name} على استفسارك"
        safe_q = _html.escape((question or '')[:2000])
        safe_a = _html.escape((answer or '')[:8000])
        safe_b = _html.escape(business_name or '')
        body_html = f"""
        <div dir="rtl" style="font-family:Tahoma,Arial;padding:20px;background:#f8f9fa;">
            <h2 style="color:#059669;">رد من الفريق</h2>
            <p><strong>{safe_b}</strong></p>
            <p style="color:#6b7280;">استفسارك:</p>
            <div style="background:#fff;padding:14px;border-radius:8px;border:1px solid #e5e7eb;margin-bottom:16px;">{safe_q}</div>
            <p style="color:#6b7280;">الرد:</p>
            <div style="background:#ecfdf5;padding:14px;border-radius:8px;border:1px solid #a7f3d0;">{safe_a}</div>
        </div>
        """
        return EmailService._send(to_email, subject, body_html)

    @staticmethod
    def send_tenant_deletion_code(
        to_email: str,
        business_name: str,
        code: str,
    ) -> bool:
        """رمز تحقق لحذف النشاط من لوحة التاجر (يُرسل لبريد المالك المسجّل)."""
        import html as _html

        safe_b = _html.escape((business_name or '').strip())
        safe_code = _html.escape((code or '').strip())
        subject = f'رمز التحقق — حذف النشاط «{business_name}»'
        body_html = f"""
        <div dir="rtl" style="font-family:Tahoma,Arial;padding:20px;background:#f8f9fa;">
            <h2 style="color:#b91c1c;">تأكيد حذف النشاط</h2>
            <p>طُلب حذف نشاط <strong>{safe_b}</strong> من لوحة التحكم.</p>
            <p>إذا لم تطلب ذلك، تجاهل هذا البريد وغيّر كلمة مرور لوحة التحكم.</p>
            <p style="font-size:22px;letter-spacing:4px;font-weight:bold;margin:20px 0;">{safe_code}</p>
            <p style="color:#6b7280;font-size:13px;">الرمز صالح لمدة قصيرة فقط. لا تشاركه مع أحد.</p>
        </div>
        """
        ok = EmailService._send(to_email, subject, body_html)
        if ok and not current_app.config.get('MAIL_ENABLED', False):
            current_app.logger.info(
                '[delete-account] MAIL_ENABLED=false — deletion code (dev): %s for %s',
                code,
                to_email,
            )
        return ok

    @staticmethod
    def send_password_reset_link(
        to_email: str,
        intro_line: str,
        reset_url: str,
        expire_minutes: int = 60,
    ) -> bool:
        """رابط لمرة واحدة لإعادة تعيين كلمة المرور."""
        import html as _html

        safe_intro = _html.escape((intro_line or '').strip())
        safe_url = _html.escape((reset_url or '').strip(), quote=True)
        subject = 'إعادة تعيين كلمة المرور'
        body_html = f"""
        <div dir="rtl" style="font-family:Tahoma,Arial;padding:20px;background:#f8f9fa;">
            <h2 style="color:#1d4ed8;">إعادة تعيين كلمة المرور</h2>
            <p>{safe_intro}</p>
            <p>اضغط الزر أدناه لاختيار كلمة مرور جديدة. الرابط صالح لمدة {expire_minutes} دقيقة ولا يعمل إلا مرة واحدة.</p>
            <a href="{safe_url}" style="display:inline-block;background:#2563eb;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold;">
                إعادة تعيين كلمة المرور
            </a>
            <p style="color:#6b7280;font-size:13px;margin-top:16px;">إذا لم تطلب ذلك، تجاهل هذا البريد.</p>
            <p style="color:#9ca3af;font-size:12px;word-break:break-all;">{safe_url}</p>
        </div>
        """
        ok = EmailService._send(to_email, subject, body_html)
        if ok and not current_app.config.get('MAIL_ENABLED', False):
            current_app.logger.info(
                '[password-reset] MAIL_ENABLED=false — reset URL (dev): %s for %s',
                reset_url,
                to_email,
            )
        return ok

    @staticmethod
    def send_payment_reminder(
        to_email: str,
        tenant_name: str,
        contract_number: str,
        amount: str,
        due_date: str,
        payment_link: str,
        bank_name: str = '',
        bank_account_name: str = '',
        bank_iban: str = '',
    ) -> bool:
        """إرسال تذكير الدفع عبر الإيميل مع بيانات الحساب أو الدفع الإلكتروني."""
        import html as _html
        subject = f"تذكير: اقتراب موعد سداد الإيجار - {tenant_name}"
        
        safe_tenant = _html.escape(tenant_name)
        safe_contract = _html.escape(contract_number)
        safe_amount = _html.escape(str(amount))
        safe_due = _html.escape(str(due_date))
        
        body_html = f"""
        <div dir="rtl" style="font-family:Tahoma,Arial,sans-serif; padding:20px; max-width:600px; margin:0 auto; border:1px solid #e2e8f0; border-radius:10px; background-color:#f8fafc;">
            <div style="text-align:center; padding-bottom:15px; border-bottom:2px solid #2563eb;">
                <h2 style="color:#2563eb; margin:0;">{safe_tenant}</h2>
            </div>
            
            <div style="padding:20px 0; color:#333; line-height:1.6;">
                <h3 style="color:#eab308; margin-top:0;">تذكير بسداد دفعة الإيجار ⏰</h3>
                <p>عزيزي العميل،</p>
                <p>نود تذكيركم باقتراب موعد سداد الإيجار الخاص بالعقد رقم <strong>{safe_contract}</strong>.</p>
                
                <table style="width:100%; border-collapse:collapse; margin:20px 0; background:#fff; border-radius:5px; overflow:hidden;">
                    <tr>
                        <td style="padding:10px; border:1px solid #e2e8f0; font-weight:bold; width:40%;">المبلغ المستحق:</td>
                        <td style="padding:10px; border:1px solid #e2e8f0; color:#b91c1c; font-weight:bold;">{safe_amount} ر.س</td>
                    </tr>
                    <tr>
                        <td style="padding:10px; border:1px solid #e2e8f0; font-weight:bold;">تاريخ الاستحقاق:</td>
                        <td style="padding:10px; border:1px solid #e2e8f0;">{safe_due}</td>
                    </tr>
                </table>
        """
        
        body_html += """
                <h4 style="color:#1e40af; border-bottom:1px solid #cbd5e1; padding-bottom:5px;">💳 خيارات الدفع المتاحة:</h4>
                <div style="background:#eff6ff; padding:15px; border-radius:8px; border-right:4px solid #3b82f6; margin-bottom:15px;">
                    <p style="margin:0 0 10px 0; font-weight:bold; color:#1d4ed8;">1. الدفع الإلكتروني المباشر:</p>
                    <a href="{}" style="display:inline-block; background:#2563eb; color:#fff; padding:10px 20px; text-decoration:none; border-radius:5px; font-weight:bold;">ادفع الآن بأمان</a>
                </div>
        """.format(payment_link)

        if bank_iban:
            body_html += f"""
                <div style="background:#f1f5f9; padding:15px; border-radius:8px; border-right:4px solid #64748b;">
                    <p style="margin:0 0 10px 0; font-weight:bold; color:#334155;">2. التحويل البنكي:</p>
                    <ul style="list-style-type:none; padding:0; margin:0; color:#475569;">
                        <li style="margin-bottom:5px;"><strong>البنك:</strong> {_html.escape(bank_name)}</li>
                        <li style="margin-bottom:5px;"><strong>اسم الحساب:</strong> {_html.escape(bank_account_name)}</li>
                        <li style="margin-bottom:5px;"><strong>رقم الآيبان:</strong> <span dir="ltr">{_html.escape(bank_iban)}</span></li>
                    </ul>
                </div>
            """
            
        body_html += f"""
                <p style="margin-top:25px; font-size:14px; text-align:center; color:#64748b;">
                    نشكر لكم ثقتكم وحسن تعاونكم،<br>
                    <strong>إدارة {safe_tenant}</strong>
                </p>
            </div>
        </div>
        """
        return EmailService._send(to_email, subject, body_html)

    @staticmethod
    def send_signature_link(
        to_email: str,
        tenant_name: str,
        contract_number: str,
        sign_url: str,
    ) -> bool:
        """إرسال رابط توقيع العقد للعميل."""
        import html as _html
        subject = f"توقيع العقد الإلكتروني - {tenant_name}"
        
        safe_tenant = _html.escape(tenant_name)
        safe_contract = _html.escape(contract_number)
        
        body_html = f"""
        <div dir="rtl" style="font-family:Tahoma,Arial,sans-serif; padding:20px; max-width:600px; margin:0 auto; border:1px solid #e2e8f0; border-radius:10px; background-color:#f8fafc;">
            <div style="text-align:center; padding-bottom:15px; border-bottom:2px solid #2563eb;">
                <h2 style="color:#2563eb; margin:0;">{safe_tenant}</h2>
            </div>
            
            <div style="padding:20px 0; color:#333; line-height:1.6;">
                <h3 style="color:#10b981; margin-top:0;">رابط توقيع العقد ✍️</h3>
                <p>عزيزي العميل،</p>
                <p>تم تجهيز مسودة العقد رقم <strong>{safe_contract}</strong>.</p>
                <p>نرجو منك مراجعة العقد وتوقيعه إلكترونياً عبر الرابط التالي:</p>
                
                <div style="text-align:center; margin:30px 0;">
                    <a href="{sign_url}" style="display:inline-block; background:#10b981; color:#fff; padding:12px 25px; text-decoration:none; border-radius:5px; font-weight:bold; font-size:16px;">
                        توقيع العقد الآن
                    </a>
                </div>
                
                <p style="margin-top:25px; font-size:14px; text-align:center; color:#64748b;">
                    نشكر لكم ثقتكم وحسن تعاونكم،<br>
                    <strong>إدارة {safe_tenant}</strong>
                </p>
            </div>
        </div>
        """
        return EmailService._send(to_email, subject, body_html)

    @staticmethod
    def _send(to: str, subject: str, body_html: str) -> bool:
        """إرسال الإيميل (SMTP أو console)."""
        mail_enabled = current_app.config.get('MAIL_ENABLED', False)

        if not mail_enabled:
            # وضع التطوير: طباعة فقط
            current_app.logger.info(
                f'\n'
                f'╔══════════════════════════════════════╗\n'
                f'║  📧 EMAIL (dev mode — not sent)     ║\n'
                f'║  To: {to:<32s}  ║\n'
                f'║  Subject: {subject[:28]:<28s}  ║\n'
                f'╚══════════════════════════════════════╝\n'
                f'{body_html[:200]}...\n'
            )
            return True

        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = current_app.config['MAIL_DEFAULT_SENDER']
            msg['To'] = to
            msg.attach(MIMEText(body_html, 'html', 'utf-8'))

            server = smtplib.SMTP(
                current_app.config['MAIL_SERVER'],
                current_app.config['MAIL_PORT']
            )
            if current_app.config.get('MAIL_USE_TLS'):
                server.starttls()
            if current_app.config.get('MAIL_USERNAME'):
                server.login(
                    current_app.config['MAIL_USERNAME'],
                    current_app.config['MAIL_PASSWORD']
                )
            server.sendmail(msg['From'], [to], msg.as_string())
            server.quit()
            current_app.logger.info(f'Email sent to {to}: {subject}')
            return True
        except Exception as e:
            current_app.logger.error(f'Email failed to {to}: {e}')
            return False

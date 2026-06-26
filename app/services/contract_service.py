"""
app/services/contract_service.py — خدمة العقود الإلكترونية.

تتولى:
1. مطابقة رسائل العميل مع قوالب العقود
2. جمع البيانات تدريجياً (FSM للحوار)
3. توليد PDF أو إرسال لـ API خارجي
4. إرسال العقد للعميل والتاجر
"""
import io
import requests
from datetime import datetime
from typing import Optional, Dict, List
from flask import current_app

from app.extensions import db
from app.models.contract_template import ContractTemplate
from app.models.contract import Contract


class ContractService:
    """خدمة العقود الإلكترونية."""

    @staticmethod
    def find_matching_template(tenant_id: int, message: str) -> Optional[ContractTemplate]:
        """البحث عن قالب يطابق الرسالة."""
        templates = ContractTemplate.query.filter_by(
            tenant_id=tenant_id, is_active=True,
        ).all()
        for tpl in templates:
            if tpl.matches_message(message):
                return tpl
        return None

    @staticmethod
    def start_contract(tenant_id: int, template_id: int, conversation_id: int = None) -> Contract:
        """بدء عقد جديد (مسودة)."""
        contract = Contract(
            tenant_id=tenant_id,
            template_id=template_id,
            conversation_id=conversation_id,
            status='draft',
            field_values={},
        )
        db.session.add(contract)
        db.session.flush()
        contract.generate_contract_number()
        return contract

    @staticmethod
    def add_field_value(contract: Contract, field_key: str, value):
        """إضافة قيمة لحقل في العقد."""
        if not contract.field_values:
            contract.field_values = {}
        contract.field_values = {**contract.field_values, field_key: value}

        # حفظ في الحقول الرئيسية للسهولة
        if field_key == 'full_name':
            contract.customer_name = str(value)[:200]
        elif field_key == 'phone':
            contract.customer_phone = str(value)[:30]
        elif field_key == 'email':
            contract.customer_email = str(value)[:255]
        elif field_key == 'id_number':
            contract.customer_id_number = str(value)[:50]

    @staticmethod
    def get_next_required_field(contract: Contract) -> Optional[Dict]:
        """جلب الحقل التالي المطلوب جمعه."""
        template = contract.template
        if not template:
            return None

        required = template.required_fields or []
        collected = contract.field_values or {}

        for field in required:
            key = field.get('key')
            if not key:
                continue
            if key not in collected or not collected[key]:
                if field.get('required', False):
                    return field

        return None

    @staticmethod
    def is_complete(contract: Contract) -> bool:
        """هل تم جمع كل البيانات المطلوبة؟"""
        return ContractService.get_next_required_field(contract) is None

    @staticmethod
    def field_prompt(field: Dict) -> str:
        """رسالة سؤال للعميل لجمع حقل معين."""
        label = field.get('label', '')
        ftype = field.get('type', 'text')

        prompts = {
            'text': f'أرجو إدخال {label}:',
            'phone': f'أرجو إدخال {label} (رقم الجوال):',
            'email': f'أرجو إدخال {label}:',
            'id_number': f'أرجو إدخال {label} (10 أرقام):',
            'image': f'أرجو إرسال {label} (كصورة):',
            'date': f'أرجو إدخال {label} (مثال: 2026-05-01):',
            'number': f'أرجو إدخال {label} (رقم):',
        }
        return prompts.get(ftype, f'أرجو إدخال {label}:')

    # ========================================
    # توليد العقد
    # ========================================
    @staticmethod
    def generate_contract(contract: Contract) -> Dict:
        """توليد العقد النهائي."""
        template = contract.template
        if not template:
            return {'success': False, 'error': 'القالب غير موجود'}

        provider = (getattr(template, 'provider', '') or 'internal').strip().lower()
        if provider == 'external':
            return ContractService._generate_via_api(contract, template)
        return ContractService._generate_pdf_internal(contract, template)

    @staticmethod
    def _generate_pdf_internal(contract: Contract, template: ContractTemplate) -> Dict:
        """توليد PDF داخلياً بقالب جذاب يستخدم شعار التاجر ولونه."""
        try:
            pdf_bytes = ContractService._render_branded_pdf(contract, template)

            # حفظ العقد محلياً بدلاً من Cloudinary
            import os
            
            upload_dir = current_app.config['UPLOAD_FOLDER'] / 'contracts' / f'tenant_{contract.tenant_id}'
            upload_dir.mkdir(parents=True, exist_ok=True)
            
            filename = f'contract_{contract.contract_number}.pdf'
            file_path = upload_dir / filename
            
            with open(file_path, 'wb') as f:
                f.write(pdf_bytes)
                
            file_url = f'/static/uploads/contracts/tenant_{contract.tenant_id}/{filename}'
            
            contract.contract_pdf_url = file_url
            if contract.status != 'signed':
                contract.status = 'pending_signature'
            else:
                contract.signed_at = contract.signed_at or datetime.utcnow()
            
            return {'success': True, 'url': file_url}

        except Exception as e:
            current_app.logger.exception(f'[ContractService] PDF gen error: {e}')
            return {'success': False, 'error': str(e)[:200]}

    # ========================================
    # قالب PDF جذاب: شعار + ألوان + جداول + شروط
    # ========================================
    @staticmethod
    def _render_branded_pdf(contract: Contract, template: ContractTemplate) -> bytes:
        """يولّد PDF جذاب باسم النشاط وشعاره ولونه + بيانات + شروط + ميزات."""
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_RIGHT, TA_CENTER
        from reportlab.lib import colors
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, HRFlowable,
        )

        font_name = ContractService._ensure_arabic_font() or 'Helvetica'
        tenant = contract.tenant

        # لون أساسي من بيانات التاجر
        try:
            primary = colors.HexColor(tenant.primary_color or '#2563eb')
        except Exception:
            primary = colors.HexColor('#2563eb')

        # تحضير الأنماط
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'BrandTitle', parent=styles['Title'], fontName=font_name,
            fontSize=20, leading=26, alignment=TA_CENTER, textColor=primary,
        )
        subtitle = ParagraphStyle(
            'Subtitle', parent=styles['Normal'], fontName=font_name,
            fontSize=11, leading=16, alignment=TA_CENTER, textColor=colors.HexColor('#475569'),
        )
        section_h = ParagraphStyle(
            'SectionH', parent=styles['Heading2'], fontName=font_name,
            fontSize=13, leading=18, alignment=TA_RIGHT, textColor=primary,
            spaceBefore=10, spaceAfter=4,
        )
        body = ParagraphStyle(
            'Body', parent=styles['Normal'], fontName=font_name,
            fontSize=11, leading=18, alignment=TA_RIGHT, wordWrap='RTL',
        )
        small = ParagraphStyle(
            'Small', parent=styles['Normal'], fontName=font_name,
            fontSize=9, leading=12, alignment=TA_CENTER, textColor=colors.HexColor('#64748b'),
        )

        def shape(t):
            return ContractService._shape_arabic(str(t or ''))

        story = []

        # الشعار
        logo_flowable = ContractService._logo_flowable(tenant)
        if logo_flowable:
            story.append(logo_flowable)
            story.append(Spacer(1, 0.3 * cm))

        story.append(Paragraph(shape(tenant.business_name or ''), title_style))
        story.append(Paragraph(shape(template.name or 'عقد إيجار شقة مفروشة (شهري)'), subtitle))
        story.append(Spacer(1, 0.3 * cm))
        story.append(HRFlowable(width='100%', thickness=1.2, color=primary))
        story.append(Spacer(1, 0.4 * cm))

        # شريط معلومات سريع: رقم العقد + التاريخ
        info_data = [[
            Paragraph(shape(f'تاريخ العقد: {datetime.utcnow().strftime("%Y/%m/%d")} م'), body),
            Paragraph(shape(f'رقم العقد: {contract.contract_number or "-"}'), body),
        ]]
        info_t = Table(info_data, colWidths=['50%', '50%'])
        info_t.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8fafc')),
            ('PADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(info_t)
        story.append(Spacer(1, 0.4 * cm))

        fv = contract.field_values or {}

        # الطرف الأول والثاني
        parties_data = [
            [
                Paragraph(shape('الطرف الثاني (المستأجر)'), section_h),
                Paragraph(shape('الطرف الأول (المؤجر)'), section_h)
            ],
            [
                Paragraph(shape(f"الاسم: {fv.get('full_name') or contract.customer_name or '-'}"), body),
                Paragraph(shape(f"الاسم: {template.lessor_name or tenant.business_name or '-'}"), body)
            ],
            [
                Paragraph(shape(f"رقم الهوية: {fv.get('id_number') or contract.customer_id_number or '-'}"), body),
                Paragraph(shape(f"رقم السجل/الهوية: {template.lessor_id_number or '-'}"), body)
            ],
            [
                Paragraph(shape(f"رقم الجوال: {fv.get('phone') or contract.customer_phone or '-'}"), body),
                Paragraph(shape(f"رقم الجوال: {template.lessor_phone or '-'}"), body)
            ],
            [
                Paragraph(shape(f"العنوان: {fv.get('address') or '-'}"), body),
                Paragraph(shape(f"العنوان: {template.lessor_address or '-'}"), body)
            ]
        ]
        
        parties_t = Table(parties_data, colWidths=['50%', '50%'])
        parties_t.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
            ('BACKGROUND', (1, 0), (1, 0), colors.HexColor('#f1f5f9')),
            ('BACKGROUND', (0, 0), (0, 0), colors.HexColor('#f1f5f9')),
            ('PADDING', (0, 0), (-1, -1), 6),
            ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
        ]))
        story.append(parties_t)
        story.append(Spacer(1, 0.4 * cm))

        # تفاصيل العقار
        story.append(Paragraph(shape('تفاصيل العقار'), section_h))
        unit_name = fv.get('unit_name') or 'غير محدد'
        property_data = [
            [
                Paragraph(shape(f"نوع العقار: {fv.get('property_type', 'شقة مفروشة')}"), body),
                Paragraph(shape(f"رقم الشقة: {unit_name}"), body),
                Paragraph(shape(f"الدور: {fv.get('floor_number', '-')}"), body)
            ]
        ]
        prop_t = Table(property_data, colWidths=['33%', '33%', '34%'])
        prop_t.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
            ('PADDING', (0, 0), (-1, -1), 6),
            ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
        ]))
        story.append(prop_t)
        story.append(Spacer(1, 0.4 * cm))

        # مدة الإيجار
        story.append(Paragraph(shape('مدة الإيجار'), section_h))
        dates_data = [
            [
                Paragraph(shape(f"تاريخ الدخول: {fv.get('check_in_date') or '-'}"), body),
                Paragraph(shape(f"مدة الإيجار: {fv.get('duration') or '-'} شهر"), body),
                Paragraph(shape(f"تاريخ الخروج: {fv.get('check_out_date') or '-'}"), body)
            ]
        ]
        dates_t = Table(dates_data, colWidths=['33%', '33%', '34%'])
        dates_t.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
            ('PADDING', (0, 0), (-1, -1), 6),
            ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
        ]))
        story.append(dates_t)
        story.append(Spacer(1, 0.4 * cm))

        # قيمة الإيجار
        story.append(Paragraph(shape('قيمة الإيجار وطريقة الدفع'), section_h))
        amount_data = [
            [
                Paragraph(shape(f"قيمة الإيجار المتفق عليها: {float(contract.payment_amount or 0):.2f} ر.س"), body)
            ],
            [
                Paragraph(shape(f"طريقة الدفع: {template.payment_mode or 'دفعة واحدة قبل التسليم'}"), body)
            ]
        ]
        amount_t = Table(amount_data, colWidths=['100%'])
        amount_t.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
            ('BACKGROUND', (0, 0), (0, 0), colors.HexColor('#eff6ff')),
            ('PADDING', (0, 0), (-1, -1), 6),
            ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
        ]))
        story.append(amount_t)
        story.append(Spacer(1, 0.4 * cm))

        # المفروشات / الميزات
        if (template.features_text or '').strip():
            story.append(Paragraph(shape('المفروشات والأجهزة المشمولة'), section_h))
            features = []
            for line in template.features_text.split('\n'):
                line = line.strip()
                if line:
                    features.append(Paragraph(shape(f'• {line}'), body))
            
            if features:
                feat_t = Table([[f] for f in features], colWidths=['100%'])
                feat_t.setStyle(TableStyle([
                    ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
                    ('PADDING', (0, 0), (-1, -1), 6),
                    ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
                ]))
                story.append(feat_t)
                story.append(Spacer(1, 0.4 * cm))

        # الشروط
        if (template.terms_text or '').strip():
            story.append(Paragraph(shape('الشروط المتفق عليها'), section_h))
            terms = []
            for line in template.terms_text.split('\n'):
                line = line.strip()
                if line:
                    terms.append(Paragraph(shape(line), body))
            
            if terms:
                term_t = Table([[t] for t in terms], colWidths=['100%'])
                term_t.setStyle(TableStyle([
                    ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
                    ('PADDING', (0, 0), (-1, -1), 6),
                    ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
                ]))
                story.append(term_t)

        # التوقيع
        story.append(Spacer(1, 0.8 * cm))
        if contract.status == 'signed' and contract.signed_at:
            sig_text = f"تم التوقيع إلكترونياً بواسطة العميل\nIP: {contract.signature_ip or '-'}\nالوقت: {contract.signed_at.strftime('%Y/%m/%d %H:%M')}"
            sig_p = Paragraph(shape(sig_text), small)
        else:
            sig_p = Paragraph(shape('بانتظار توقيع العميل إلكترونياً...'), body)
            
        sig_data = [
            [
                Paragraph(shape('توقيع الطرف الثاني (المستأجر):'), body),
                Paragraph(shape('توقيع الطرف الأول (المؤجر):'), body)
            ],
            [
                Paragraph(shape(f"الاسم: {fv.get('full_name') or contract.customer_name or '-'}"), body),
                Paragraph(shape(f"الاسم: {template.lessor_name or tenant.business_name or '-'}"), body)
            ],
            [
                sig_p,
                Paragraph(shape('التوقيع: ____________________'), body)
            ]
        ]
        sig_t = Table(sig_data, colWidths=['50%', '50%'])
        sig_t.setStyle(TableStyle([
            ('PADDING', (0, 0), (-1, -1), 6),
            ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
        ]))
        story.append(sig_t)

        # تذييل
        story.append(Spacer(1, 0.6 * cm))
        story.append(HRFlowable(width='100%', thickness=0.5, color=colors.HexColor('#cbd5e1')))
        story.append(Spacer(1, 0.2 * cm))
        story.append(Paragraph(
            shape('هذا العقد إلكتروني، وُلّد ووقّع رقمياً عبر منصة ' + (tenant.business_name or '')),
            small,
        ))

        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=A4,
            rightMargin=2 * cm, leftMargin=2 * cm,
            topMargin=1.5 * cm, bottomMargin=1.5 * cm,
            title=f'Contract {contract.contract_number or ""}',
        )
        doc.build(story)
        return buf.getvalue()

    @staticmethod
    def _logo_flowable(tenant):
        """يحضّر صورة شعار التاجر للـ PDF (لو موجود)."""
        try:
            from reportlab.platypus import Image
            from reportlab.lib.units import cm
            from flask import current_app

            path = (tenant.logo_path or '').strip()
            if not path:
                return None

            if path.startswith('http://') or path.startswith('https://'):
                # نزّل مؤقتاً
                resp = requests.get(path, timeout=8)
                if resp.status_code != 200:
                    return None
                buf = io.BytesIO(resp.content)
                img = Image(buf, width=3 * cm, height=3 * cm, kind='proportional')
                img.hAlign = 'CENTER'
                return img

            base = current_app.config.get('BASE_DIR')
            local = base / path.lstrip('/')
            if not local.exists():
                return None
            img = Image(str(local), width=3 * cm, height=3 * cm, kind='proportional')
            img.hAlign = 'CENTER'
            return img
        except Exception:
            return None

    @staticmethod
    def _default_pdf_text(contract: Contract, template: ContractTemplate) -> str:
        """نص افتراضي للعقد لو ما حدد التاجر قالب."""
        return """عقد إيجار / خدمة

رقم العقد: {contract_number}
التاريخ: {date}

اسم المنشأة: {tenant_name}
اسم العميل: {full_name}
رقم الهوية: {id_number}
رقم الجوال: {phone}

تاريخ الوصول: {check_in_date}
المدة: {duration} شهر

المبلغ المدفوع: {amount} ر.س

----
هذا العقد إلكتروني وموقّع رقمياً.
""".strip()

    # خطوط محتملة تدعم العربي (نبحث عنها بالترتيب)
    _ARABIC_FONT_PATHS = [
        # Windows
        'C:/Windows/Fonts/arial.ttf',
        'C:/Windows/Fonts/tahoma.ttf',
        'C:/Windows/Fonts/segoeui.ttf',
        # Linux
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
        '/usr/share/fonts/TTF/DejaVuSans.ttf',
        # macOS
        '/Library/Fonts/Arial.ttf',
        '/System/Library/Fonts/Supplemental/Arial.ttf',
    ]

    _arabic_font_registered = None  # cache: اسم الخط أو False

    @classmethod
    def _ensure_arabic_font(cls) -> Optional[str]:
        """تسجيل خط يدعم العربي مع reportlab مرة واحدة. يرجع اسم الخط أو None."""
        if cls._arabic_font_registered is not None:
            return cls._arabic_font_registered or None

        try:
            import os
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont

            # خط مخصّص في static/fonts/ (لو التاجر رفع Amiri مثلاً)
            from flask import current_app
            try:
                custom = current_app.config.get('BASE_DIR') / 'static' / 'fonts' / 'Amiri-Regular.ttf'
                if custom.exists():
                    pdfmetrics.registerFont(TTFont('AppArabic', str(custom)))
                    cls._arabic_font_registered = 'AppArabic'
                    return 'AppArabic'
            except Exception:
                pass

            for path in cls._ARABIC_FONT_PATHS:
                if os.path.exists(path):
                    pdfmetrics.registerFont(TTFont('AppArabic', path))
                    cls._arabic_font_registered = 'AppArabic'
                    return 'AppArabic'
        except Exception as e:
            current_app.logger.warning(f'[ContractService] Arabic font registration failed: {e}')

        cls._arabic_font_registered = False
        return None

    @staticmethod
    def _shape_arabic(text: str) -> str:
        """إعادة تشكيل النص العربي + اتجاه RTL ليطبع صحيح في PDF."""
        try:
            import arabic_reshaper
            from bidi.algorithm import get_display
            reshaped = arabic_reshaper.reshape(text)
            return get_display(reshaped)
        except Exception:
            return text

    @staticmethod
    def _text_to_pdf(text: str) -> bytes:
        """تحويل نص لـ PDF مع دعم العربي."""
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.enums import TA_RIGHT
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
            from reportlab.lib.units import cm
        except ImportError:
            current_app.logger.error('[ContractService] reportlab غير مثبّت — أضف للـ requirements')
            raise RuntimeError('reportlab غير متوفر — لا يمكن توليد PDF')

        font_name = ContractService._ensure_arabic_font()
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=2*cm, leftMargin=2*cm,
                                topMargin=2*cm, bottomMargin=2*cm)

        styles = getSampleStyleSheet()
        if font_name:
            arabic_style = ParagraphStyle(
                'Arabic', parent=styles['Normal'],
                fontName=font_name, fontSize=12, leading=18,
                alignment=TA_RIGHT, wordWrap='RTL',
            )
        else:
            # fallback بدون خط عربي — قد لا يظهر العربي صحيح
            arabic_style = ParagraphStyle(
                'Arabic', parent=styles['Normal'],
                fontSize=12, leading=18, alignment=TA_RIGHT,
            )

        story = []
        for line in text.split('\n'):
            if line.strip():
                shaped = ContractService._shape_arabic(line) if font_name else line
                # هروب رموز XML قبل Paragraph
                shaped = shaped.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                story.append(Paragraph(shaped, arabic_style))
            else:
                story.append(Spacer(1, 0.3 * cm))
        doc.build(story)
        return buf.getvalue()

    @staticmethod
    def _generate_via_api(contract: Contract, template: ContractTemplate) -> Dict:
        """إرسال للـ API الخارجي للتاجر."""
        url = template.external_api_url
        if not url:
            return {'success': False, 'error': 'API URL غير مضبوط'}

        headers = template.external_api_headers or {}
        headers.setdefault('Content-Type', 'application/json')
        if template.external_api_auth:
            headers.setdefault('Authorization', template.external_api_auth)

        payload = {
            'contract_number': contract.contract_number,
            'tenant_id': contract.tenant_id,
            'customer_name': contract.customer_name,
            'customer_phone': contract.customer_phone,
            'customer_id': contract.customer_id_number,
            'customer_email': contract.customer_email,
            'amount': float(contract.payment_amount or 0),
            'paid': float(contract.payment_paid or 0),
            'fields': contract.field_values or {},
            'created_at': contract.created_at.isoformat() if contract.created_at else None,
        }

        try:
            method = (template.external_api_method or 'POST').upper()
            resp = requests.request(method, url, json=payload, headers=headers, timeout=30)

            if resp.status_code in (200, 201):
                data = resp.json() if resp.headers.get('content-type', '').startswith('application/json') else {}
                contract.external_contract_id = str(data.get('contract_id', '') or data.get('id', ''))
                contract.external_contract_url = data.get('contract_url', '') or data.get('url', '')
                contract.status = 'signed'
                contract.signed_at = datetime.utcnow()
                return {'success': True, 'url': contract.external_contract_url}
            else:
                return {'success': False, 'error': f'HTTP {resp.status_code}: {resp.text[:200]}'}

        except Exception as e:
            current_app.logger.exception(f'[ContractService] external API error: {e}')
            return {'success': False, 'error': str(e)[:200]}

    @staticmethod
    def send_to_customer(contract: Contract):
        """إرسال العقد للعميل."""
        template = contract.template
        if not template:
            return False

        url = contract.contract_pdf_url or contract.external_contract_url
        if not url:
            return False

        from flask import request, url_for
        try:
            base_url = request.host_url.rstrip('/')
        except RuntimeError:
            base_url = current_app.config.get('BASE_URL', 'https://kognitixai.com').rstrip('/')

        # تحويل المسار النسبي لمطلق
        if url.startswith('/'):
            absolute_pdf_url = base_url + url
        else:
            absolute_pdf_url = url

        if contract.status == 'pending_signature':
            try:
                action_url = base_url + url_for('public.sign_contract', token=contract.signature_token)
            except RuntimeError:
                action_url = f"{base_url}/contract/sign/{contract.signature_token}"
            action_text = "✍️ اقرأ ووقّع العقد إلكترونياً"
            email_title = "عقدك جاهز للتوقيع ✍️"
            email_msg = "تم إعداد العقد، يرجى مراجعته وتوقيعه إلكترونياً واعتماده."
            whatsapp_msg = f'عقدك رقم {contract.contract_number} جاهز. يرجى الضغط على الرابط التالي لقراءته وتوقيعه:\n{action_url}'
            send_as_document = False
        else:
            action_url = absolute_pdf_url
            action_text = "📄 تحميل العقد"
            email_title = "تم الانتهاء من عقدك ✅"
            email_msg = "تم توقيع واعتماد العقد بنجاح. يمكنك تحميل نسختك من الرابط أدناه."
            whatsapp_msg = f'عقدك رقم {contract.contract_number} المعتمد جاهز.'
            send_as_document = True

        sent = False

        # Email — يُرسل افتراضياً إذا توفر البريد
        if contract.customer_email:
            try:
                from app.services.email_service import EmailService
                EmailService._send(
                    to=contract.customer_email,
                    subject=f'عقدك — {contract.contract_number}',
                    body_html=f'''
                    <div dir="rtl" style="font-family:Tahoma,Arial;padding:20px;">
                      <h2>{email_title}</h2>
                      <p>عزيزي {contract.customer_name},</p>
                      <p>{email_msg}</p>
                      <p>رقم العقد: <strong>{contract.contract_number}</strong></p>
                      <br/>
                      <p><a href="{action_url}" style="background:#2563eb;color:#fff;padding:12px 24px;text-decoration:none;border-radius:8px;display:inline-block;margin-top:10px;">{action_text}</a></p>
                    </div>
                    ''',
                )
                sent = True
            except Exception as e:
                current_app.logger.warning(f'[ContractService] email send error: {e}')

        # WhatsApp — يُرسل افتراضياً إذا توفر الجوال
        if contract.customer_phone:
            try:
                from app.services.whatsapp_service import WhatsAppService
                if send_as_document:
                    WhatsAppService.send_document(
                        tenant_id=contract.tenant_id,
                        to_phone=contract.customer_phone,
                        doc_url=absolute_pdf_url,
                        filename=f'contract_{contract.contract_number}.pdf',
                        caption=whatsapp_msg,
                    )
                else:
                    WhatsAppService.send_text(
                        tenant_id=contract.tenant_id,
                        to_phone=contract.customer_phone,
                        text=whatsapp_msg,
                    )
                sent = True
            except Exception as e:
                current_app.logger.warning(f'[ContractService] whatsapp send error: {e}')

        if sent:
            contract.status = 'sent'
            contract.sent_at = datetime.utcnow()

        return sent

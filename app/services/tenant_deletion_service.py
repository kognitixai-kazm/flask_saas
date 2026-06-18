"""
حذف المستأجر وجميع البيانات المرتبطة (بما فيها ما لا يُحذف تلقائياً عبر علاقات Tenant).
"""
from __future__ import annotations

from datetime import datetime, timedelta

import hmac
import hashlib
import secrets
from pathlib import Path

from flask import current_app

from app.extensions import db
from app.models.audit_log import AuditLog
from app.models.chat_visitor import ChatVisitor
from app.models.hotel_models import HotelService
from app.models.restaurant_models import MenuCategory, RestaurantService
from app.models.tenant import Tenant
from app.models.tenant_deletion_code import TenantDeletionCode


def _hash_deletion_code(code: str) -> str:
    secret = (current_app.config.get('SECRET_KEY') or '').encode()
    return hmac.new(secret, code.strip().encode('utf-8'), hashlib.sha256).hexdigest()


def _normalize_digit_code(raw: str) -> str:
    """يوحّد الرمز المرسل إلى ٦ خانات بالأرقام اللاتينية (٠١٢ → 012 ...) ليقبل الواجهات العربية."""
    s = (raw or '').strip().replace(' ', '').replace('\u00a0', '').replace('\u200f', '')
    s = s.translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))
    s = s.translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789'))
    return s


class TenantDeletionService:
    """إصدار رموز الحذف + تنظيف الجداول قبل حذف صف المستأجر."""

    CODE_TTL_MINUTES = 15
    MAX_SENDS_PER_HOUR = 5

    @staticmethod
    def purge_rows_for_tenant(tenant_id: int) -> None:
        """حذف صريح ومرتّب لكل الصفوف المرتبطة قبل حذف المستأجر.
        الترتيب مهم: الجداول التي تعتمد على جداول أخرى تُحذف أولاً.
        """
        from app.models.booking import Booking
        from app.models.conversation import Message
        from app.models.hotel_models import Floor, Unit
        from app.models.message_usage import MessageUsage
        from app.models.contract import Contract
        from app.models.inquiry import Inquiry
        from app.models.tenant_wallet import WalletTopUp, TenantWallet

        # المرحلة 1 — حذف الحجوزات أولاً (لها FK على conversations و hotel_units)
        Booking.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)

        # المرحلة 2 — حذف كل ما يعتمد على conversations.id
        Contract.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
        Inquiry.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
        MessageUsage.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
        Message.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)

        # المرحلة 3 — حذف الوحدات الفندقية قبل الطوابق (Unit.floor_id → Floor.id)
        Unit.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
        Floor.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)

        # المرحلة 4 — بقية الجداول المباشرة
        WalletTopUp.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
        TenantWallet.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
        AuditLog.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
        TenantDeletionCode.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
        ChatVisitor.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
        HotelService.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
        RestaurantService.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
        for cat in MenuCategory.query.filter_by(tenant_id=tenant_id).all():
            db.session.delete(cat)

        # فرض تنفيذ كل الحذوفات في قاعدة البيانات قبل حذف المستأجر نفسه
        db.session.flush()

    @staticmethod
    def delete_tenant_object(tenant: Tenant) -> None:
        """يُفترض أنّ session ما زالت تحمل كائن tenant بعد التحقق من الهوية."""
        tid = tenant.id
        TenantDeletionService.purge_rows_for_tenant(tid)
        logo = (tenant.logo_path or '').strip()
        if logo and not logo.startswith(('http://', 'https://')):
            try:
                logo_full = Path(current_app.static_folder) / logo.replace('/static/', '')
                if logo_full.is_file():
                    logo_full.unlink()
            except OSError:
                pass
        db.session.delete(tenant)

    @staticmethod
    def count_recent_code_sends(tenant_id: int) -> int:
        since = datetime.utcnow() - timedelta(hours=1)
        return TenantDeletionCode.query.filter(
            TenantDeletionCode.tenant_id == tenant_id,
            TenantDeletionCode.created_at >= since,
        ).count()

    @staticmethod
    def issue_email_code(tenant_id: int) -> str:
        """يولّد رمزاً جديداً، يخزّن الهاش، ويعيد الرمز الصريح لإرساله بالبريد فقط."""
        code = ''.join(str(secrets.randbelow(10)) for _ in range(6))
        ch = _hash_deletion_code(code)
        expires = datetime.utcnow() + timedelta(minutes=TenantDeletionService.CODE_TTL_MINUTES)
        row = TenantDeletionCode(
            tenant_id=tenant_id,
            code_hash=ch,
            expires_at=expires,
        )
        db.session.add(row)
        db.session.commit()
        return code

    @staticmethod
    def verify_latest_code(tenant_id: int, code_plain: str) -> bool:
        code_plain = _normalize_digit_code(code_plain)
        if not code_plain or len(code_plain) != 6 or not code_plain.isdigit():
            return False
        row = (
            TenantDeletionCode.query.filter_by(tenant_id=tenant_id)
            .order_by(TenantDeletionCode.created_at.desc())
            .first()
        )
        if not row or row.expires_at < datetime.utcnow():
            return False
        want = _hash_deletion_code(code_plain)
        return hmac.compare_digest(row.code_hash, want)

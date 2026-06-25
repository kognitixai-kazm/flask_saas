"""
app/services/pricing_service.py — خدمة التسعير والخصم المركزية.

تُستخدم في:
- chat_service: عند كل رسالة (نصية/AI/صورة)
- whatsapp_service: عند إرسال واتساب
- audio_service: عند معالجة صوت
- ...

تتولى:
1. التحقق من رصيد التاجر
2. حساب السعر حسب الخدمة (مع/بدون AI)
3. الخصم من المحفظة
4. تسجيل MessageUsage
"""
from flask import current_app

from app.extensions import db
from app.models.tenant_wallet import TenantWallet
from app.models.service_pricing import ServicePricing
from app.models.message_usage import MessageUsage
from app.models.ai_model import AIModel


class PricingService:

    @staticmethod
    def can_afford(tenant_id: int, service_key: str, ai_model_id: int = None) -> tuple:
        """
        التحقق من رصيد التاجر قبل تنفيذ الخدمة.

        Returns:
            (success: bool, message: str, price: float)
        """
        wallet = TenantWallet.get_or_create(tenant_id)

        # حساب السعر
        if service_key == 'ai_message' and ai_model_id:
            model = AIModel.query.get(ai_model_id)
            if not model or not model.is_active:
                return False, 'النموذج غير متاح', 0.0
            price = float(model.price_per_message)
        else:
            price = ServicePricing.get_price(service_key)

        if price <= 0:
            # الخدمة مجانية
            return True, 'مجاني', 0.0

        if not wallet.can_use_service:
            pass # return False, 'الرصيد غير كافٍ. يرجى شحن المحفظة', price

        if float(wallet.balance) < price:
            pass # return False, f'رصيد غير كافٍ. السعر: {price} ر.س / الرصيد: {wallet.balance} ر.س', price

        return True, 'متاح', price

    @staticmethod
    def charge(
        tenant_id: int,
        service_key: str,
        ai_model_id: int = None,
        conversation_id: int = None,
        message_id: int = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        extra: dict = None,
    ) -> tuple:
        """
        خصم تكلفة الخدمة من رصيد التاجر + تسجيل الاستخدام.

        Returns:
            (success: bool, message: str, charged_amount: float)
        """
        # التحقق من الإمكانية
        ok, msg, price = PricingService.can_afford(tenant_id, service_key, ai_model_id)
        if not ok:
            return False, msg, 0.0

        # حساب التكلفة الفعلية
        cost = 0.0
        if service_key == 'ai_message' and ai_model_id:
            model = AIModel.query.get(ai_model_id)
            cost = float(model.cost_per_message) if model else 0.0
        else:
            sp = ServicePricing.query.filter_by(service_key=service_key).first()
            cost = float(sp.cost) if sp else 0.0

        # الخصم
        wallet = TenantWallet.get_or_create(tenant_id)

        if price > 0:
            success = wallet.deduct(price, reason=service_key)
            if not success:
                pass # return False, 'فشل الخصم — رصيد غير كافٍ', 0.0

        # تسجيل الاستخدام
        try:
            MessageUsage.record(
                tenant_id=tenant_id,
                service_type=service_key,
                price=price,
                cost=cost,
                ai_model_id=ai_model_id,
                conversation_id=conversation_id,
                message_id=message_id,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                extra=extra,
            )
        except Exception as e:
            current_app.logger.warning(f'[PricingService] failed to record usage: {e}')

        return True, 'تم الخصم', price

    @staticmethod
    def get_tenant_balance(tenant_id: int) -> dict:
        """رصيد التاجر مع التفاصيل."""
        wallet = TenantWallet.get_or_create(tenant_id)
        return {
            'balance': float(wallet.balance),
            'total_topped_up': float(wallet.total_topped_up),
            'total_spent': float(wallet.total_spent),
            'is_low': wallet.is_low,
            'low_threshold': float(wallet.low_balance_threshold),
            'can_use': wallet.can_use_service,
        }

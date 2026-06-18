"""
app/utils/slug.py — توليد slug عشوائي غير قابل للتخمين
"""
from nanoid import generate


# alphabet بدون حروف مشابهة (0, O, l, I) ليسهل قراءته ومشاركته
SAFE_ALPHABET = '23456789abcdefghjkmnpqrstuvwxyz'


def generate_tenant_slug(length: int = 10) -> str:
    """
    توليد slug قصير عشوائي للمستأجر.
    مثال: "k7m3x9np2q"
    قابل للمشاركة، غير قابل للتخمين.
    """
    return generate(SAFE_ALPHABET, length)


def generate_visitor_id(length: int = 24) -> str:
    """توليد معرف زائر عشوائي."""
    return generate(size=length)

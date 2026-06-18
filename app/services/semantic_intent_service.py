"""
طبقة نوايا دلالية معطّلة — لا تحميل نماذج محلية (sentence-transformers).
الكشف يبقى عبر الكلمات والقواعد في IntentEngine ثم الذكاء الخارجي.
"""
from typing import Optional, Tuple


def classify_semantic(text: str, activity_code: str) -> Tuple[Optional[str], float]:
    """لا يُنفَّذ أي تضمين جملي؛ يعيد فوراً دون حظر."""
    return None, 0.0


def semantic_layer_available() -> bool:
    return False

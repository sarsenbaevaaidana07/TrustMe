"""
utils.py — вспомогательные утилиты.
Fix: безопасный парсинг float (было: float(analysis.get("confidence", 0))
     падало на "0.8 (medium)" и подобных строках).
"""

import re


def safe_float(value, default: float = 0.0, lo: float = 0.0, hi: float = 1.0) -> float:
    """
    Извлекает float из значения любого типа.

    Обрабатывает:
      0.8          → 0.8
      "0.8"        → 0.8
      "0.8 (medium)" → 0.8   ← был баг
      "high"       → default
      None         → default

    Параметры lo/hi — опциональный clamp (по умолчанию [0.0, 1.0] для confidence).
    """
    if isinstance(value, (int, float)):
        return max(lo, min(hi, float(value)))

    if isinstance(value, str):
        # Берём первое число (целое или дробное) из строки
        match = re.search(r"[-+]?\d+(?:\.\d+)?", value)
        if match:
            return max(lo, min(hi, float(match.group())))

    return default


def safe_int(value, default: int = 0, lo: int = 0, hi: int = 10) -> int:
    """
    Аналог safe_float для целых чисел.
    Используется для revenue_at_risk, reach_score и т.д.
    """
    result = safe_float(value, default=float(default), lo=float(lo), hi=float(hi))
    return int(result)

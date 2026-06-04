"""
scorer.py — скоринг и приоритизация запросов по методологии RICE.
Fix: safe_float вместо float() для confidence и revenue_at_risk
     (было: строки 27, 56-57 падали на "0.8 (medium)" и подобных).
"""

import json
from llm_adapter import LLMAdapter
from utils import safe_float, safe_int
from prompts import SCORING_PROMPT  # текст из scoring.txt


class Scorer:
    def __init__(self, llm: LLMAdapter, product_strategy: str):
        self.llm = llm
        self.product_strategy = product_strategy

    async def score(self, analysis: dict) -> dict:
        """
        Отправляет extraction-JSON в LLM для скоринга.
        Возвращает scoring-JSON с priority и justification.
        """
        prompt = SCORING_PROMPT.format(
            PRODUCT_STRATEGY=self.product_strategy,
            ANALYSIS_JSON=json.dumps(analysis, ensure_ascii=False, indent=2),
        )
        raw = await self.llm.complete(prompt)

        try:
            result = json.loads(raw.strip())
        except json.JSONDecodeError:
            # Fallback: если модель добавила markdown-обёртку
            import re
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            result = json.loads(match.group()) if match else {}

        return self._sanitize(result)

    def _sanitize(self, result: dict) -> dict:
        """
        Нормализует поля из scoring-ответа.

        БЫЛО (строки 27, 56-57):
            confidence = float(analysis.get("confidence", 0))
            revenue_at_risk = float(analysis.get("revenue_at_risk", 0))
            # ❌ падало если LLM вернул "0.8 (medium)" или "7 (high)"

        СТАЛО: safe_float / safe_int через utils.py
        """
        return {
            "reach_score":        safe_int(result.get("reach_score"), lo=0, hi=10),
            "impact_score":       safe_int(result.get("impact_score"), lo=0, hi=10),
            # confidence — дробное [0.0, 1.0]
            "confidence_score":   safe_float(result.get("confidence_score"), lo=0.0, hi=1.0),
            "strategy_fit_score": safe_int(result.get("strategy_fit_score"), lo=0, hi=10),
            "base_score":         safe_float(result.get("base_score"), lo=0, hi=9999),
            "bonus":              safe_int(result.get("bonus"), lo=0, hi=999),
            "bonus_reason":       str(result.get("bonus_reason") or ""),
            "total_score":        safe_float(result.get("total_score"), lo=0, hi=9999),
            "priority":           _validated_priority(result.get("priority")),
            "justification":      str(result.get("justification") or ""),
        }


def _validated_priority(value) -> str:
    allowed = {"Low", "Medium", "High", "Highest"}
    if value in allowed:
        return value
    return "Low"

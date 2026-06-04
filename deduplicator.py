"""
deduplicator.py — семантическая дедупликация продуктовых запросов.
Fix: батч-запрос вместо 50 последовательных вызовов (было: строки 18-25).
"""

import asyncio
import json
from typing import Optional
from llm_adapter import LLMAdapter
from prompts import DEDUP_PROMPT  # текст из dedup.txt


class Deduplicator:
    def __init__(self, llm: LLMAdapter):
        self.llm = llm

    # ──────────────────────────────────────────────────────────────────
    # БЫЛО (50 последовательных запросов):
    #
    # async def check_duplicate(self, new_problem, candidates):
    #     for candidate in candidates:
    #         prompt = DEDUP_PROMPT.format(
    #             PROBLEM_A=new_problem, PROBLEM_B=candidate["summary"]
    #         )
    #         result = await self.llm.complete(prompt)
    #         if result.strip() == "DUPLICATE":
    #             return candidate
    #     return None
    #
    # ──────────────────────────────────────────────────────────────────
    # СТАЛО: один батч-запрос на все кандидаты сразу
    # ──────────────────────────────────────────────────────────────────

    async def check_duplicate(
        self, new_problem: str, candidates: list[dict]
    ) -> Optional[dict]:
        """
        Проверяет новый запрос против списка кандидатов.
        Вместо N последовательных вызовов отправляет один батч-промпт,
        который просит модель проанализировать все кандидаты разом
        и вернуть JSON с индексом совпадения (или -1 если дублей нет).
        """
        if not candidates:
            return None

        # Если один кандидат — всё ещё выгоднее одного запроса, но без overhead
        # нумерованного батча. Оставляем тот же путь для единообразия.
        numbered = "\n\n".join(
            f"[{i}] {c['summary']}" for i, c in enumerate(candidates)
        )

        batch_prompt = f"""
Ты — система семантической дедупликации. Ниже — новый запрос и список
существующих тикетов. Применяй критерии из своих инструкций к каждому тикету.

НОВЫЙ ЗАПРОС:
{new_problem}

СУЩЕСТВУЮЩИЕ ТИКЕТЫ (пронумерованы):
{numbered}

Верни ТОЛЬКО валидный JSON без markdown:
{{
  "duplicate_index": <номер тикета-дубликата или -1 если дублей нет>,
  "reason": "<одна фраза — почему это дубликат, или пустая строка>"
}}
""".strip()

        raw = await self.llm.complete(batch_prompt)

        try:
            result = json.loads(raw.strip())
            idx = int(result.get("duplicate_index", -1))
            if 0 <= idx < len(candidates):
                return candidates[idx]
        except (json.JSONDecodeError, ValueError, TypeError):
            # Если модель вернула мусор — не блокируем создание тикета,
            # лучше создать лишний, чем потерять запрос клиента.
            pass

        return None

    # ──────────────────────────────────────────────────────────────────
    # Альтернатива: параллельные запросы через asyncio.gather
    # Используй если батч-промпт даёт слабую точность на большом списке.
    # ──────────────────────────────────────────────────────────────────

    async def check_duplicate_parallel(
        self, new_problem: str, candidates: list[dict]
    ) -> Optional[dict]:
        """
        Параллельная версия: N запросов одновременно через gather.
        Быстрее последовательного варианта, но дороже батча по токенам.
        Оставлена как запасной вариант.
        """
        if not candidates:
            return None

        async def _check_one(candidate: dict) -> Optional[dict]:
            prompt = DEDUP_PROMPT.format(
                PROBLEM_A=new_problem,
                PROBLEM_B=candidate["summary"],
            )
            result = await self.llm.complete(prompt)
            return candidate if result.strip() == "DUPLICATE" else None

        results = await asyncio.gather(*(_check_one(c) for c in candidates))
        return next((r for r in results if r is not None), None)

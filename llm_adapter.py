"""
llm_adapter.py — адаптер для LLM API.
Fix: убрана проверка длины ключей метаданных (строки 328-332),
     которая сливала имена внутренних полей в логи/ошибки.
"""

import httpx
import json
from typing import Optional


class LLMAdapter:
    def __init__(self, api_key: str, model: str = "gpt-4o", timeout: float = 30.0):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    def build_metadata(self, raw: dict) -> dict:
        """
        Нормализует метаданные перед сохранением/логированием.

        БЫЛО (строки 328-332):
            for key in metadata:
                if len(key) > 32:                    # ← слив имён ключей
                    raise ValueError(
                        f"Metadata key too long: '{key}' ({len(key)} chars)"
                    )

        Проблема: при ошибке ValueError сообщение содержало имя ключа —
        это метаданные внутренней структуры, которые не должны попадать
        в пользовательские ошибки или внешние логи.

        СТАЛО: молча усекаем длинные ключи, не раскрываем их имена.
        """
        MAX_KEY_LEN = 32
        MAX_VAL_LEN = 512

        sanitized = {}
        for key, value in raw.items():
            safe_key = key[:MAX_KEY_LEN] if len(key) > MAX_KEY_LEN else key
            # Значения тоже усекаем — строковые поля не должны быть безлимитными
            if isinstance(value, str) and len(value) > MAX_VAL_LEN:
                value = value[:MAX_VAL_LEN]
            sanitized[safe_key] = value

        return sanitized

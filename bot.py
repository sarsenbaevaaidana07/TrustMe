"""
bot.py — Telegram-бот TeamTrustGate.

Исправления:
  Fix 4 (строки 136, 170): safe_float для confidence вместо float()
  Fix 5 (строка 136):      Markdown parse_mode через Defaults
  Fix 6 (строка 285):      concurrent_updates=True для параллельной обработки
"""

import os
import json
import logging

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    Defaults,
)
from telegram.constants import ParseMode

from llm_adapter import LLMAdapter
from scorer import Scorer
from deduplicator import Deduplicator
from jira_client import JiraClient
from utils import safe_float
from prompts import EXTRACTION_PROMPT

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────
# Зависимости (инициализируются один раз при старте)
# ──────────────────────────────────────────────────────────────────

llm = LLMAdapter(api_key=os.environ["OPENAI_API_KEY"])
jira = JiraClient(
    base_url=os.environ["JIRA_BASE_URL"],
    token=os.environ["JIRA_TOKEN"],
)
scorer = Scorer(llm, product_strategy=os.environ.get("PRODUCT_STRATEGY", ""))
deduplicator = Deduplicator(llm)


# ──────────────────────────────────────────────────────────────────
# Handlers
# ──────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "*TeamTrustGate* готов к работе\\.\n"
        "Опишите запрос клиента — я создам тикет в Jira\\.",
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_text = update.message.text
    chat_id = update.effective_chat.id

    # 1. Extraction
    extraction_prompt = EXTRACTION_PROMPT.format(
        USER_MESSAGE=user_text,
        COLLECTED_ANSWERS=context.user_data.get("collected_answers", ""),
        PRODUCT_STRATEGY=os.environ.get("PRODUCT_STRATEGY", ""),
    )
    raw_analysis = await llm.complete(extraction_prompt)

    try:
        analysis = json.loads(raw_analysis.strip())
    except json.JSONDecodeError:
        await update.message.reply_text("❌ Не смог разобрать ответ модели. Попробуйте ещё раз.")
        return

    # Отклонение
    if analysis.get("should_reject"):
        await update.message.reply_text(
            f"ℹ️ {analysis.get('reject_reason', 'Запрос отклонён.')}"
        )
        return

    # Уточняющий вопрос
    if analysis.get("missing_info"):
        question = analysis["missing_info"][0]
        context.user_data["collected_answers"] = user_text
        await update.message.reply_text(f"🔍 {question}")
        return

    context.user_data.pop("collected_answers", None)

    # ──────────────────────────────────────────────────────────────
    # БЫЛО (строка 136):
    #   confidence = float(analysis.get("confidence", 0))
    #   # ❌ падало если модель вернула "0.75 (high)" и т.п.
    #
    # СТАЛО:
    # ──────────────────────────────────────────────────────────────
    confidence = safe_float(analysis.get("confidence"), default=0.0)

    # 2. Дедупликация
    candidates = await jira.search_issues(
        jql='project = TTG AND status != Done ORDER BY created DESC',
        max_results=50,
    )
    candidate_summaries = [
        {"id": c["id"], "key": c["key"], "summary": c["fields"].get("summary", "")}
        for c in candidates
    ]
    duplicate = await deduplicator.check_duplicate(
        analysis["problem_statement"], candidate_summaries
    )

    if duplicate:
        await update.message.reply_text(
            f"🔁 Похожий тикет уже существует: *{duplicate['key']}*\n"
            f"`{duplicate['summary']}`"
        )
        return

    # 3. Скоринг
    scoring = await scorer.score(analysis)

    # ──────────────────────────────────────────────────────────────
    # БЫЛО (строка 170):
    #   confidence = float(analysis.get("confidence", 0))  # дублировалось
    # СТАЛО: переиспользуем уже вычисленный safe_float выше
    # ──────────────────────────────────────────────────────────────

    # 4. Создание тикета
    priority_map = {
        "Highest": "Highest",
        "High": "High",
        "Medium": "Medium",
        "Low": "Low",
    }
    jira_payload = {
        "fields": {
            "project": {"key": "TTG"},
            "summary": analysis["problem_statement"][:200],
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {
                                "type": "text",
                                "text": scoring["justification"],
                            }
                        ],
                    }
                ],
            },
            "issuetype": {"name": "Story"},
            "priority": {"name": priority_map.get(scoring["priority"], "Medium")},
            "labels": [analysis.get("request_type", "unknown")],
        }
    }

    try:
        issue = await jira.create_issue(jira_payload)
    except RuntimeError as e:
        await update.message.reply_text(f"❌ Ошибка создания тикета: {e}")
        return

    issue_key = issue.get("key", "???")
    await update.message.reply_text(
        f"✅ Тикет создан: *{issue_key}*\n"
        f"Приоритет: *{scoring['priority']}* \\(score: {scoring['total_score']:.0f}\\)\n"
        f"\n_{scoring['justification']}_"
    )


# ──────────────────────────────────────────────────────────────────
# Точка входа
# ──────────────────────────────────────────────────────────────────

def main() -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]

    # Fix 4: Markdown рендерится через Defaults — не нужно указывать
    #        parse_mode в каждом reply_text вручную.
    # БЫЛО:  Application.builder().token(token).build()
    # СТАЛО:
    defaults = Defaults(parse_mode=ParseMode.MARKDOWN_V2)

    # Fix 6: concurrent_updates=True — апдейты обрабатываются параллельно.
    # БЫЛО:  Application.builder().token(token).build()
    #        (последовательная обработка по умолчанию)
    # СТАЛО:
    app = (
        Application.builder()
        .token(token)
        .defaults(defaults)
        .concurrent_updates(True)   # ← параллельная обработка
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot starting...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()

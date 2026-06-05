"""
bot.py — Telegram-бот TeamTrustGate.
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
# Читаем переменные — поддерживаем оба варианта названий
# ──────────────────────────────────────────────────────────────────

LLM_API_KEY = (
    os.environ.get("LLM_API_KEY")
    or os.environ.get("OPENAI_API_KEY")
    or ""
)
JIRA_BASE_URL = (
    os.environ.get("JIRA_BASE_URL")
    or os.environ.get("JIRA_URL")
    or ""
)
JIRA_TOKEN = (
    os.environ.get("JIRA_TOKEN")
    or os.environ.get("JIRA_API_TOKEN")
    or ""
)

if not LLM_API_KEY:
    raise RuntimeError("Нет LLM ключа: задайте LLM_API_KEY или OPENAI_API_KEY в Variables")
if not JIRA_BASE_URL:
    raise RuntimeError("Нет JIRA URL: задайте JIRA_BASE_URL или JIRA_URL в Variables")
if not JIRA_TOKEN:
    raise RuntimeError("Нет JIRA токена: задайте JIRA_TOKEN или JIRA_API_TOKEN в Variables")

llm = LLMAdapter(api_key=LLM_API_KEY)
jira = JiraClient(
    base_url=JIRA_BASE_URL,
    token=JIRA_TOKEN,
    email=os.environ.get("JIRA_EMAIL", ""),
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

    if analysis.get("should_reject"):
        await update.message.reply_text(
            f"ℹ️ {analysis.get('reject_reason', 'Запрос отклонён.')}"
        )
        return

    if analysis.get("missing_info"):
        question = analysis["missing_info"][0]
        context.user_data["collected_answers"] = user_text
        await update.message.reply_text(f"🔍 {question}")
        return

    context.user_data.pop("collected_answers", None)

    confidence = safe_float(analysis.get("confidence"), default=0.0)

    # 2. Дедупликация
    candidates = await jira.search_issues(
        jql='project = SCRUM AND status != Done ORDER BY created DESC',
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

    # 4. Создание тикета
    priority_map = {"Highest": "Highest", "High": "High", "Medium": "Medium", "Low": "Low"}
    jira_payload = {
        "fields": {
            "project": {"key": "SCRUM"},
            "summary": analysis["problem_statement"][:200],
            "description": {
                "type": "doc",
                "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": scoring["justification"]}]}],
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
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise RuntimeError("Нет TELEGRAM_BOT_TOKEN в Variables")

    defaults = Defaults(parse_mode=ParseMode.MARKDOWN_V2)
    app = (
        Application.builder()
        .token(token)
        .defaults(defaults)
        .concurrent_updates(True)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot starting...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()

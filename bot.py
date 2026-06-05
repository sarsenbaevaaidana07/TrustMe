"""
bot.py — Telegram-бот TeamTrustGate.
Түзетілген және қауіпсіздігі арттырылған нұсқасы.
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
# Читаем переменные
# ──────────────────────────────────────────────────────────────────

LLM_API_KEY = os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
JIRA_BASE_URL = os.environ.get("JIRA_BASE_URL") or os.environ.get("JIRA_URL") or ""
JIRA_TOKEN = os.environ.get("JIRA_TOKEN") or os.environ.get("JIRA_API_TOKEN") or ""
JIRA_PROJECT_KEY = os.environ.get("JIRA_PROJECT_KEY", "SCRUM") # Проект кілтін оқу

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
    # MARKDOWN_V2-де нүктелер мен сызықшалардың алдына \ қойылды
    await update.message.reply_text(
        "*TeamTrustGate* готов к работе\\.\n"
        "Опишите запрос клиента — я создам тикет в Jira\\.",
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_text = update.message.text
    logger.info(f"Получено сообщение: {user_text[:50]}...")

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
        # Қате кетсе қарапайым мәтінмен (HTML) жауап беру, бот үнсіз қалмайды
        await update.message.reply_text("❌ Не смог разобрать JSON от модели. Попробуйте еще раз.", parse_mode=ParseMode.HTML)
        return

    if analysis.get("should_reject"):
        await update.message.reply_text(f"ℹ️ {analysis.get('reject_reason', 'Запрос отклонён.')}", parse_mode=ParseMode.HTML)
        return

    if analysis.get("missing_info"):
        question = analysis["missing_info"][0]
        context.user_data["collected_answers"] = user_text
        await update.message.reply_text(f"🔍 {question}", parse_mode=ParseMode.HTML)
        return

    context.user_data.pop("collected_answers", None)

    # 2. Дедупликация
    try:
        jql_query = f'project = {JIRA_PROJECT_KEY} AND status != Done ORDER BY created DESC'
        candidates = await jira.search_issues(jql=jql_query, max_results=50)
        candidate_summaries = [
            {"id": c["id"], "key": c["key"], "summary": c["fields"].get("summary", "")}
            for c in candidates
        ]
        duplicate = await deduplicator.check_duplicate(analysis["problem_statement"], candidate_summaries)

        if duplicate:
            dup_key = duplicate['key']
            dup_sum = duplicate['summary']
            await update.message.reply_text(f"🔁 Похожий тикет уже существует: <b>{dup_key}</b>\n<code>{dup_sum}</code>", parse_mode=ParseMode.HTML)
            return
    except Exception as e:
        logger.error(f"Ошибка при дедупликации: {e}")
        # Егер дедупликация құласа, тоқтап қалмай әрі қарай кете береміз

    # 3. Скоринг
    scoring = await scorer.score(analysis)

    # 4. Создание тикета
    priority_map = {"Highest": "Highest", "High": "High", "Medium": "Medium", "Low": "Low"}
    
    # Қауіпсіз және қарапайым сипаттама мәтіні (String форматында)
    description_text = f"Justification:\n{scoring['justification']}\n\nProblem Statement:\n{analysis['problem_statement']}"

    jira_payload = {
        "fields": {
            "project": {"key": JIRA_PROJECT_KEY},
            "summary": analysis["problem_statement"][:200],
            "description": description_text, # Қарапайым форматқа ауыстырылды
            "issuetype": {"name": "Story"},
            "priority": {"name": priority_map.get(scoring["priority"], "Medium")},
            "labels": [analysis.get("request_type", "unknown")],
        }
    }

    try:
        issue = await jira.create_issue(jira_payload)
        issue_key = issue.get("key", "???")
        
        # Сәтті шыққан жауапты қатесіз HTML форматында жіберу
        success_text = (
            f"✅ <b>Тикет создан: {issue_key}</b>\n"
            f"Приоритет: <b>{scoring['priority']}</b> (score: {scoring['total_score']:.0f})\n\n"
            f"<i>{scoring['justification']}</i>"
        )
        await update.message.reply_text(success_text, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Ошибка создания тикета в Jira: {e}")
        # Егер қате кетсе, чатқа нақты не бүлінгенін анық көрсетеді
        await update.message.reply_text(f"❌ Ошибка создания тикета в Jira: <code>{str(e)[:150]}</code>", parse_mode=ParseMode.HTML)


# ──────────────────────────────────────────────────────────────────
# Точка входа
# ──────────────────────────────────────────────────────────────────

def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise RuntimeError("Нет TELEGRAM_BOT_TOKEN в Variables")

    # Баптауды қауіпсіз HTML режиміне ауыстырамыз, сонда бот бұзылмайды
    defaults = Defaults(parse_mode=ParseMode.HTML)
    app = (
        Application.builder()
        .token(token)
        .defaults(defaults)
        .concurrent_updates(True)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot starting with HTML parse mode...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()

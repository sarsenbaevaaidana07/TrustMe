# TeamTrustGate 🤖

Telegram-бот для автоматической обработки клиентских запросов и создания тикетов в Jira.

## Установка

```bash
git clone https://github.com/өзінің/teamtrustgate.git
cd teamtrustgate
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

## Настройка

Скопируй `.env.example` в `.env` и заполни:

```
TELEGRAM_BOT_TOKEN=  # от BotFather
OPENAI_API_KEY=      # от platform.openai.com
JIRA_BASE_URL=       # https://компания.atlassian.net
JIRA_TOKEN=          # от id.atlassian.com/manage-profile/security/api-tokens
PRODUCT_STRATEGY=    # описание продукта и стратегии
```

## Запуск

```bash
python bot.py
```

## Структура файлов

```
teamtrustgate/
├── bot.py           # Telegram-бот, главный файл
├── deduplicator.py  # Проверка дублей
├── scorer.py        # Приоритизация RICE
├── jira_client.py   # Создание тикетов в Jira
├── llm_adapter.py   # Запросы к OpenAI
├── prompts.py       # Все промпты
├── utils.py         # Вспомогательные функции
├── requirements.txt
├── .env.example
└── .gitignore
```

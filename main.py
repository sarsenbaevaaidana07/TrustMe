# main.py
import os
import logging
import telebot
from openai import OpenAI
from jira import JIRA
from prompts import SYSTEM_ANALYSIS_PROMPT

# Логтарды жазу (Railway консолінен көру үшін)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Railway Environment Variables-тен мәліметтерді қауіпсіз оқу
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
JIRA_URL = os.getenv("JIRA_URL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY")

# Клиенттерді іске қосу
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Jira-ға қосылу функциясы
def get_jira_client():
    try:
        return JIRA(server=JIRA_URL, basic_auth=(JIRA_EMAIL, JIRA_API_TOKEN))
    except Exception as e:
        logger.error(f"Jira-ға қосылу кезінде қате шықты: {e}")
        return None

# /start командасын өңдеу
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "TeamTrustGate дайын. Маған клиенттің шикі сұранысын жіберіңіз, мен оны талдап, Jira-ға тикет жасаймын.")

# Менеджерден келген мәтінді өңдеу және Jira-ға жіберу
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    user_text = message.text
    
    # /start сияқты команда болса өткізіп жіберу
    if user_text.startswith('/'):
        return

    bot.send_chat_action(message.chat.id, 'typing')
    logger.info(f"Жаңа хабарлама келді: {user_text[:30]}...")

    try:
        # OpenAI-ға сұраныс жіберу (System prompt файлдан алынады)
        response = openai_client.chat.completions.create(
            model="gpt-4",  # Немесе сендер қолданатын модель аты
            messages=[
                {"role": "system", "content": SYSTEM_ANALYSIS_PROMPT},
                {"role": "user", "content": user_text}
            ],
            temperature=0.7
        )
        
        # AI дайындаған әдемі артефакт мәтіні
        analyzed_artifact = response.choices[0].message.content
        
        # Jira-мен байланысу
        jira = get_jira_client()
        if not jira:
            bot.reply_to(message, "Қате: Jira жүйесіне қосылу мүмкін болмады. Логтарды тексеріңіз.")
            return

        # Jira тикетінің тақырыбы (қысқаша бірінші жолынан алынады)
        summary_text = f"Анализ: {user_text[:50]}..."

        # Jira-дан жаңа тикет ашу
        issue_dict = {
            'project': {'key': JIRA_PROJECT_KEY},
            'summary': summary_text,
            'description': analyzed_artifact,
            'issuetype': {'name': 'Task'},  # Немесе 'Story'
        }
        
        new_issue = jira.create_issue(fields=issue_dict)
        
        # Қолданушыға сәтті аяқталғаны туралы жауап беру
        ticket_url = f"{JIRA_URL}/browse/{new_issue.key}"
        success_message = f"✅ **Jira-да тикет сәтті құрылды!**\n\n🔗 Кілті: `{new_issue.key}`\n🔗 Сілтеме: {ticket_url}\n\n**AI Талдауы:**\n\n{analyzed_artifact}"
        
        bot.reply_to(message, success_message, parse_mode="Markdown")
        logger.info(f"Jira тикеті ашылды: {new_issue.key}")

    except Exception as e:
        logger.error(f"Хабарламаны өңдеуде қате кетті: {e}")
        bot.reply_to(message, f"❌ Қате пайда болды. Код логтарын тексеріңіз.\nЕскерту: {str(e)[:100]}")

# Ботты іске қосу (Long Polling)
if __name__ == "__main__":
    logger.info("Бот іске қосылды...")
    bot.infinity_polling()

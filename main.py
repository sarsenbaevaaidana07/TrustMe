import telebot  # немесе aiogram (жобада қайсысы қолданылса да)
from openai import OpenAI
from prompts import SYSTEM_ANALYSIS_PROMPT  # Бағанағы промптты импорттаймыз

client = OpenAI(api_key="СЕНІҢ_LLM_API_KEY")

# Бот хабарлама алған кезде жұмыс істейтін функция (Handler)
# Қазіргі қате жері осы функцияның ішінде:
def handle_user_request(message):
    user_raw_text = message.text  # Менеджердің чатқа жазған шикі сұранысы
    
    # КРИТИКАЛЫҚ ӨЗГЕРІС: LLM-ге сұранысты құрастыру
    messages = [
        {
            "role": "system", 
            "content": SYSTEM_ANALYSIS_PROMPT  # Промпт файлдан автоматты түрде қосылады
        },
        {
            "role": "user", 
            "content": user_raw_text  # Чатқа жазылған клиенттің сұранысы
        }
    ]
    
    # OpenAI-ға сұраныс жіберу
    response = client.chat.completions.create(
        model="gpt-4", # немесе сендерде қандай модель тұр
        messages=messages
    )
    
    ai_analyzed_artifact = response.choices[0].message.content
    
    # Осы жерден кейін Jira-ға жіберетін функция шақырылады (мысалы: create_jira_ticket)
    # Jira-ға менеджердің жазған мәтіні емес, AI дайындаған 'ai_analyzed_artifact' баруы керек.

import os
import telebot
import json
from datetime import datetime, timezone
from google import genai
from google.genai import types
from config import TELEGRAM_TOKEN, GOOGLE_API_KEY, MODEL, SYSTEM_PROMPT

# === CONFIG ===
CHAT_HISTORY_DIR = "chat_history"

if not os.path.exists(CHAT_HISTORY_DIR):
    os.makedirs(CHAT_HISTORY_DIR)

# === INIT ===
client = genai.Client(api_key=GOOGLE_API_KEY)
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# === CHAT HISTORY FUNCTIONS ===

def get_history_filepath(message):
    username = message.from_user.username
    user_id = message.from_user.id
    safe_name = username if username else str(user_id)
    return os.path.join(CHAT_HISTORY_DIR, f"{safe_name}.json")

def load_history(message):
    path = get_history_filepath(message)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return ""

def save_history(role, text, message, timestamp=None):
    path = get_history_filepath(message)

    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat()

    entry = {
        "role": role,
        "content": text.strip(),
        "timestamp": timestamp
    }

    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

# === GEMINI GENERATION ===
# === GEMINI GENERATION ===

def generate_response(user_message, message):
    history_text = load_history(message)
    contents = []

    if history_text:
        for line in history_text.strip().split("\n"):
            entry = json.loads(line)
            contents.append(
                types.Content(
                    role=entry["role"],
                    parts=[types.Part(text=entry["content"])]
                )
            )

    contents.append(
        types.Content(
            role="user",
            parts=[types.Part(text=user_message)]
        )
    )

    system_content = types.Content(
        role="user",  # Gemini does NOT support "system" role — must be "user"
        parts=[types.Part(text=SYSTEM_PROMPT)]
    )

    config = types.GenerateContentConfig(
        temperature=1.7,
        system_instruction=system_content,
        safety_settings=[
            types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
        ],
        response_mime_type="text/plain",
    )

    response_text = ""
    for chunk in client.models.generate_content_stream(
        model=MODEL,
        contents=contents,
        config=config
    ):
        response_text += chunk.text

    current_time = datetime.fromtimestamp(message.date, timezone.utc).isoformat()
    save_history("user", user_message, message, timestamp=current_time)
    save_history("model", response_text, message)

    return response_text.strip()
# === TELEGRAM HANDLER ===

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    user_message = message.text.strip()
    sender = message.from_user.username or str(message.from_user.id)
    print(f"Received message from {sender}: {user_message}")

    try:
        response = generate_response(user_message, message)
    except Exception as e:
        print(f"Error generating response: {e}")
        response = "Sorry, something went wrong... ☹️"

    bot.reply_to(message, response)

# === RUN ===

if __name__ == "__main__":
    print("Alita-1.2 is running...✨")
    bot.infinity_polling()
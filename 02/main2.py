import os
import telebot
import json
from datetime import datetime, timezone
from google import genai
from google.genai import types
from config import TELEGRAM_TOKEN, GOOGLE_API_KEY, MODEL, SYSTEM_PROMPT

# === CONFIG ===
CHAT_HISTORY_DIR = "chat_history"
MEDIA_DIR = "media_files"

if not os.path.exists(CHAT_HISTORY_DIR):
    os.makedirs(CHAT_HISTORY_DIR)

if not os.path.exists(MEDIA_DIR):
    os.makedirs(MEDIA_DIR)

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

# === GEMINI TEXT RESPONSE ===

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
        role="user",
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

# === GEMINI MEDIA OPINION ===

def generate_media_opinion(media_bytes: bytes, mime_type: str) -> str:
    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part(text=SYSTEM_PROMPT),
                types.Part(data=<bytes>, mime_type="image/jpeg")

            ]
        )
    ]

    config = types.GenerateContentConfig(
        temperature=1.7,
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
        config=config,
    ):
        response_text += chunk.text

    return response_text.strip()

# === TELEGRAM HANDLERS ===

@bot.message_handler(content_types=["text"])
def handle_text(message):
    user_message = message.text.strip()
    sender = message.from_user.username or str(message.from_user.id)
    print(f"Received message from {sender}: {user_message}")

    try:
        response = generate_response(user_message, message)
    except Exception as e:
        print(f"Error generating response: {e}")
        response = "Sorry, kichu vul holo... ami abar chesta korbo."

    bot.reply_to(message, response)

@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        # Telegram photos are always JPEG format
        mime_type = "image/jpeg"
        user_id = message.from_user.id
        filename = f"{user_id}_{message.message_id}.jpg"
        file_path = os.path.join(MEDIA_DIR, filename)

        with open(file_path, "wb") as f:
            f.write(downloaded_file)

        print(f"Saved file: {file_path}")

        # Generate opinion based on image bytes
        opinion = generate_media_opinion(downloaded_file, mime_type)

        # Save history with image mention and bot opinion
        save_history("user", f"[User sent image: {filename}]", message)
        save_history("model", opinion, message)

        bot.reply_to(message, opinion)

    except Exception as e:
        print(f"Error in image handling: {e}")
        bot.reply_to(message, "Oops... Chobi ta dekhte giye kichu vul holo.")

@bot.message_handler(content_types=["document"])
def handle_document(message):
    try:
        # For handling GIF, PNG, JPG as document uploads
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        # Use the file extension from the original file name
        file_name = message.document.file_name
        user_id = message.from_user.id
        filename = f"{user_id}_{message.message_id}_{file_name}"
        file_path = os.path.join(MEDIA_DIR, filename)

        with open(file_path, "wb") as f:
            f.write(downloaded_file)

        print(f"Saved file: {file_path}")

        # Guess mime type from extension (simple version)
        ext = file_name.split('.')[-1].lower()
        mime_map = {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "gif": "image/gif",
            "mp4": "video/mp4"
        }
        mime_type = mime_map.get(ext, "application/octet-stream")

        opinion = generate_media_opinion(downloaded_file, mime_type)

        save_history("user", f"[User sent file: {filename}]", message)
        save_history("model", opinion, message)

        bot.reply_to(message, opinion)

    except Exception as e:
        print(f"Error in document handling: {e}")
        bot.reply_to(message, "Oops... File ta dekhte giye kichu vul holo.")

# === RUN ===

if __name__ == "__main__":
    print("Alita-1.3 is running...✨")
    bot.infinity_polling()

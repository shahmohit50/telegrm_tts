import logging
import os
import re
import requests
import edge_tts
import asyncio
from flask import Flask, request
from telegram import Bot, Update, ChatAction
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, Filters
from bs4 import BeautifulSoup

# Environment variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # e.g. https://your-app-name.onrender.com
PORT = int(os.getenv("PORT", 5000))
MAX_CHAPTERS = 20
TARGET_NOVEL_KEYWORD = "Son of the Dragon"

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

os.makedirs("downloads", exist_ok=True)

bot = Bot(token=TELEGRAM_BOT_TOKEN)
app = Flask(__name__)
dispatcher = Dispatcher(bot, None, workers=0)

def extract_slug_and_chapter(url):
    match = re.search(r'liddread\.com/([^/]+)-chapter-(\d+)/', url)
    if match:
        slug = match.group(1)
        chapter = int(match.group(2))
        return slug, chapter
    return None, None

def scrape_content(url):
    res = requests.get(url, timeout=10)
    soup = BeautifulSoup(res.text, "html.parser")
    title_tag = soup.find("title")
    content_div = soup.find("div", class_="chapter-content") or soup.find("div", class_="content")
    title = title_tag.get_text() if title_tag else "No Title"
    content = content_div.get_text(separator="\n") if content_div else "Content not found."
    return title.strip(), content.strip()

async def text_to_speech(text, output_path):
    communicate = edge_tts.Communicate(text, voice="en-US-GuyNeural")
    await communicate.save(output_path)

def handle_message(update, context):
    chat_id = update.effective_chat.id
    url = update.message.text.strip()

    slug, chapter_num = extract_slug_and_chapter(url)
    if not slug or not chapter_num:
        bot.send_message(chat_id=chat_id, text="❌ Invalid URL format. Please send me a Liddread chapter URL.")
        return

    bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    bot.send_message(chat_id=chat_id, text=f"🔎 Starting from Chapter {chapter_num}. Processing up to {MAX_CHAPTERS} chapters.")

    for i in range(MAX_CHAPTERS):
        current_chapter = chapter_num + i
        chapter_url = f"https://liddread.com/{slug}-chapter-{current_chapter}/"
        logger.info(f"Fetching {chapter_url}")
        
        try:
            title, content = scrape_content(chapter_url)
            if TARGET_NOVEL_KEYWORD.lower() not in title.lower():
                bot.send_message(chat_id=chat_id, text=f"⚠️ Stopping at chapter {current_chapter}. Title mismatch: '{title}'")
                break

            filename = f"downloads/{slug}_chapter_{current_chapter}.txt"
            audio_file = f"downloads/{slug}_chapter_{current_chapter}.mp3"

            with open(filename, "w", encoding="utf-8") as f:
                f.write(content)

            bot.send_message(chat_id=chat_id, text=f"📖 Chapter {current_chapter} scraped. Generating audio...")
            asyncio.run(text_to_speech(content, audio_file))

            bot.send_document(chat_id=chat_id, document=open(filename, "rb"), filename=os.path.basename(filename))
            bot.send_audio(chat_id=chat_id, audio=open(audio_file, "rb"), title=title)

            os.remove(filename)
            os.remove(audio_file)

        except Exception as e:
            logger.error(e)
            bot.send_message(chat_id=chat_id, text=f"❌ Failed at Chapter {current_chapter}. Stopping.")
            break

def start(update, context):
    update.message.reply_text("Send me a Liddread chapter URL to scrape and convert multiple chapters to audio.")

dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

@app.route(f"/{TELEGRAM_BOT_TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return "ok"

@app.route("/")
def index():
    return "Bot is running"

if __name__ == '__main__':
    bot.set_webhook(f"{WEBHOOK_URL}/{TELEGRAM_BOT_TOKEN}")
    app.run(host="0.0.0.0", port=PORT)
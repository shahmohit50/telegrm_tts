import os
import logging
import requests
import edge_tts
import asyncio
import re
from flask import Flask, request
from telegram import Bot, Update, ChatAction
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, Filters
from goose3 import Goose
from collections import deque

# ENV variables
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
bot = Bot(TOKEN)
app = Flask(__name__)

# Setup dispatcher
dispatcher = Dispatcher(bot, None, workers=0)

# Deduplication buffer: keep last 500 updates (tune as needed)
processed_updates = deque(maxlen=500)

MAX_CHAPTERS = 20
TARGET_NOVEL_KEYWORD = "Son of the Dragon"

def extract_slug_and_chapter(url):
    match = re.search(r'liddread\.com/([^/]+)-chapter-(\d+)/', url)
    if match:
        slug = match.group(1)
        chapter = int(match.group(2))
        return slug, chapter
    return None, None

def scrape_content(url):
    g = Goose()
    article = g.extract(url=url)
    title = article.title or "No Title"
    content = article.cleaned_text or "Content not found."
    return title.strip(), content.strip()

async def text_to_speech(text, output_path):
    communicate = edge_tts.Communicate(text, voice="en-US-GuyNeural")
    await communicate.save(output_path)

def handle_message(update, context):
    chat_id = update.effective_chat.id
    url = update.message.text.strip()

    slug, chapter_num = extract_slug_and_chapter(url)
    if not slug or not chapter_num:
        bot.send_message(chat_id=chat_id, text="❌ Invalid URL format.")
        return

    bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    bot.send_message(chat_id=chat_id, text=f"🔎 Starting from Chapter {chapter_num}")

    for i in range(MAX_CHAPTERS):
        current_chapter = chapter_num + i
        chapter_url = f"https://liddread.com/{slug}-chapter-{current_chapter}/"
        try:
            title, content = scrape_content(chapter_url)
            if TARGET_NOVEL_KEYWORD.lower() not in title.lower():
                bot.send_message(chat_id=chat_id, text=f"⚠️ Stopping at Chapter {current_chapter}")
                break

            filename = f"{slug}_chapter_{current_chapter}.txt"
            audio_file = f"{slug}_chapter_{current_chapter}.mp3"

            with open(filename, "w", encoding="utf-8") as f:
                f.write(content)

            bot.send_message(chat_id=chat_id, text="Generating audio...")
            asyncio.run(text_to_speech(content, audio_file))

            bot.send_document(chat_id=chat_id, document=open(filename, "rb"))
            bot.send_audio(chat_id=chat_id, audio=open(audio_file, "rb"))

            os.remove(filename)
            os.remove(audio_file)

        except Exception as e:
            bot.send_message(chat_id=chat_id, text="❌ Failed to process.")
            break

def start(update, context):
    update.message.reply_text("Send me a Liddread URL")

# Setup handlers
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    if update.update_id in processed_updates:
        return "duplicate"
    processed_updates.append(update.update_id)
    dispatcher.process_update(update)
    return "ok"

@app.route("/")
def index():
    return "Bot is running"

if __name__ == '__main__':
    bot.set_webhook(f"{WEBHOOK_URL}/{TOKEN}")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

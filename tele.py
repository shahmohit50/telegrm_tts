import logging
import os
import re
import requests
import edge_tts
import asyncio
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
from telegram import ChatAction
from goose3 import Goose

TELEGRAM_BOT_TOKEN = "7445313694:AAGOphwXa1pU2Urxvcm6UdMmf05oaZz5T40"
MAX_CHAPTERS = 20
TARGET_NOVEL_KEYWORD = "Son of the Dragon"

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

os.makedirs("downloads", exist_ok=True)

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
        context.bot.send_message(chat_id=chat_id, text="❌ Invalid URL format. Please send me a Liddread chapter URL.")
        return

    context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    context.bot.send_message(chat_id=chat_id, text=f"🔎 Starting from Chapter {chapter_num}. Processing up to {MAX_CHAPTERS} chapters.")

    for i in range(MAX_CHAPTERS):
        current_chapter = chapter_num + i
        chapter_url = f"https://liddread.com/{slug}-chapter-{current_chapter}/"
        logger.info(f"Fetching {chapter_url}")
        
        try:
            title, content = scrape_content(chapter_url)

            if TARGET_NOVEL_KEYWORD.lower() not in title.lower():
                context.bot.send_message(chat_id=chat_id, text=f"⚠️ Stopping at chapter {current_chapter}. Title mismatch: '{title}'")
                break

            filename = f"downloads/{slug}_chapter_{current_chapter}.txt"
            audio_file = f"downloads/{slug}_chapter_{current_chapter}.mp3"

            with open(filename, "w", encoding="utf-8") as f:
                f.write(content)

            context.bot.send_message(chat_id=chat_id, text=f"📖 Chapter {current_chapter} scraped. Generating audio...")
            asyncio.run(text_to_speech(content, audio_file))

            context.bot.send_document(chat_id=chat_id, document=open(filename, "rb"), filename=os.path.basename(filename))
            context.bot.send_audio(chat_id=chat_id, audio=open(audio_file, "rb"), title=title)

            os.remove(filename)
            os.remove(audio_file)

        except Exception as e:
            logger.error(e)
            context.bot.send_message(chat_id=chat_id, text=f"❌ Failed at Chapter {current_chapter}. Stopping.")
            break

def start(update, context):
    update.message.reply_text("Send me a Liddread chapter URL to scrape and convert multiple chapters to audio.")

def main():
    updater = Updater(TELEGRAM_BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()

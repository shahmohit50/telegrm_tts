import os
import logging
import requests
import edge_tts
import asyncio
import re
import random
import json
import html
from flask import Flask, request
from telegram import Bot, Update, ChatAction
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, Filters, CallbackQueryHandler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from goose3 import Goose
from collections import deque
import gender_guesser.detector as gender_detector
from deep_translator import GoogleTranslator

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
bot = Bot(TOKEN)
app = Flask(__name__)

# Setup dispatcher
dispatcher = Dispatcher(bot, None, workers=0)
processed_updates = deque(maxlen=500)

MAX_CHAPTERS = 20
TARGET_NOVEL_KEYWORD = "Son of the Dragon"
narrator_voice = "en-GB-LibbyNeural"
detector = gender_detector.Detector(case_sensitive=False)

available_voices = [
    "en-US-GuyNeural",
    "en-US-DavisNeural",
    "en-US-JennyNeural",
    "en-US-AriaNeural",
    "en-GB-RyanNeural",
    "en-AU-NatashaNeural",
    "en-IN-NeerjaNeural"
]
character_voice_map = {}
user_context = {}

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

def translate_text(text, target_lang="es"):
    try:
        return GoogleTranslator(source="auto", target=target_lang).translate(text)
    except Exception as e:
        logging.warning(f"Translation failed: {e}")
        return text

def detect_speaker_name(tail):
    tail = tail.lower()
    name_match = re.search(r"(?:said|replied|asked|yelled|shouted|cried)\s+(\w+\s?\w*)", tail)
    if name_match:
        return name_match.group(1).strip().lower()
    elif 'old man' in tail:
        return 'old man'
    elif 'girl' in tail:
        return 'girl'
    return 'unknown'

def split_paragraph_with_speaker_attribution(para):
     pattern = re.compile(r'([“"])(.+?)([”"])(?=\s|$)')  # Matches any quoted segment
    #pattern = re.compile(r'(["“](.*?)["”])([^\n]*)')
    #matches = pattern.findall(para)
    segments = []
    last_end = 0

    for match in pattern.finditer(para):
        start, end = match.span()
        # Add narration before the quote
        if start > last_end:
            narration = para[last_end:start].strip()
            if narration:
                segments.append((narration, "narrator"))

        quote_text = match.group(2).strip()
        if quote_text:
            segments.append((quote_text, "character"))

        last_end = end

    # Add remaining narration after the last quote
    if last_end < len(para):
        tail = para[last_end:].strip()
        if tail:
            segments.append((tail, "narrator"))

    return segments if segments else [(para.strip(), "narrator")]

    # if not matches:
    #     return [(para.strip(), "narrator")]

    # # If no quotes are found, treat it as narration
    # if not matches:
    #     return [(para.strip(), "narrator")]

    # # For each match (quote and tail), split the text
    # for quote, quote_text, tail in matches:
    #     if quote_text.strip():
    #         segments.append((quote_text.strip(), "character"))  # dialogue part

    #     if tail.strip():
    #         segments.append((tail.strip(), "narrator"))  # narrative part

    # return segments
    
    #if not matches:
       # return [(para.strip(), "narrator")]

   # for quote, quote_text, tail in matches:
        #speaker = detect_speaker_name(tail)
      #  segments.append((quote_text.strip(), speaker))

     #   if tail:
       #     segments.append((tail.strip(), "narrator"))

    #return segments

def assign_voice_for_speaker(name):
    if name not in character_voice_map:
        unused = [v for v in available_voices if v not in character_voice_map.values() and v != narrator_voice]
        voice = random.choice(unused or available_voices)
        character_voice_map[name] = voice
    return character_voice_map[name]

async def text_to_speech_with_speaker_attribution(full_text, output_path, translate=False, lang_code="es"):
    if translate:
        full_text = translate_text(full_text, target_lang=lang_code)

    dialogues = []
    paragraphs = full_text.split('\n')
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        segments = split_paragraph_with_speaker_attribution(para)
        dialogues.extend(segments)

    filenames = []
    for i, (sentence, speaker_name) in enumerate(dialogues):
        if not sentence.strip():
            continue

        if lang_code == "hi":
            voice = "hi-IN-MadhurNeural"
        elif speaker_name == "narrator":
            voice = narrator_voice
        elif speaker_name == "unknown":
            voice = random.choice([v for v in available_voices if v != narrator_voice])
        else:
            voice = assign_voice_for_speaker(speaker_name)

        temp_output = f"part_{i}.mp3"
        try:
            communicate = edge_tts.Communicate(sentence, voice=voice)
            await communicate.save(temp_output)

            if os.path.exists(temp_output) and os.path.getsize(temp_output) > 100:
                filenames.append(temp_output)
            else:
                logging.warning(f"🛑 Empty or missing audio for part {i} — voice={voice}")
        except Exception as e:
            logging.exception(f"❌ TTS failed for part {i} — voice={voice}, text={sentence}")

    with open(output_path, "wb") as out_file:
        for file in filenames:
            if os.path.exists(file):
                with open(file, "rb") as f:
                    out_file.write(f.read())
                os.remove(file)
            else:
                logging.warning(f"⚠️ Skipped missing audio file: {file}")

def handle_message(update, context):
    chat_id = update.effective_chat.id
    url = update.message.text.strip()
    slug, chapter_num = extract_slug_and_chapter(url)
    if not slug or not chapter_num:
        bot.send_message(chat_id=chat_id, text="❌ Invalid URL format.")
        return

    user_context[chat_id] = {"slug": slug, "chapter": chapter_num, "url": url}

    keyboard = [
        [
            InlineKeyboardButton("Translate to Spanish", callback_data="translate_es"),
            InlineKeyboardButton("Translate to Hindi", callback_data="translate_hi")
        ],
        [InlineKeyboardButton("Keep Original (English)", callback_data="original")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    bot.send_message(chat_id=chat_id, text="🌐 Do you want to translate the content before audio generation?", reply_markup=reply_markup)


def handle_translation_choice(update, context):
    query = update.callback_query
    chat_id = query.message.chat_id
    choice = query.data

    bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    bot.edit_message_text(chat_id=chat_id, message_id=query.message.message_id, text="📖 Processing your request...")

    context_data = user_context.get(chat_id, {})
    slug = context_data.get("slug")
    chapter_num = context_data.get("chapter")

    lang_code = "en"
    translate_flag = False
    if choice.startswith("translate_"):
        translate_flag = True
        lang_code = choice.split("_")[1]

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

            bot.send_message(chat_id=chat_id, text="🔊 Generating audio...")
            asyncio.run(text_to_speech_with_speaker_attribution(content, audio_file, translate=translate_flag, lang_code=lang_code))

            bot.send_document(chat_id=chat_id, document=open(filename, "rb"))
            bot.send_audio(chat_id=chat_id, audio=open(audio_file, "rb"))

            os.remove(filename)
            os.remove(audio_file)

        except Exception as e:
            logging.exception("Error processing chapter")
            bot.send_message(chat_id=chat_id, text=f"❌ Failed to process: {e}")
            break


def start(update, context):
    update.message.reply_text("Send me a Liddread URL")


dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
dispatcher.add_handler(CallbackQueryHandler(handle_translation_choice))


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

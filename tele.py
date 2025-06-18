import os
import random
import re
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
import html
import gender_guesser.detector as gender_detector


# ENV variables
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
bot = Bot(TOKEN)
app = Flask(__name__)

# Setup dispatcher
dispatcher = Dispatcher(bot, None, workers=0)

# Deduplication buffer: keep last 500 updates (tune as needed)
processed_updates = deque(maxlen=500)

detector = gender_detector.Detector(case_sensitive=False)


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

def detect_gender_from_speaker(tail):
    tail = tail.lower()

    # Try detecting a name in the tail
    name_match = re.search(r"(?:said|replied|asked|yelled|shouted|cried)\\s+(\\w+\\s?\\w*)", tail)
    if name_match:
        name = name_match.group(1).strip()
        g = detector.get_gender(name.split()[0])  # First name only
        if g in ['male', 'mostly_male']:
            return 'male'
        elif g in ['female', 'mostly_female']:
            return 'female'

    # Heuristic checks
    if any(word in tail for word in ['old man', 'boy', 'elder', 'father', 'young master']):
        return 'male'
    elif any(word in tail for word in ['girl', 'mother', 'aunt', 'sister']):
        return 'female'

    # Fallback
    return random.choice(['male', 'female'])

def split_paragraph_with_speaker_attribution(para):
    pattern = re.compile(r'(["“](.*?)["”])([^\n]*)')
    matches = pattern.findall(para)
    segments = []

    if not matches:
        return [(para.strip(), "narrator")]

    for quote, quote_text, tail in matches:
        gender = detect_gender_from_speaker(tail)
        segments.append((quote_text.strip(), gender))

        if tail:
            segments.append((tail.strip(), "narrator"))

    return segments

# def split_paragraph_with_quotes(para):
#     parts = re.split(r'(\".*?\"|“.*?”)', para)
#     segments = []
#     for part in parts:
#         part = part.strip()
#         if not part:
#             continue
#         if (part.startswith('"') and part.endswith('"')) or (part.startswith('“') and part.endswith('”')):
#             gender = random.choice(["male", "female"])
#             segments.append((part.strip('“”"'), gender))
#         else:
#             segments.append((part, "narrator"))
#     return segments


# async def text_to_speech(text, output_path):
#     communicate = edge_tts.Communicate(text, voice="en-US-GuyNeural")
#     await communicate.save(output_path)

async def text_to_speech_with_dialogue_and_narration(full_text, output_path):
    dialogues = []
    narrator_voice = "en-GB-LibbyNeural"  # Narrator voice

    # Split text into paragraphs (very simple split for now)
    paragraphs = full_text.split('\n')

    for para in paragraphs:
        # Clean empty lines
        para = para.strip()
        if not para:
            continue
        # segments = split_paragraph_with_quotes(para)
        segments = split_paragraph_with_speaker_attribution(para)
        dialogues.extend(segments)

    filenames = []
    for i, (sentence, role) in enumerate(dialogues):
        if role == "male":
            voice = "en-US-GuyNeural"
            ssml = sentence
        elif role == "female":
            voice = "en-US-JennyNeural"
            ssml = sentence
        else:
            voice = narrator_voice
            safe_sentence = html.escape(sentence)
            # ssml = f'<speak><voice name="{voice}"><prosody pitch="-10%" rate="95%">{sentence}</prosody></voice></speak>'
            ssml = f'<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='en-US'><voice name="{voice}"><prosody pitch="-10%" rate="95%">{safe_sentence}</prosody></voice></speak>'
        temp_output = f"part_{i}.mp3"
        if role == "narrator":
            communicate = edge_tts.Communicate(ssml, voice=voice )
        else:
            communicate = edge_tts.Communicate(ssml, voice=voice )
        # communicate = edge_tts.Communicate(sentence, voice=voice)
        await communicate.save(temp_output)
        filenames.append(temp_output)

    # Merge files into final output
    with open(output_path, "wb") as out_file:
        for file in filenames:
            with open(file, "rb") as f:
                out_file.write(f.read())
            os.remove(file)

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
            # asyncio.run(text_to_speech(content, audio_file))
            asyncio.run(text_to_speech_with_dialogue_and_narration(content, audio_file))

            bot.send_document(chat_id=chat_id, document=open(filename, "rb"))
            bot.send_audio(chat_id=chat_id, audio=open(audio_file, "rb"))

            os.remove(filename)
            os.remove(audio_file)

        except Exception as e:
            bot.send_message(chat_id=chat_id, text="❌ Failed to process.")
            bot.send_message(chat_id=chat_id, text="Error: " + str(e))
            logging.error(f"Error processing chapter {current_chapter}: {e}")
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

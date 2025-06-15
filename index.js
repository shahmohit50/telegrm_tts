const TelegramBot = require('node-telegram-bot-api');
const axios = require('axios');
const { Readability } = require('@mozilla/readability');
const { JSDOM } = require('jsdom');
const fs = require('fs');
const path = require('path');

// Get token from environment variable
// const token = process.env.TELEGRAM_BOT_TOKEN;
const token = '7445313694:AAGOphwXa1pU2Urxvcm6UdMmf05oaZz5T40';

if (!token) {
  console.error('TELEGRAM_BOT_TOKEN environment variable is not set!');
  process.exit(1);
}

// Create a bot that uses polling to fetch new updates
const bot = new TelegramBot(token, { polling: true });

// Store message IDs for each chat
const messageHistory = new Map();

// Function to store message ID
function storeMessage(chatId, messageId) {
  if (!messageHistory.has(chatId)) {
    messageHistory.set(chatId, []);
  }
  messageHistory.get(chatId).push(messageId);
}

// Function to clear messages
async function clearMessages(chatId) {
  try {
    const messages = messageHistory.get(chatId) || [];
    for (const messageId of messages) {
      try {
        await bot.deleteMessage(chatId, messageId);
      } catch (error) {
        console.error(`Error deleting message ${messageId}:`, error);
      }
    }
    messageHistory.set(chatId, []);
    await bot.sendMessage(chatId, '🧹 All messages cleared!');
  } catch (error) {
    console.error('Error clearing messages:', error);
    await bot.sendMessage(chatId, '❌ Error clearing messages.');
  }
}

// Utility functions
function extractChapterNumber(url) {
  const match = url.match(/(\d+)/);
  return match ? parseInt(match[1]) : null;
}

function getNextChapterUrl(url) {
  const chapterNumber = extractChapterNumber(url);
  return chapterNumber ? url.replace(/\d+/, (chapterNumber + 1).toString()) : null;
}

function isSameNovel(currentTitle, nextTitle) {
  const cleanTitle = (title) => {
    return title
      .replace(/Chapter\s*\d+/i, '')
      .replace(/\d+/g, '')
      .replace(/[-–—]/g, '')
      .replace(/\s+/g, ' ')
      .trim();
  };
  return cleanTitle(currentTitle) === cleanTitle(nextTitle);
}

// Main functions
async function extractReadableContent(url) {
  try {
    const { data: html } = await axios.get(url);
    const dom = new JSDOM(html, { url });
    const reader = new Readability(dom.window.document);
    const article = reader.parse();
    return article ? { title: article.title, content: article.textContent } : null;
  } catch (error) {
    console.error('Error extracting content:', error);
    return null;
  }
}

function saveToFile(title, content, chapterNumber) {
  const filename = `chapter_${chapterNumber}_${Date.now()}.txt`;
  const filepath = path.join(__dirname, filename);
  fs.writeFileSync(filepath, `Title: ${title}\n\n${content}`, 'utf8');
  return filename;
}

async function processChapter(url, chatId, originalTitle = null) {
  try {
    const urlObj = new URL(url);
    const message = await bot.sendMessage(chatId, `🔍 Scraping content from: ${urlObj.hostname}${urlObj.pathname}`);
    storeMessage(chatId, message.message_id);
    
    const article = await extractReadableContent(url);
    if (!article) {
      const errorMsg = await bot.sendMessage(chatId, '❌ Could not extract content from the provided URL.');
      storeMessage(chatId, errorMsg.message_id);
      return false;
    }
    
    if (originalTitle && !isSameNovel(originalTitle, article.title)) {
      const warningMsg = await bot.sendMessage(chatId, '⚠️ Different novel detected. Stopping to prevent mixing novels.');
      storeMessage(chatId, warningMsg.message_id);
      return false;
    }
    
    const chapterNumber = extractChapterNumber(url);
    const filename = saveToFile(article.title, article.content, chapterNumber);
    
    const docMessage = await bot.sendDocument(chatId, filename, {
      caption: `📚 Chapter ${chapterNumber}: ${article.title}`,
      contentType: 'text/plain'
    }, {
      filename: filename,
      contentType: 'text/plain'
    });
    storeMessage(chatId, docMessage.message_id);
    
    fs.unlinkSync(filename);
    return article.title;
  } catch (error) {
    console.error('Error processing chapter:', error);
    const errorMsg = await bot.sendMessage(chatId, '❌ An error occurred while processing the chapter.');
    storeMessage(chatId, errorMsg.message_id);
    return false;
  }
}

// Bot message handler
bot.on('message', async (msg) => {
  const chatId = msg.chat.id;
  const userMessage = msg.text;

  // Handle clear command
  if (userMessage?.toLowerCase() === 'clear') {
    await clearMessages(chatId);
    return;
  }

  if (!userMessage?.includes('http://') && !userMessage?.includes('https://')) {
    const message = await bot.sendMessage(chatId, 'Please send me a URL to scrape the content from.');
    storeMessage(chatId, message.message_id);
    return;
  }

  try {
    let currentUrl = userMessage;
    let originalTitle = null;
    let chapterCount = 0;
    const maxChapters = 20;
    const startChapter = extractChapterNumber(currentUrl);
    
    if (startChapter) {
      const startMsg = await bot.sendMessage(chatId, `📚 Starting from Chapter ${startChapter}. Will process up to ${maxChapters} chapters.`);
      storeMessage(chatId, startMsg.message_id);
    }
    
    while (chapterCount < maxChapters) {
      const title = await processChapter(currentUrl, chatId, originalTitle);
      if (!title) break;
      
      if (!originalTitle) originalTitle = title;
      
      chapterCount++;
      const currentChapter = extractChapterNumber(currentUrl);
      
      if (chapterCount % 5 === 0) {
        const progressMsg = await bot.sendMessage(chatId, `⏳ Progress: Processed ${chapterCount} chapters (Currently at Chapter ${currentChapter})`);
        storeMessage(chatId, progressMsg.message_id);
      }
      
      const nextUrl = getNextChapterUrl(currentUrl);
      if (!nextUrl) {
        const endMsg = await bot.sendMessage(chatId, '📚 Reached the end of available chapters.');
        storeMessage(chatId, endMsg.message_id);
        break;
      }
      
      currentUrl = nextUrl;
      await new Promise(resolve => setTimeout(resolve, 2000));
    }
    
    if (chapterCount > 0) {
      const endChapter = extractChapterNumber(currentUrl);
      const finalMsg = await bot.sendMessage(chatId, `✅ Successfully processed ${chapterCount} chapters (from Chapter ${startChapter} to Chapter ${endChapter}).`);
      storeMessage(chatId, finalMsg.message_id);
    }
  } catch (error) {
    console.error('Error:', error);
    const errorMsg = await bot.sendMessage(chatId, '❌ An error occurred while processing your request.');
    storeMessage(chatId, errorMsg.message_id);
  }
});

// Start the bot
console.log('Bot is running...'); 
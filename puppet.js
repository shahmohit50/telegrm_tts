const puppeteer = require('puppeteer');

async function generateSpeechFromPage(url, text) {
  // Launch browser
  const browser = await puppeteer.launch({ headless: false });
  const page = await browser.newPage();
  
  // Set up a page with your content
  await page.goto(url);
  
  // Run JavaScript inside the page context to trigger "Listen to this page"
  await page.evaluate((text) => {
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'en-US';  // You can specify the language
    utterance.rate = 1;  // Adjust speed
    utterance.pitch = 1;  // Adjust pitch
    speechSynthesis.speak(utterance);
  }, text);

  // Wait for the speech to finish (you can adjust timing or events)
  await page.waitForTimeout(5000);  // Wait for 5 seconds to allow the speech to complete

  await browser.close();
}

const text = "Hello, I am using the browser's speech synthesis feature!";
generateSpeechFromPage('https://example.com', text);

import html
import time
import os
from datetime import datetime, timezone

import feedparser
import requests
import yfinance as yf

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")  # opsional; kalau kosong, skip AI summary

# Ganti nama model ini kalau suatu saat error "model not found" —
# cek daftar model terbaru di https://ai.google.dev
GEMINI_MODEL = "gemini-3.8-flash"
GEMINI_MAX_RETRIES = 3
GEMINI_RETRY_DELAY_SECONDS = 5

# Reuters & Bloomberg gak nyediain RSS publik resmi lagi, jadi dipakai
# trik Google News RSS yang di-filter ke domain mereka. Link hasilnya
# tetap mengarah ke artikel asli (lewat redirect Google News).
RSS_FEEDS = {
    "Crypto (CoinDesk)": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "Stock News (MarketWatch)": "https://feeds.marketwatch.com/marketwatch/topstories/",
    "Economic News (Investing.com)": "https://www.investing.com/rss/news_301.rss",
    "Reuters": "https://news.google.com/rss/search?q=site:reuters.com+economy&hl=en-US&gl=US&ceid=US:en",
    "Bloomberg": "https://news.google.com/rss/search?q=site:bloomberg.com+economy&hl=en-US&gl=US&ceid=US:en",
}
NEWS_PER_FEED = 3

MARKET_TICKERS = {
    "🟡 XAU/USD (Gold)": "XAUUSD=X",
    "📊 Nasdaq Composite": "^IXIC",
    "📉 Dow Jones": "^DJI",
}

TELEGRAM_MAX_CHARS = 3500  # dikasih margin dari limit asli 4096


def get_news(feed_url, limit=NEWS_PER_FEED):
    feed = feedparser.parse(feed_url)
    items = []
    for entry in feed.entries[:limit]:
        items.append(
            {
                "title": entry.title.strip(),
                "link": entry.link.strip(),
                "summary": getattr(entry, "summary", "").strip(),
            }
        )
    return items


def get_market_data():
    lines = []
    for name, ticker in MARKET_TICKERS.items():
        try:
            # period 5 hari biar tetap ada data walau lagi weekend/libur bursa
            data = yf.Ticker(ticker).history(period="5d")
            if len(data) >= 2:
                prev_close = float(data["Close"].iloc[-2])
                last_price = float(data["Close"].iloc[-1])
                change = last_price - prev_close
                pct = (change / prev_close) * 100
                arrow = "🟢" if change >= 0 else "🔴"
                lines.append(f"{name}: {last_price:,.2f} {arrow} ({pct:+.2f}%)")
            else:
                lines.append(f"{name}: data tidak tersedia saat ini")
        except Exception as e:
            lines.append(f"{name}: gagal ambil data ({e})")
    return lines


def summarize_with_gemini(all_news_by_category):
    if not GEMINI_API_KEY:
        return None

    prompt_parts = [
        "Rangkum berita-berita ekonomi/finansial berikut ke dalam Bahasa Indonesia, "
        "dikelompokkan per kategori, singkat dan padat (maks 2-3 kalimat per kategori), "
        "gaya bahasa netral seperti berita, TANPA markdown/HTML, TANPA tanda bintang:\n"
    ]
    for category, items in all_news_by_category.items():
        prompt_parts.append(f"\n[{category}]")
        for item in items:
            snippet = item["summary"][:200] if item["summary"] else ""
            prompt_parts.append(f"- {item['title']}. {snippet}")

    prompt = "\n".join(prompt_parts)

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )
    payload = {"contents": [{"parts": [{"text": prompt}]}]}

    last_error = None
    for attempt in range(1, GEMINI_MAX_RETRIES + 1):
        try:
            resp = requests.post(url, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except Exception as e:
            last_error = e
            # 503/429 biasanya cuma server lagi sibuk sesaat -> coba lagi
            if attempt < GEMINI_MAX_RETRIES:
                time.sleep(GEMINI_RETRY_DELAY_SECONDS)

    print(f"Gemini gagal setelah {GEMINI_MAX_RETRIES}x percobaan: {last_error}")
    return None  # skip bagian AI summary daripada nampilin error mentah ke user


def build_message_blocks():
    now = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")
    news_by_category = {name: get_news(url) for name, url in RSS_FEEDS.items()}

    blocks = [f"<b>📊 Ringkasan Ekonomi &amp; Market</b>\n<i>{now}</i>"]

    market_block = "<b>💹 Pergerakan Market</b>\n" + "\n".join(get_market_data())
    blocks.append(market_block)

    ai_summary = summarize_with_gemini(news_by_category)
    if ai_summary:
        blocks.append("<b>🧠 Rangkuman AI</b>\n" + html.escape(ai_summary))

    for category, items in news_by_category.items():
        lines = [f"<b>🔗 {html.escape(category)}</b>"]
        if items:
            for item in items:
                title = html.escape(item["title"])
                link = item["link"]
                lines.append(f'• <a href="{link}">{title}</a>')
        else:
            lines.append("Tidak ada berita baru.")
        blocks.append("\n".join(lines))

    return blocks


def chunk_blocks(blocks, max_len=TELEGRAM_MAX_CHARS):
    """Gabungin blocks jadi beberapa pesan, tanpa motong di tengah satu block
    (biar tag HTML gak pernah kepotong)."""
    chunks = []
    current = ""
    for block in blocks:
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) > max_len and current:
            chunks.append(current)
            current = block
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    response = requests.post(url, data=payload, timeout=30)
    response.raise_for_status()


if __name__ == "__main__":
    blocks = build_message_blocks()
    for chunk in chunk_blocks(blocks):
        send_telegram_message(chunk)
        time.sleep(1)  # jaga-jaga biar gak kena rate limit Telegram

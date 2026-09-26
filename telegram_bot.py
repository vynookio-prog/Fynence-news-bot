import html
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
GEMINI_MODEL = "gemini-4.8-flash"

RSS_FEEDS = {
    "Crypto (CoinDesk)": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "Stock News (MarketWatch)": "https://feeds.marketwatch.com/marketwatch/topstories/",
    "Economic News (Investing.com)": "https://www.investing.com/rss/news_301.rss",
}
NEWS_PER_FEED = 4

MARKET_TICKERS = {
    "🟡 XAU/USD (Gold)": "XAUUSD=X",
    "📊 Nasdaq Composite": "^IXIC",
    "📉 Dow Jones": "^DJI",
}


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
            data = yf.Ticker(ticker).history(period="2d")
            if len(data) >= 2:
                prev_close = float(data["Close"].iloc[-2])
                last_price = float(data["Close"].iloc[-1])
                change = last_price - prev_close
                pct = (change / prev_close) * 100
                arrow = "🟢" if change >= 0 else "🔴"
                lines.append(f"{name}: {last_price:,.2f} {arrow} ({pct:+.2f}%)")
            else:
                lines.append(f"{name}: data belum cukup")
        except Exception as e:
            lines.append(f"{name}: gagal ambil data ({e})")
    return lines


def summarize_with_gemini(all_news_by_category):
    if not GEMINI_API_KEY:
        return None

    prompt_parts = ["Rangkum berita-berita ekonomi/finansial berikut ke dalam Bahasa Indonesia, "
                    "dikelompokkan per kategori, singkat dan padat (maks 2-3 kalimat per kategori), "
                    "gaya bahasa netral seperti berita, TANPA markdown/HTML, TANPA tanda bintang:\n"]
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

    try:
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        return f"(Gagal generate summary AI: {e})"


def build_message():
    now = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")
    news_by_category = {name: get_news(url) for name, url in RSS_FEEDS.items()}

    parts = [f"<b>📊 Ringkasan Ekonomi &amp; Market</b>\n<i>{now}</i>\n"]

    parts.append("<b>💹 Pergerakan Market</b>")
    parts.append("\n".join(get_market_data()))
    parts.append("")

    ai_summary = summarize_with_gemini(news_by_category)
    if ai_summary:
        parts.append("<b>🧠 Rangkuman AI</b>")
        parts.append(html.escape(ai_summary))
        parts.append("")

    for category, items in news_by_category.items():
        parts.append(f"<b>🔗 {html.escape(category)}</b>")
        if items:
            for item in items:
                title = html.escape(item["title"])
                link = item["link"]
                parts.append(f'• <a href="{link}">{title}</a>')
        else:
            parts.append("Tidak ada berita baru.")
        parts.append("")

    return "\n".join(parts).strip()


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
    message = build_message()
    send_telegram_message(message[:4096])
    

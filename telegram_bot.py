import os
from datetime import datetime, timezone

import feedparser
import requests
import yfinance as yf

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# Sumber berita RSS (gratis, tanpa API key)
RSS_FEEDS = {
    "🪙 Crypto (CoinDesk)": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "📈 Stock News (MarketWatch)": "https://feeds.marketwatch.com/marketwatch/topstories/",
    "🌍 Economic News (Investing.com)": "https://www.investing.com/rss/news_301.rss",
}
NEWS_PER_FEED = 3

# Ticker market yang dipantau (via Yahoo Finance, gratis)
MARKET_TICKERS = {
    "🟡 XAU/USD (Gold)": "XAUUSD=X",
    "📊 Nasdaq Composite": "^IXIC",
    "📉 Dow Jones": "^DJI",
}


def get_news(feed_url, limit=NEWS_PER_FEED):
    feed = feedparser.parse(feed_url)
    items = []
    for entry in feed.entries[:limit]:
        title = entry.title.strip()
        link = entry.link.strip()
        items.append(f'• <a href="{link}">{title}</a>')
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


def build_message():
    now = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")
    parts = [f"<b>📊 Ringkasan Ekonomi &amp; Market</b>\n<i>{now}</i>\n"]

    parts.append("<b>💹 Pergerakan Market</b>")
    parts.append("\n".join(get_market_data()))
    parts.append("")  # spacer

    for section, url in RSS_FEEDS.items():
        parts.append(f"<b>{section}</b>")
        news_items = get_news(url)
        parts.append("\n".join(news_items) if news_items else "Tidak ada berita baru.")
        parts.append("")  # spacer

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
    # Telegram batasi 4096 karakter per pesan; potong kalau kepanjangan
    send_telegram_message(message[:4096])

import os
import feedparser
import google.generativeai as genai
from linebot import LineBotApi
from linebot.models import TextSendMessage
import yfinance as yf
import pandas as pd
from datetime import datetime
import pytz
import time

# --- 設定環境變數 ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
LINE_TOKEN = os.environ.get("LINE_TOKEN", "").strip()
GROUP_ID = os.environ.get("GROUP_ID", "").strip()

# ==========================================
# 🔴 第一部分：原有的台美股戰報 (保持不變)
# ==========================================

# --- 監控清單 ---
US_WATCHLIST = ["NVDA", "TSLA", "AAPL", "AMD", "MSFT", "GOOG", "AMZN", "META", "TQQQ", "SOXL"]

# --- 台美股新聞來源 ---
MARKET_RSS_URLS = [
    "https://www.cnbc.com/id/10000664/device/rss/rss.html",
    "https://feeds.content.dowjones.com/public/rss/mw_topstories",
    "https://news.cnyes.com/rss/cat/tw_stock",
    "https://news.google.com/rss/search?q=張震+股市+when:1d&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=萬寶投顧+when:1d&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=先探+when:1d&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
]

def calculate_rsi(data, window=14):
    delta = data.diff()
    gain = (delta.where(delta > 0, 0)).fillna(0)
    loss = (-delta.where(delta < 0, 0)).fillna(0)
    avg_gain = gain.ewm(com=window-1, min_periods=window).mean()
    avg_loss = loss.ewm(com=window-1, min_periods=window).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def get_market_data():
    signals = []
    tw_summary = ""
    print("正在分析市場數據 (第一戰報)...")
    
    # 1. 美股
    for ticker in US_WATCHLIST:
        try:
            df = yf.download(ticker, period="3mo", interval="1d", progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            if len(df) < 20: continue 

            df['RSI'] = calculate_rsi(df['Close'])
            rsi = float(df['RSI'].iloc[-1]) if not pd.isna(df['RSI'].iloc[-1]) else 50
            
            current_vol = float(df['Volume'].iloc[-1])
            avg_vol = float(df['Volume'].rolling(window=5).mean().iloc[-1])
            vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1.0

            ticker_signals = []
            if rsi > 75: ticker_signals.append(f"⚠️過熱(RSI{rsi:.0f})")
            elif rsi < 25: ticker_signals.append(f"💎超跌(RSI{rsi:.0f})")
            if vol_ratio > 2.0: ticker_signals.append(f"🔥爆量({vol_ratio:.1f}倍)")

            if ticker_signals:
                signals.append(f"{ticker}: {' '.join(ticker_signals)}")
        except: continue

    # 2. 台股
    try:
        twii = yf.download("^TWII", period="5d", progress=False)
        if isinstance(twii.columns, pd.MultiIndex):
            twii.columns = twii.columns.get_level_values(0)
        
        if len(twii) >= 2:
            change = twii['Close'].iloc[-1] - twii['Close'].iloc[-2]
            pct_change = (change / twii['Close'].iloc[-2]) * 100
            tw_summary = f"台股昨收漲跌 {change:+.0f} 點 ({pct_change:+.2f}%)"
        else: tw_summary = "資料不足"
    except: tw_summary = "無法取得數據"

    tech_report = "\n".join(signals) if signals else "無特殊異常。"
    return tech_report, tw_summary

def get_market_news():
    content = ""
    try:
        for url in MARKET_RSS_URLS:
            feed = feedparser.parse(url)
            for entry in feed.entries[:3]: 
                if len(entry.title) > 5: content += f"- {entry.title}\n"
    except: pass
    return content

def generate_stock_report():
    raw_news = get_market_news()
    us_signals, tw_info = get_market_data()
    tw_time = datetime.now(pytz.timezone('Asia/Taipei')).strftime('%Y/%m/%d')
    
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    prompt = f"""
    你是嚴謹的台股分析師。請撰寫戰報。
    資料A: {tw_info}
    資料B: {us_signals}
    資料C: {raw_news}

    請特別過濾資料C中「張震、萬寶、先探」的觀點。
    
    格式:
    📊 **台美股戰報** ({tw_time})
    **1. 盤勢重點**: (一句話)
    **2. 名師觀點**:
    * 張震: (無則省略)
    * 萬寶: (無則省略)
    * 先探: (無則省略)
    **3. 焦點族群**: (點名板塊)
    **4. 操盤錦囊**: (一句話建議)
    """
    return model.generate_content(prompt).text

# ==========================================
# 🔵 第二部分：新增「理財達人秀」專屬總結
# ==========================================

# --- 達人秀專屬追蹤源 ---
SHOW_RSS_URLS = [
    # 追蹤節目本身的標題 (YouTube & Google News)
    "https://news.google.com/rss/search?q=理財達人秀+when:1d&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    # 追蹤特定人物 (加上 '股市' 避免抓到同名同姓)
    "https://news.google.com/rss/search?q=李兆華+股市+when:1d&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=權證小哥+when:1d&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=艾倫+股市+when:1d&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
]

def get_show_news():
    content = ""
    print("正在抓取理財達人秀資訊...")
    try:
        for url in SHOW_RSS_URLS:
            feed = feedparser.parse(url)
            for entry in feed.entries[:3]: # 每個關鍵字抓前3則
                if len(entry.title) > 5:
                    content += f"- {entry.title}\n"
    except Exception as e:
        print(f"抓取達人秀失敗: {e}")
    return content

def generate_show_report():
    raw_data = get_show_news()
    
    # 如果完全沒抓到資料 (可能週末沒錄影)，就回傳 None，避免發送空訊息
    if not raw_data:
        print("今日無達人秀相關新聞，跳過發送。")
        return None

    print("呼叫 Gemini 分析達人秀...")
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    prompt = f"""
    你是一位「理財達人秀」的忠實觀眾與筆記整理者。請根據以下網路上抓取的最新節目相關資訊，整理昨日精華。

    【擷取資訊】
    {raw_data}

    【任務目標】
    請針對「李兆華 (主持人)」、「權證小哥」、「艾倫」這三位關鍵人物進行分析。
    
    ⚠️ **注意事項**：
    1. 若資訊中包含該人物的具體分析（如小哥的籌碼、艾倫的產業），請重點摘要。
    2. 若某位達人今日無相關資訊，請該欄位留白或寫「今日無重點」，**不要瞎掰**。
    3. 語氣要像節目小編，輕鬆但有重點。

    ---
    **格式如下 (繁體中文)**：

    📺 **理財達人秀：昨日精華筆記**

    🔥 **本集熱門主題**：
    (根據標題總結昨日討論重點，例如：AI復活? 航運噴出?)

    💡 **達人觀點透視**：
    🔹 **權證小哥**：(專注籌碼/技術面分析)
    🔹 **艾倫分析師**：(專注產業/個股分析)
    🔹 **李兆華**：(主持人觀點或總結)

    📝 **重點總結**：
    (一句話總結昨日節目的核心結論)
    """
    
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"達人秀分析失敗: {e}")
        return None

# ==========================================
# 🚀 主程式：依序執行兩個任務
# ==========================================

def send_line_push(content):
    line_bot_api = LineBotApi(LINE_TOKEN)
    line_bot_api.push_message(GROUP_ID, TextSendMessage(text=content))

if __name__ == "__main__":
    # --- 任務 1：發送原本的台美股戰報 ---
    try:
        print("--- 開始執行任務 1：台美股戰報 ---")
        report1 = generate_stock_report()
        send_line_push(report1)
        print("✅ 第一則戰報發送成功！")
    except Exception as e:
        print(f"❌ 第一則戰報失敗: {e}")

    # 休息 3 秒，避免訊息黏在一起，或 API 請求太快
    time.sleep(3)

    # --- 任務 2：發送理財達人秀戰報 ---
    try:
        print("--- 開始執行任務 2：理財達人秀 ---")
        report2 = generate_show_report()
        
        if report2: # 只有在有內容時才發送
            send_line_push(report2)
            print("✅ 第二則戰報 (達人秀) 發送成功！")
        else:
            print("⚠️ 今日無達人秀內容，跳過發送。")
            
    except Exception as e:
        print(f"❌ 第二則戰報失敗: {e}")

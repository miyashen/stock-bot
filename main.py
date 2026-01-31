import os
import feedparser
import google.generativeai as genai
from linebot import LineBotApi
from linebot.models import TextSendMessage
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import pytz
import time

# --- 設定環境變數 ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
LINE_TOKEN = os.environ.get("LINE_TOKEN", "").strip()
GROUP_ID = os.environ.get("GROUP_ID", "").strip()

# ==========================================
# 🔴 第一部分：台美股戰報 (維持不變)
# ==========================================
US_WATCHLIST = ["NVDA", "TSLA", "AAPL", "AMD", "MSFT", "GOOG", "AMZN", "META", "TQQQ", "SOXL"]
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
    請過濾張震、萬寶、先探觀點。
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
# 🔵 第二部分：理財達人秀 (Google 搜尋工具版 🔍)
# ==========================================

def generate_show_report_via_search():
    print("🔍 啟動 Google 搜尋引擎，搜尋最新節目資訊...")
    
    # 1. 計算日期，確保搜到的是「最新」的
    tw_now = datetime.now(pytz.timezone('Asia/Taipei'))
    today_str = tw_now.strftime('%Y-%m-%d')
    yesterday_str = (tw_now - timedelta(days=1)).strftime('%Y-%m-%d')
    
    # 2. 設定搜尋關鍵字 (這就像你在 Google 搜尋欄打字一樣)
    search_query = f"理財達人秀 {yesterday_str} {today_str} 重點 李兆華 權證小哥 艾倫"
    
    genai.configure(api_key=GEMINI_API_KEY)
    
    # 🌟 關鍵魔法：啟用 Google Search 工具
    # 這會讓 Gemini 擁有「上網搜尋」的能力，就像 NotebookLM 一樣
    tools = [
        {'google_search_retrieval': {
            'dynamic_retrieval_config': {
                'mode': 'dynamic',
                'dynamic_threshold': 0.3,
            }
        }}
    ]
    
    model = genai.GenerativeModel('gemini-2.5-flash', tools=tools)
    
    prompt = f"""
    請利用 Google 搜尋功能，查找「理財達人秀」最近一集(昨日或今日)的節目內容。
    搜尋關鍵字建議："{search_query}"
    
    【任務目標】
    請根據搜尋到的最新資訊 (包含影片標題、新聞報導、社群討論)，整理出精華筆記。
    
    重點分析人物：
    1. **權證小哥**：是否有提到特定籌碼、分點或個股？
    2. **艾倫 (Allen)**：看好什麼產業或題材？
    3. **李兆華**：本集討論的主題是什麼？

    ⚠️ **嚴格規定**：
    * **必須真實**：完全基於搜尋結果，如果搜尋結果沒有提到某人的觀點，請寫「本集無相關資訊」。
    * **不要瞎掰**：如果找不到最新的，請誠實回報「找不到今日最新節目資訊」。

    ---
    **格式 (繁體中文)**：

    📺 **理財達人秀：昨日精華筆記**
    (日期：{yesterday_str} ~ {today_str})

    💡 **達人觀點透視**：
    🔹 **權證小哥**：(搜尋到的重點)
    🔹 **艾倫分析師**：(搜尋到的重點)
    🔹 **李兆華 (主題)**：(搜尋到的重點)

    📝 **綜合觀察**：(一句話總結搜尋到的市場氣氛)
    """
    
    try:
        response = model.generate_content(prompt)
        # 檢查是否有內容 (避免搜尋失敗回傳空值)
        if not response.text or "找不到" in response.text:
            print("搜尋結果不足，跳過發送。")
            return None
            
        return response.text
    except Exception as e:
        print(f"Gemini 搜尋分析失敗: {e}")
        return None

# ==========================================
# 🚀 主程式
# ==========================================
def send_line_push(content):
    line_bot_api = LineBotApi(LINE_TOKEN)
    line_bot_api.push_message(GROUP_ID, TextSendMessage(text=content))

if __name__ == "__main__":
    # --- 任務 1 ---
    try:
        print("--- 任務 1：台美股戰報 ---")
        report1 = generate_stock_report()
        send_line_push(report1)
        print("✅ 戰報發送成功！")
    except Exception as e:
        print(f"❌ 戰報失敗: {e}")

    time.sleep(5)

    # --- 任務 2 ---
    try:
        print("--- 任務 2：理財達人秀 (搜尋版) ---")
        report2 = generate_show_report_via_search()
        
        if report2:
            send_line_push(report2)
            print("✅ 達人秀筆記發送成功！")
        else:
            print("⚠️ 無法產生筆記 (可能無新資訊)")
            
    except Exception as e:
        print(f"❌ 達人秀失敗: {e}")

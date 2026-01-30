import os
import feedparser
import google.generativeai as genai
from linebot import LineBotApi
from linebot.models import TextSendMessage
import yfinance as yf
import pandas as pd
from datetime import datetime
import pytz

# --- 設定環境變數 ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
LINE_TOKEN = os.environ.get("LINE_TOKEN", "").strip()
GROUP_ID = os.environ.get("GROUP_ID", "").strip()

# --- 設定監控清單 ---
# 美股監控
US_WATCHLIST = ["NVDA", "TSLA", "AAPL", "AMD", "MSFT", "GOOG", "AMZN", "META", "TQQQ", "SOXL"]

# --- 新聞來源 (新增台灣鉅亨網) ---
RSS_URLS = [
    "https://www.cnbc.com/id/10000664/device/rss/rss.html",       # 美股財經
    "https://feeds.content.dowjones.com/public/rss/mw_topstories", # MarketWatch
    "https://news.cnyes.com/rss/cat/tw_stock"                     # 台股鉅亨網
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
    """抓取美股監控 + 台股大盤資訊"""
    signals = []
    tw_summary = ""
    print("正在分析市場數據...")
    
    # 1. 分析美股個股
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

        except Exception as e:
            print(f"分析 {ticker} 失敗: {e}")
            continue

    # 2. 抓取台股大盤 (加權指數) 昨收資訊
    try:
        twii = yf.download("^TWII", period="5d", progress=False)
        if isinstance(twii.columns, pd.MultiIndex):
            twii.columns = twii.columns.get_level_values(0)
            
        close_price = twii['Close'].iloc[-1]
        change = twii['Close'].iloc[-1] - twii['Close'].iloc[-2]
        pct_change = (change / twii['Close'].iloc[-2]) * 100
        
        tw_summary = f"台股加權指數昨收 {close_price:.0f} 點，漲跌 {change:+.0f} 點 ({pct_change:+.2f}%)"
    except Exception as e:
        tw_summary = "無法取得台股大盤數據"
        print(f"台股抓取失敗: {e}")

    tech_report = "\n".join(signals) if signals else "美股監控名單無特殊異常。"
    return tech_report, tw_summary

def get_news():
    news_content = ""
    print("正在抓取全球與台股新聞...")
    try:
        for url in RSS_URLS:
            feed = feedparser.parse(url)
            # 每個來源抓前 4 則，增加資訊量
            for entry in feed.entries[:4]: 
                news_content += f"- {entry.title}\n"
    except Exception as e:
        print(f"抓新聞錯誤: {e}")
    return news_content

def generate_report():
    raw_news = get_news()
    us_tech_signals, tw_market_info = get_market_data()
    tw_time = datetime.now(pytz.timezone('Asia/Taipei')).strftime('%Y/%m/%d')

    print("呼叫 Gemini 分析中...")
    if not GEMINI_API_KEY:
        raise ValueError("GitHub Secrets 沒有成功傳遞 GEMINI_API_KEY")

    genai.configure(api_key=GEMINI_API_KEY)
    
    # 使用你最強的 gemini-2.5-flash
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    prompt = f"""
    你是一位精通台美股連動的資深分析師。請根據以下資料，撰寫一份給台灣投資人的「每日晨間戰報」。

    【資料 A：昨日台股大盤】
    {tw_market_info}

    【資料 B：美股技術面異常訊號】
    {us_tech_signals}

    【資料 C：全球與台股最新新聞標題】
    {raw_news}

    ---
    **撰寫規則 (請嚴格遵守)：**
    1. **繁體中文**撰寫，語氣專業、簡潔、有洞見。
    2. **台美連動分析**：請根據美股昨晚表現 (如 NVDA 漲跌)，推論今日台股相關族群 (如 AI 概念股) 的可能走勢。
    3. 格式如下：

    📊 **台美股晨間戰報** ({tw_time})

    **1. 昨日台股回顧**：
    (簡短總結昨日加權指數表現與強勢族群)

    **2. 美股隔夜風向**：
    (總結美股氣氛，並列出【資料 B】中有出現異常訊號的股票，若無則寫觀望)

    **3. 今日台股看點 (重點)**：
    (結合美股走勢與新聞，分析今日台股該注意的「板塊」或「產業」。例如：美股科技股大跌，今日台股電子股恐承壓...)

    **4. 操作建議**：
    (給散戶的一句話策略，例如：短線勿追高、留意低接機會等)
    """
    
    response = model.generate_content(prompt)
    return response.text

def send_line_push(content):
    line_bot_api = LineBotApi(LINE_TOKEN)
    line_bot_api.push_message(GROUP_ID, TextSendMessage(text=content))

if __name__ == "__main__":
    try:
        report = generate_report()
        send_line_push(report)
        print("發送成功！")
    except Exception as e:
        print(f"執行失敗: {e}")

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
US_WATCHLIST = ["NVDA", "TSLA", "AAPL", "AMD", "MSFT", "GOOG", "AMZN", "META", "TQQQ", "SOXL"]

# --- 新聞來源 (新增名師追蹤) ---
RSS_URLS = [
    # 1. 國際財經
    "https://www.cnbc.com/id/10000664/device/rss/rss.html",
    "https://feeds.content.dowjones.com/public/rss/mw_topstories",
    # 2. 台股新聞 (鉅亨網)
    "https://news.cnyes.com/rss/cat/tw_stock",
    # 3. 名師與機構 (使用 Google News 關鍵字追蹤)
    "https://news.google.com/rss/search?q=張震+股市&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=萬寶投顧&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=先探&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
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
    print("正在分析市場數據...")
    
    # 1. 美股技術分析
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

    # 2. 台股大盤
    try:
        twii = yf.download("^TWII", period="5d", progress=False)
        if isinstance(twii.columns, pd.MultiIndex):
            twii.columns = twii.columns.get_level_values(0)
        
        if len(twii) >= 2:
            close_price = twii['Close'].iloc[-1]
            change = twii['Close'].iloc[-1] - twii['Close'].iloc[-2]
            pct_change = (change / twii['Close'].iloc[-2]) * 100
            tw_summary = f"台股加權指數昨收 {close_price:.0f} 點，漲跌 {change:+.0f} 點 ({pct_change:+.2f}%)"
        else:
            tw_summary = "台股大盤資料不足"
            
    except Exception as e:
        tw_summary = "無法取得台股大盤數據"
        print(f"台股抓取失敗: {e}")

    tech_report = "\n".join(signals) if signals else "美股監控名單無特殊異常。"
    return tech_report, tw_summary

def get_news():
    news_content = ""
    print("正在抓取新聞與名師觀點...")
    try:
        for url in RSS_URLS:
            feed = feedparser.parse(url)
            # 每個來源抓前 3 則，名師的新聞通常比較少，這樣可以確保抓到最新的
            for entry in feed.entries[:3]: 
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
    
    # 使用最強的 gemini-2.5-flash
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    prompt = f"""
    你是一位精通「籌碼分析」與「技術面」的台股資深操盤手。請撰寫一份戰報。

    【資料來源】
    A. 台股昨日大盤：{tw_market_info}
    B. 美股異常訊號：{us_tech_signals}
    C. 市場新聞與名師觀點：{raw_news}

    【任務重點】
    請特別從「資料 C」中搜尋以下關鍵字的相關看法，並整合在報告中：
    1. **張震 (股市MBA)**：通常強調技術型態與位階。
    2. **萬寶投顧**：通常分析主力籌碼與熱門題材。
    3. **先探財訊**：通常深入產業趨勢。

    ---
    **戰報格式 (請繁體中文撰寫)：**

    📊 **台美股戰報** ({tw_time})

    **1. 盤勢重點**：
    (結合台股大盤 {tw_market_info} 與美股氣氛，給出一句定調)

    **2. 名師與機構觀點 (精華)**：
    * **張震/技術面**：(若有相關新聞，總結他的看法；若無，請省略)
    * **萬寶/籌碼面**：(若有相關新聞，總結看好哪些族群；若無，請省略)
    * **先探/產業面**：(若有相關新聞，提煉產業重點；若無，請省略)

    **3. 今日焦點族群**：
    (根據美股表現與上述名師觀點，點名今日可留意的板塊)

    **4. 操盤錦囊**：
    (給散戶的一個具體操作建議)
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

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
# 使用 strip() 確保沒有因為複製貼上產生的多餘空白
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
LINE_TOKEN = os.environ.get("LINE_TOKEN", "").strip()
GROUP_ID = os.environ.get("GROUP_ID", "").strip()

# --- 設定 ---
WATCHLIST = ["NVDA", "TSLA", "AAPL", "AMD", "MSFT", "GOOG", "AMZN", "META", "TQQQ", "SOXL"]
RSS_URLS = [
    "https://www.cnbc.com/id/10000664/device/rss/rss.html",
    "https://feeds.content.dowjones.com/public/rss/mw_topstories"
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

def get_technical_analysis():
    signals = []
    print("正在分析技術指標...")
    
    for ticker in WATCHLIST:
        try:
            # 抓取資料
            df = yf.download(ticker, period="3mo", interval="1d", progress=False)
            
            # 處理 yfinance 新版多層索引問題
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            if len(df) < 20: continue 

            # 手動計算指標
            df['RSI'] = calculate_rsi(df['Close'])
            
            # 確保取出的是純數字
            rsi_val = df['RSI'].iloc[-1]
            if pd.isna(rsi_val): continue
            rsi = float(rsi_val)
            
            current_vol = float(df['Volume'].iloc[-1])
            avg_vol = float(df['Volume'].rolling(window=5).mean().iloc[-1])
            
            vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1.0

            # 判斷訊號
            ticker_signals = []
            
            if rsi > 75:
                ticker_signals.append(f"⚠️ 買盤竭盡 (RSI {rsi:.0f})")
            elif rsi < 25:
                ticker_signals.append(f"💎 賣盤竭盡 (RSI {rsi:.0f})")
                
            if vol_ratio > 2.0:
                ticker_signals.append(f"🔥 大單灌入 (量增 {vol_ratio:.1f}倍)")

            if ticker_signals:
                signals.append(f"【{ticker}】: {' '.join(ticker_signals)}")

        except Exception as e:
            print(f"分析 {ticker} 失敗: {e}")
            continue

    if not signals:
        return "今日監控名單籌碼穩定，無特殊異常訊號。"
    return "\n".join(signals)

def get_news():
    news_content = ""
    print("正在抓取新聞...")
    try:
        for url in RSS_URLS:
            feed = feedparser.parse(url)
            for entry in feed.entries[:3]:
                news_content += f"- {entry.title}\n"
    except Exception as e:
        print(f"抓新聞錯誤: {e}")
    return news_content

def generate_report():
    raw_news = get_news()
    tech_signals = get_technical_analysis()
    tw_time = datetime.now(pytz.timezone('Asia/Taipei')).strftime('%Y/%m/%d')

    print("呼叫 Gemini 分析中...")
    if not GEMINI_API_KEY:
        raise ValueError("GitHub Secrets 沒有成功傳遞 GEMINI_API_KEY")

    genai.configure(api_key=GEMINI_API_KEY)
    
    # 🌟【關鍵修改】改用你清單裡有的最強模型 gemini-2.5-flash
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    prompt = f"""
    你是華爾街資深交易員。請根據以下資料，為 LINE 群組撰寫一份「美股晨間戰報」。
    
    【資料 A：昨晚重點新聞標題】
    {raw_news}
    
    【資料 B：技術面監控訊號 (RSI/爆量)】
    {tech_signals}
    
    ---
    請以「繁體中文」撰寫，語氣專業、簡潔，適合手機閱讀。
    格式如下：
    
    📊 **美股晨間戰報** ({tw_time})
    
    **1. 市場風向**：(一句話總結)
    **2. 焦點新聞**：(挑選 2 則並解讀)
    **3. 技術面異常**：(整理資料 B，若無則寫觀察名單平穩)
    **4. 操作建議**：(一句話建議)
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

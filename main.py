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
import json

# --- 新增的套件 ---
import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi

# --- 設定環境變數 ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
LINE_TOKEN = os.environ.get("LINE_TOKEN", "").strip()
GROUP_ID = os.environ.get("GROUP_ID", "").strip()

# ==========================================
# 🔴 第一部分：原有的台美股戰報
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
# 🔵 第二部分：理財達人秀 (yt-dlp 強化搜尋版)
# ==========================================

def get_youtube_transcript():
    """使用 yt-dlp 搜尋理財達人秀最新影片並抓取字幕"""
    print("正在搜尋 YouTube 最新影片...")
    
    # 設定 yt-dlp 搜尋參數
    ydl_opts = {
        'default_search': 'ytsearch1', # 只搜尋 1 筆結果
        'quiet': True,                 # 安靜模式，不印出一大堆下載進度
        'extract_flat': True,          # 快速抓取標題就好，不要真的下載影片
        'noplaylist': True,
    }

    try:
        # 1. 搜尋影片
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # 搜尋關鍵字：理財達人秀 (它會自動找最相關/最新的)
            info = ydl.extract_info("理財達人秀", download=False)
            
            if 'entries' not in info or not info['entries']:
                return None, None, "找不到影片"
            
            video_info = info['entries'][0]
            video_id = video_info['id']
            video_title = video_info['title']
            video_url = video_info['url']
            
            print(f"找到影片: {video_title} (ID: {video_id})")

        # 2. 抓取字幕 (使用 youtube_transcript_api)
        # 嘗試順序：繁體中文 -> 簡體中文 -> 自動產生
        try:
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['zh-TW', 'zh-Hant', 'zh', 'zh-Hans'])
        except:
            print("無標準中文字幕，嘗試抓取自動產生的字幕...")
            try:
                # 如果沒有手動字幕，列出所有可用字幕並選第一個
                transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
            except Exception as e:
                print(f"無法取得任何字幕: {e}")
                return None, video_title, "本集無字幕可供分析"

        # 3. 組合字幕文字
        full_text = " ".join([t['text'] for t in transcript_list])
        
        # 限制長度，只取前 25000 字 (通常夠了，且不會爆 Token)
        return full_text[:25000], video_title, video_url

    except Exception as e:
        print(f"YouTube 處理失敗: {e}")
        return None, None, None

def generate_show_report():
    # 取得字幕
    transcript, title, url = get_youtube_transcript()
    
    if not transcript:
        print("今日無有效字幕資料，跳過。")
        return None

    print("呼叫 Gemini 閱讀字幕中...")
    genai.configure(api_key=GEMINI_API_KEY)
    # 使用 2.5-flash，吞吐量大，適合讀長文
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    prompt = f"""
    你是一位專業的財經節目筆記整理者。請閱讀以下「理財達人秀」的完整節目逐字稿，整理出精華重點。

    【節目資訊】
    標題：{title}
    連結：{url}

    【逐字稿內容 (部分)】
    {transcript}

    ---
    【任務目標】
    請根據逐字稿內容，深度分析以下來賓的觀點。如果逐字稿中沒有明確標示人名，請根據對話內容推測（通常李兆華是主持人，負責提問）。
    
    1. **權證小哥**：專注於「籌碼動向」、「主力進出」、「分點券商」或「特殊技術型態」。
    2. **艾倫 (Allen)**：專注於「產業趨勢」、「基本面」或「個股題材」。
    3. **李兆華**：整理她強調的今日市場氛圍或總結。

    ⚠️ **嚴格規定**：
    * **必須有乾貨**：不要寫「小哥分析了股市」，要寫「小哥指出XX股票主力大買...」、「艾倫看好散熱族群...」。
    * **如果某人沒來**：如果整篇稿子都沒出現某位達人，請誠實標註「本集未出席」。
    * **不要瞎掰**：只根據逐字稿內容撰寫。

    ---
    **格式如下 (繁體中文)**：

    📺 **理財達人秀：昨日精華筆記**
    ({title})

    💡 **達人觀點透視**：
    🔹 **權證小哥**：
    (請列出具體分析，例如看好的個股、觀察到的籌碼異常)
    
    🔹 **艾倫分析師**：
    (請列出看好的產業或個股理由)
    
    🔹 **李兆華 (總結)**：
    (本集核心結論)

    🔗 **觀看連結**：{url}
    """
    
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"分析失敗: {e}")
        return None

# ==========================================
# 🚀 主程式
# ==========================================
def send_line_push(content):
    line_bot_api = LineBotApi(LINE_TOKEN)
    line_bot_api.push_message(GROUP_ID, TextSendMessage(text=content))

if __name__ == "__main__":
    # --- 任務 1：台美股戰報 ---
    try:
        print("--- 任務 1：台美股戰報 ---")
        report1 = generate_stock_report()
        send_line_push(report1)
        print("✅ 戰報發送成功！")
    except Exception as e:
        print(f"❌ 戰報失敗: {e}")

    time.sleep(5) # 休息一下，避免連續發送

    # --- 任務 2：達人秀字幕分析 ---
    try:
        print("--- 任務 2：理財達人秀 (字幕版) ---")
        report2 = generate_show_report()
        
        if report2:
            send_line_push(report2)
            print("✅ 達人秀筆記發送成功！")
        else:
            print("⚠️ 無法產生達人秀筆記 (可能無字幕或無影片)")
            
    except Exception as e:
        print(f"❌ 達人秀失敗: {e}")

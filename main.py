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
import yt_dlp

# --- 設定環境變數 ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
LINE_TOKEN = os.environ.get("LINE_TOKEN", "").strip()
GROUP_ID = os.environ.get("GROUP_ID", "").strip()

# ==========================================
# 🔴 第一部分：台美股戰報 (保持不變)
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
# 🔵 第二部分：理財達人秀 (音訊分析版 🎧)
# ==========================================

def download_audio():
    """下載最新一集影片的音軌 (MP3)"""
    print("🎧 正在搜尋並下載理財達人秀音檔...")
    
    # 目標：理財達人秀官方頻道的最新影片
    TARGET_URL = "https://www.youtube.com/@moneymaker48/videos"
    OUTPUT_FILENAME = "show_audio.mp3"

    # 清理舊檔案
    if os.path.exists(OUTPUT_FILENAME):
        os.remove(OUTPUT_FILENAME)

    ydl_opts = {
        'format': 'bestaudio/best', # 只下載音訊，體積小
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '128', # 128k 對語音識別已足夠
        }],
        'outtmpl': 'show_audio', # 檔名範本 (yt-dlp 會自動加 .mp3)
        'playlistend': 1,     # 只抓最新一集
        'quiet': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # 1. 先抓資訊
            info = ydl.extract_info(TARGET_URL, download=False)
            if 'entries' not in info or not info['entries']:
                return None, None, "找不到影片"
            
            video_info = info['entries'][0]
            title = video_info['title']
            url = f"https://www.youtube.com/watch?v={video_info['id']}"
            print(f"🎯 鎖定影片: {title}")

            # 2. 開始下載
            print("🚀 開始下載音訊 (這可能需要幾秒鐘)...")
            ydl.download([url])
            
            # 確認檔案是否存在
            if os.path.exists(OUTPUT_FILENAME):
                print(f"✅ 音訊下載完成: {os.path.getsize(OUTPUT_FILENAME) / 1024 / 1024:.2f} MB")
                return OUTPUT_FILENAME, title, url
            else:
                return None, title, "下載失敗，檔案未生成"

    except Exception as e:
        print(f"❌ 下載流程失敗: {e}")
        return None, None, None

def generate_audio_report():
    audio_path, title, url = download_audio()
    
    if not audio_path:
        print("無法取得音檔，跳過分析。")
        return None

    print("📤 上傳音檔至 Gemini...")
    genai.configure(api_key=GEMINI_API_KEY)
    
    try:
        # 1. 上傳檔案
        audio_file = genai.upload_file(path=audio_path)
        print(f"✅ 上傳成功，檔案 ID: {audio_file.name}")

        # 2. 等待檔案處理 (Google 需要一點時間處理音訊)
        print("⏳ 等待 AI 處理音訊中...")
        while audio_file.state.name == "PROCESSING":
            time.sleep(5)
            audio_file = genai.get_file(audio_file.name)
        
        if audio_file.state.name == "FAILED":
            raise ValueError("音訊處理失敗")

        # 3. 呼叫 Gemini 聽音檔
        print("🎧 Gemini 正在聆聽並做筆記...")
        model = genai.GenerativeModel('gemini-2.5-flash') # 支援多模態
        
        prompt = f"""
        你是一位專業的財經節目筆記整理者。請「仔細聆聽」這段「理財達人秀」的節目錄音，整理出精華重點。
        
        【節目資訊】
        標題：{title}
        連結：{url}

        【任務目標】
        請針對以下人物的發言進行深度分析。若是多人對話，請根據聲線與內容推測（女主持人是李兆華）。
        
        1. **權證小哥**：重點在籌碼、分點券商、特殊型態。
        2. **艾倫 (Allen)**：重點在產業趨勢、題材。
        3. **李兆華**：市場氛圍總結。

        ⚠️ **嚴格規定**：
        * **必須有乾貨**：不要寫「小哥分析了股市」，要寫「小哥指出XX股票主力大買...」。
        * **誠實標註**：如果沒聽到某人的聲音，請寫「本集未出席」。

        ---
        **格式 (繁體中文)**：

        📺 **理財達人秀：昨日精華筆記**
        ({title})

        💡 **達人觀點透視**：
        🔹 **權證小哥**：
        (聽到的重點摘要)
        
        🔹 **艾倫分析師**：
        (聽到的重點摘要)
        
        🔹 **李兆華 (總結)**：
        (聽到的重點摘要)

        🔗 **觀看連結**：{url}
        """

        response = model.generate_content([prompt, audio_file])
        
        # 4. 清理雲端檔案 (省空間)
        genai.delete_file(audio_file.name)
        
        return response.text

    except Exception as e:
        print(f"❌ Gemini 分析失敗: {e}")
        return None
    finally:
        # 清理本地檔案
        if os.path.exists(audio_path):
            os.remove(audio_path)

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
        print("--- 任務 2：理財達人秀 (音訊版) ---")
        report2 = generate_audio_report()
        
        if report2:
            send_line_push(report2)
            print("✅ 達人秀筆記發送成功！")
        else:
            print("⚠️ 無法產生筆記")
            
    except Exception as e:
        print(f"❌ 達人秀失敗: {e}")

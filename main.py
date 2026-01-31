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
import requests

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
    "https://news.cnyes.com/rss/cat/tw_stock"
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
            ticker_signals = []
            if rsi > 75: ticker_signals.append(f"⚠️過熱({rsi:.0f})")
            elif rsi < 25: ticker_signals.append(f"💎超跌({rsi:.0f})")
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
            for entry in feed.entries[:2]: 
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
    格式:
    📊 **台美股戰報** ({tw_time})
    **1. 盤勢重點**: (一句話)
    **2. 焦點族群**: (點名板塊)
    **3. 操盤錦囊**: (一句話建議)
    """
    return model.generate_content(prompt).text

# ==========================================
# 🔵 第二部分：雙 Podcast 聽力分析版 🎧
# ==========================================

# 🎙️ 節目清單 (這裡設定了你要的兩個節目)
PODCASTS = [
    {
        "name": "兆華與股惑仔",
        "rss": "https://feeds.soundon.fm/podcasts/91be014b-9f55-4bf3-a910-b232eda82d11.xml",
        "prompt_role": "請重點分析主持人李兆華與來賓對『台股盤勢』與『個股』的看法。"
    },
    {
        "name": "股癌 Gooaye",
        "rss": "https://feeds.soundon.fm/podcasts/954689a5-3096-43a4-a80b-7810b219cef3.xml",
        "prompt_role": "請重點分析謝孟恭(主委)對『市場大方向』、『科技產業趨勢』的犀利觀點。"
    }
]

def get_latest_episode(rss_url):
    try:
        feed = feedparser.parse(rss_url)
        if not feed.entries: return None, None, None
        
        entry = feed.entries[0] # 最新的一集
        title = entry.title
        link = entry.link
        
        # 找 MP3 連結
        mp3_url = None
        for enclosure in feed.entries[0].get('enclosures', []):
            if 'audio' in enclosure.get('type', ''):
                mp3_url = enclosure.get('href')
                break
        
        return mp3_url, title, link
    except: return None, None, None

def download_mp3(url, filename="temp_podcast.mp3"):
    print(f"🚀 下載音訊中... (來源: {url[:30]}...)")
    try:
        r = requests.get(url, stream=True)
        with open(filename, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024*1024):
                if chunk: f.write(chunk)
        return True
    except Exception as e:
        print(f"下載失敗: {e}")
        return False

def analyze_podcast(podcast_config):
    name = podcast_config['name']
    rss = podcast_config['rss']
    role_prompt = podcast_config['prompt_role']
    
    print(f"🎧 正在檢查節目：{name} ...")
    mp3_url, title, link = get_latest_episode(rss)
    
    if not mp3_url:
        print(f"❌ {name} 無法取得音檔，跳過。")
        return None

    # 檢查標題，避免重複分析舊聞 (這裡簡單實作，每次都分析最新一集)
    # 你可以加上日期判斷，例如只分析 24 小時內的
    
    local_file = f"{name}_temp.mp3"
    if not download_mp3(mp3_url, local_file): return None

    print(f"🧠 Gemini 正在聆聽 {name} ...")
    genai.configure(api_key=GEMINI_API_KEY)
    
    try:
        # 1. 上傳
        audio_file = genai.upload_file(path=local_file)
        while audio_file.state.name == "PROCESSING":
            time.sleep(2)
            audio_file = genai.get_file(audio_file.name)
        
        # 2. 分析
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        prompt = f"""
        你是一位專業的投資筆記整理者。請聽這集「{name}」Podcast。
        標題：{title}
        
        【任務】
        {role_prompt}
        請過濾閒聊，只保留含金量高的投資觀點。
        
        1. **市場觀點**：(多空看法、資金流向)
        2. **焦點話題**：(提到的具體產業或公司)
        3. **達人建議**：(操作心法或避雷提醒)

        ---
        **格式 (繁體中文)**：
        
        🎙️ **{name} 精華筆記**
        ({title})
        
        📈 **市場觀點**：...
        🔥 **焦點話題**：...
        💡 **達人建議**：...
        
        🔗 收聽：{link}
        """
        
        response = model.generate_content([prompt, audio_file])
        
        # 清理
        genai.delete_file(audio_file.name)
        os.remove(local_file)
        
        return response.text

    except Exception as e:
        print(f"分析失敗: {e}")
        if os.path.exists(local_file): os.remove(local_file)
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

    # --- 任務 2：Podcast 輪播 ---
    print("\n--- 任務 2：Podcast 筆記 ---")
    
    for podcast in PODCASTS:
        try:
            # 每個節目之間休息 5 秒，避免 LINE 或 Gemini 過熱
            time.sleep(5)
            
            report = analyze_podcast(podcast)
            if report:
                send_line_push(report)
                print(f"✅ {podcast['name']} 發送成功！")
            else:
                print(f"⚠️ {podcast['name']} 無報告")
                
        except Exception as e:
            print(f"❌ {podcast['name']} 執行錯誤: {e}")

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
import requests

# --- 設定環境變數 ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
LINE_TOKEN = os.environ.get("LINE_TOKEN", "").strip()
GROUP_ID = os.environ.get("GROUP_ID", "").strip()

# 設定時區
TW_TZ = pytz.timezone('Asia/Taipei')

# ==========================================
# 📅 工具函式
# ==========================================
def is_weekend():
    # 5=週六, 6=週日
    weekday = datetime.now(TW_TZ).weekday()
    return weekday >= 5

def get_current_date_str():
    now = datetime.now(TW_TZ)
    weekdays = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
    return f"{now.strftime('%Y/%m/%d')} ({weekdays[now.weekday()]})"

# ==========================================
# 📊 任務 1-A：平日台美股戰報 (維持不變)
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
    print("正在分析市場數據 (平日模式)...")
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
            for entry in feed.entries[:3]: # 稍微多抓一點讓AI挑選
                if len(entry.title) > 5: content += f"- {entry.title}\n"
    except: pass
    return content

def generate_stock_report():
    raw_news = get_market_news()
    us_signals, tw_info = get_market_data()
    date_str = get_current_date_str()
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash')
    prompt = f"""
    你是嚴謹的台股分析師。請撰寫平日戰報。
    資料A: {tw_info}
    資料B: {us_signals}
    資料C: {raw_news}
    請使用「純文字」格式，不要星號。
    格式範例:
    📊 台美股戰報 {date_str}
    【盤勢重點】(一句話)
    【焦點族群】(點名板塊)
    【操盤錦囊】(一句話建議)
    """
    return model.generate_content(prompt).text

# ==========================================
# 🌎 任務 1-B：週末操盤手戰報 (新邏輯)
# ==========================================

def get_weekend_data():
    """抓取週末需要的指標：期貨、美元、美債、黃金"""
    data_text = ""
    
    # 定義代號
    tickers = {
        "S&P500期貨": "ES=F",
        "那斯達克期貨": "NQ=F",
        "美元指數": "DX-Y.NYB",
        "美債10年殖利率": "^TNX",
        "黃金期貨": "GC=F"
    }
    
    print("正在抓取週末關鍵指標...")
    for name, symbol in tickers.items():
        try:
            # 抓取最後一筆交易數據
            df = yf.download(symbol, period="5d", interval="1d", progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            if len(df) >= 2:
                price = df['Close'].iloc[-1]
                prev_price = df['Close'].iloc[-2]
                change_pct = (price - prev_price) / prev_price * 100
                data_text += f"{name}: {price:.2f} (漲跌 {change_pct:+.2f}%)\n"
            else:
                data_text += f"{name}: 數據不足\n"
        except:
            data_text += f"{name}: 讀取失敗\n"
            
    return data_text

def generate_weekend_report():
    print("正在分析週末情勢 (操盤手模式)...")
    date_str = get_current_date_str()
    
    # 1. 抓取數據 (期貨/避險)
    market_data = get_weekend_data()
    
    # 2. 抓取新聞 (國際大事)
    raw_news = get_market_news()

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    # 你的操盤手邏輯 Prompt
    prompt = f"""
    你是專業的操盤手，今天是週末。請根據以下資料，寫出一份「下週開盤前的風向報告」。
    
    【市場數據】
    {market_data}
    
    【國際新聞標題】
    {raw_news}
    
    【寫作指令】
    請「完全依照」以下三個架構進行分析 (使用純文字，不要星號)：
    
    ✅ 一、先看「期貨市場」
    (根據 S&P500期貨 與 那斯達克期貨 的漲跌幅判斷)
    * 邏輯：漲跌超過 0.5% 代表方向明確(偏多/偏空)，若小幅震盪則標註震盪。
    * 請直接告訴我：週一開盤是「偏多」、「偏空」還是「觀望」。
    
    ✅ 二、看「重大國際新聞」
    (從新聞中篩選會影響資金流向的大事，若無相關新聞則寫無)
    1. 地緣政治：(是否有中東、俄烏、台海升級消息？關鍵字：空襲、制裁)
    2. 美國經濟/Fed：(是否有非農、CPI、官員談話？數據強弱對應升降息預期)
    3. 科技/銀行巨頭：(是否有 Apple/Nvidia/投行 的財測或爆雷)
    
    ✅ 三、看「資金避險指標」
    (根據 美元指數、美債殖利率、黃金 的漲跌判斷)
    * 邏輯：美元與殖利率雙漲=股市壓力；黃金大漲=市場恐慌。
    * 請總結目前的資金情緒是「追價」、「避險」還是「觀望」。
    
    【最後總結】
    (一句話給出下週一的操作心態)
    
    標題請用：🌎 週末全球盤勢總結 {date_str}
    """
    return model.generate_content(prompt).text

# ==========================================
# 🎧 任務 2：Podcast (含時效過濾)
# ==========================================
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

def is_fresh_episode(published_struct_time):
    if not published_struct_time: return False
    pub_time = datetime.fromtimestamp(time.mktime(published_struct_time)).replace(tzinfo=pytz.utc)
    now_time = datetime.now(pytz.utc)
    # 25 小時內的節目才算新的
    if (now_time - pub_time) < timedelta(hours=25):
        return True
    return False

def get_latest_episode(rss_url):
    try:
        feed = feedparser.parse(rss_url)
        if not feed.entries: return None, None, None
        
        entry = feed.entries[0]
        if not is_fresh_episode(entry.published_parsed):
            return None, None, None # 過期不報
            
        title = entry.title
        link = entry.link
        mp3_url = None
        for enclosure in feed.entries[0].get('enclosures', []):
            if 'audio' in enclosure.get('type', ''):
                mp3_url = enclosure.get('href')
                break
        return mp3_url, title, link
    except: return None, None, None

def download_mp3(url, filename="temp.mp3"):
    try:
        r = requests.get(url, stream=True)
        with open(filename, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024*1024):
                if chunk: f.write(chunk)
        return True
    except: return False

def analyze_podcast(podcast_config):
    name = podcast_config['name']
    rss = podcast_config['rss']
    role_prompt = podcast_config['prompt_role']
    
    mp3_url, title, link = get_latest_episode(rss)
    if not mp3_url: return None # 無新節目
    
    local_file = f"{name}_temp.mp3"
    if not download_mp3(mp3_url, local_file): return None

    genai.configure(api_key=GEMINI_API_KEY)
    try:
        audio_file = genai.upload_file(path=local_file)
        while audio_file.state.name == "PROCESSING":
            time.sleep(2)
            audio_file = genai.get_file(audio_file.name)
        
        model = genai.GenerativeModel('gemini-2.5-flash')
        prompt = f"""
        你是一位專業投資人。請聽這集「{name}」Podcast ({title})。
        {role_prompt}
        請使用「純文字」格式，不要星號，不要連結。
        格式範例:
        🎙️ {name} 精華筆記
        ({title})
        📈 市場觀點：
        🔥 焦點話題：
        💡 達人建議：
        """
        response = model.generate_content([prompt, audio_file])
        genai.delete_file(audio_file.name)
        os.remove(local_file)
        return response.text
    except:
        if os.path.exists(local_file): os.remove(local_file)
        return None

# ==========================================
# 🚀 主程式
# ==========================================
def send_line_push(content):
    line_bot_api = LineBotApi(LINE_TOKEN)
    line_bot_api.push_message(GROUP_ID, TextSendMessage(text=content))

if __name__ == "__main__":
    
    # 1. 週末/平日 切換
    if is_weekend():
        try:
            print("--- 執行任務：週末全球盤勢總結 ---")
            report = generate_weekend_report()
            send_line_push(report)
            print("✅ 週末戰報發送成功！")
        except Exception as e:
            print(f"❌ 週末戰報失敗: {e}")
    else:
        try:
            print("--- 執行任務：平日台美股戰報 ---")
            report = generate_stock_report()
            send_line_push(report)
            print("✅ 平日戰報發送成功！")
        except Exception as e:
            print(f"❌ 平日戰報失敗: {e}")

    # 2. Podcast 檢查
    print("\n--- 執行任務：Podcast 檢查 ---")
    for podcast in PODCASTS:
        try:
            time.sleep(5)
            report = analyze_podcast(podcast)
            if report:
                send_line_push(report)
                print(f"✅ {podcast['name']} 發送成功！")
        except: pass

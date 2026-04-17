import os
import datetime
from dotenv import load_dotenv

# 【重大修正】必須在這裡優先強制載入 .env，否則底層變數會抓不到預設為 0
load_dotenv()

ADMIN_ID = int(os.getenv('ADMIN_ID', 0))
ODDS_API_KEY = os.getenv('ODDS_API_KEY')

# --- 頻道與身份組設定 ---
CHANNEL_ID_ENGLISH     = 1489625770232909985  
CHANNEL_ID_SPAIN       = 1489625792903118929  
CHANNEL_ID_GERMAN      = 1489625813098692698  
CHANNEL_ID_UEFA        = 1489625832166002850  
CHANNEL_ID_GUIDE       = 1489640799636554070  
CHANNEL_ID_BUG         = 1489643447861248133  
CHANNEL_ID_LEADERBOARD = 1492541924282732738  
CHANNEL_ID_WHALE_ALERT = 1489652303328841899 

VIP_ROLES = {
    2: 1492555171207577742,
    3: 1492555676382138519,
    4: 1492555729834348748,
    5: 1492555766127923251,
    6: 1492555810260123859,
    7: 1492555843340599439
}

ERR_FOOTER = f"\n⚠️ 如持續出錯，請前往 <#{CHANNEL_ID_BUG}> 回報或建議。"

LEAGUE_CHANNELS = {
    "soccer_epl": {"name": "英超 (EPL)", "id": CHANNEL_ID_ENGLISH},
    "soccer_spain_la_liga": {"name": "西甲 (La Liga)", "id": CHANNEL_ID_SPAIN},
    "soccer_germany_bundesliga": {"name": "德甲 (Bund)", "id": CHANNEL_ID_GERMAN},
    "soccer_uefa_champs_league": {"name": "歐聯 (UCL)", "id": CHANNEL_ID_UEFA},
    "soccer_uefa_europa_league": {"name": "歐霸 (UEL)", "id": CHANNEL_ID_UEFA}
}

# --- 排程時區與時間 ---
HKT = datetime.timezone(datetime.timedelta(hours=8))
SCAN_TIME = datetime.time(hour=7, minute=0, tzinfo=HKT)
FINANCE_TIME = datetime.time(hour=7, minute=15, tzinfo=HKT)
WEEKLY_TIME = datetime.time(hour=7, minute=5, tzinfo=HKT)
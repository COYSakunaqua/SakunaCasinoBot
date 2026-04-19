import asyncio
import time

def get_user_data(bot, user_id):
    """取得玩家資料，若無則自動初始化，依賴於 bot.db"""
    uid = str(user_id)
    
    # 增加輕量級同步重試 (Sync Retry)，防禦讀取瞬間的 Cloudflare 502
    res = None
    for _ in range(3):
        try:
            res = bot.db.table("Users").select("*").eq("user_id", uid).execute()
            break
        except Exception as e:
            if "502" in str(e).lower() or "cloudflare" in str(e).lower():
                time.sleep(0.2) # 短暫微阻塞退避，兼容原同步架構
                continue
            raise e

    # 若查無資料，初始化玩家數據
    if not res or not res.data:
        bot.db.table("Users").insert({
            "user_id": uid, "bank": 0, "daily_lvl": 1, 
            "last_claim": "", "weekly_profit": 0, 
            "weekly_bet_count": 0, "current_streak": 0
        }).execute()
        return {
            "user_id": uid, "bank": 0, "daily_lvl": 1, 
            "last_claim": "", "weekly_profit": 0, 
            "weekly_bet_count": 0, "debt": 0, "current_streak": 0
        }
    return res.data[0]

def get_display_choice(title, choice):
    """將 A/B/C 轉換為動態隊名"""
    try:
        h_team, a_team = title.split(' vs ')
        if choice == 'A': return f"{h_team} 勝"
        if choice == 'B': return "和局 (Draw)"
        if choice == 'C': return f"{a_team} 勝"
    except Exception:
        pass
    return choice

async def async_db_execute(query_builder, retries=3, delay=0.5):
    """
    【新增】非同步資料庫執行器 (Async Retry Pattern)
    攔截 502/503 Cloudflare 瞬斷並進行退避重試，讓出 Event Loop 防止 10062
    """
    for attempt in range(retries):
        try:
            # 執行 Supabase query (底層為同步阻塞)
            return query_builder.execute()
        except Exception as e:
            error_msg = str(e).lower()
            if "502" in error_msg or "cloudflare" in error_msg or "503" in error_msg:
                if attempt < retries - 1:
                    print(f"⚠️ [DB Retry] 網路瞬斷 (Attempt {attempt+1}/{retries})，退避等待 {delay}s...")
                    await asyncio.sleep(delay) # 讓出執行權 (Yielding)，保護系統不崩潰
                    continue
            # 非瞬斷錯誤或重試耗盡，向上拋出給 UI 報錯
            raise e
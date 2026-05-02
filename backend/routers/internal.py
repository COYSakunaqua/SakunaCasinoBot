import os
import math
import httpx
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from fastapi import APIRouter, HTTPException, Header, Depends
from backend.utils.dependencies import supabase  # 確保你的 supabase client 放這裡

router = APIRouter(prefix="/api/internal", tags=["Internal Tasks"])

# ==========================================
# 🛡️ 環境變數與安全驗證
# ==========================================
CRON_SECRET_KEY = os.getenv("CRON_SECRET_KEY", "dev_secret_key")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

def verify_cron_secret(x_cron_secret: str = Header(None)):
    """ 攔截器：防止惡意觸發派彩引擎 """
    if x_cron_secret != CRON_SECRET_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized Cron Execution. Secret Key mismatch.")
    return True

# ==========================================
# 🏆 賽事白名單與防線配置
# ==========================================
TIER_1_SPORTS = [
    "soccer_epl", "soccer_fa_cup", "soccer_england_efl_cup", "soccer_england_community_shield",
    "soccer_spain_la_liga", "soccer_spain_copa_del_rey", "soccer_spain_super_cup",
    "soccer_germany_bundesliga", "soccer_germany_dfb_pokal",
    "soccer_italy_serie_a", "soccer_france_ligue_one",
    "soccer_uefa_champs_league", "soccer_uefa_europa_league", "soccer_uefa_europa_conference_league", "soccer_uefa_euro_championship",
    "soccer_fifa_world_cup", "soccer_uefa_nations_league"
]
TIER_2_SPORTS = ["soccer_england_championship", "soccer_friendly_match_club"]

# ==========================================
# ⚙️ 核心邏輯 (內部純異步函數)
# ==========================================

async def _prune_internal() -> int:
    """ 
    歷史數據封存引擎 (Retention: 7 days)
    清理過期的 Matches 與關聯的 Bets，嚴格釋放 Event Loop。
    """
    now_hkt = datetime.now(ZoneInfo("Asia/Hong Kong"))
    cutoff_time = now_hkt - timedelta(days=7)
    cutoff_iso = cutoff_time.isoformat()
    
    # 撈取已完賽 (status != 0) 且開賽時間超過 7 天的賽事
    old_matches = supabase.table("Matches").select("id").neq("status", 0).lt("commence_time", cutoff_iso).execute().data
    if not old_matches:
        return 0
        
    old_match_ids = [m["id"] for m in old_matches]
    deleted_count = 0
    
    # Chunked deletion (防禦 URL 長度限制與 DB Timeout)
    chunk_size = 50
    for i in range(0, len(old_match_ids), chunk_size):
        chunk = old_match_ids[i:i+chunk_size]
        
        # 刪除關聯的 Bets (若 Supabase 已設 Foreign Key Cascade 可省略這行，但手動清較穩妥)
        supabase.table("Bets").delete().in_("match_id", chunk).execute()
        # 刪除 Matches
        supabase.table("Matches").delete().in_("id", chunk).execute()
        
        deleted_count += len(chunk)
        await asyncio.sleep(0.05)  # 邏輯驗證：強制讓出 Event Loop
        
    return deleted_count

async def _settle_internal() -> dict:
    """ 全服結算與派彩引擎 (包含富人稅與狂熱點火) """
    now_hkt = datetime.now(ZoneInfo("Asia/Hong Kong"))
    
    # 1. 抓取國庫狀態與 Fever 判定
    treasury = supabase.table("Users").select("*").eq("user_id", "TREASURY").single().execute().data
    is_fever_time = treasury.get("fever_active_until") and now_hkt < datetime.fromisoformat(treasury["fever_active_until"])
    
    # 動態二次方閥值
    fever_threshold = min(500000, 10000 * (treasury.get("fever_count", 1) ** 2))
    
    # 點火邏輯 (需確認今日賽事 >= 5)
    today_matches_count = len(supabase.table("Matches").select("id").eq("status", 0).execute().data)
    
    if not is_fever_time and treasury["bank"] >= fever_threshold and today_matches_count >= 5:
        treasury["bank"] -= fever_threshold
        treasury["fever_count"] = treasury.get("fever_count", 1) + 1
        is_fever_time = True
        next_0700 = (now_hkt + timedelta(days=1)).replace(hour=7, minute=0, second=0, microsecond=0)
        supabase.table("Users").update({
            "bank": treasury["bank"], 
            "fever_count": treasury["fever_count"], 
            "fever_active_until": next_0700.isoformat()
        }).eq("user_id", "TREASURY").execute()

    # 2. 派彩迴圈與非同步阻塞防禦 (Yielding)
    pending_bets = supabase.table("Bets").select("*").eq("status", 0).execute().data
    tax_collected = 0
    settled_count = 0

    for index, bet in enumerate(pending_bets):
        if index % 10 == 0: await asyncio.sleep(0.05) # 邏輯驗證：釋放主執行緒
            
        # [實戰需由 API 取回賽果，此處保留你的原有假設邏輯]
        user_db = supabase.table("Users").select("bank, daily_lvl").eq("app_uuid", bet["app_uuid"]).single().execute().data
        if not user_db: continue
        
        current_bank = user_db["bank"]
        is_win = True # 假設贏
        
        if is_win:
            payout = int(bet["amount"] * bet["odds"])
            tax_amount = 0
            # 凹函數富人稅 (Fever 日或盲盒免稅判定)
            if not is_fever_time and user_db["daily_lvl"] >= 5 and not bet["is_mystery_box"]:
                tax_rate = min(10.0, max(1.0, round(-2 + 3 * math.sqrt(user_db["daily_lvl"] - 4), 2)))
                tax_amount = int(payout * (tax_rate / 100))
                tax_collected += tax_amount
            current_bank += (payout - tax_amount)
        else:
            # 輸錢邏輯與敗者退水 (系統印鈔，不扣國庫)
            if is_fever_time:
                current_bank += int(bet["amount"] * 0.10)

        # 批次更新狀態
        supabase.table("Bets").update({"status": 1 if is_win else -1}).eq("id", bet["id"]).execute()
        supabase.table("Users").update({"bank": current_bank}).eq("app_uuid", bet["app_uuid"]).execute()
        settled_count += 1

    # 稅金入國庫
    if tax_collected > 0:
        supabase.table("Users").update({"bank": treasury["bank"] + tax_collected}).eq("user_id", "TREASURY").execute()

    return {"settled": settled_count, "fever_active": is_fever_time, "tax_collected": tax_collected}

async def _fetch_odds_internal() -> dict:
    """ 動態水位抓盤引擎 (Tier 1 + 枯水補齊) """
    matches_to_insert = []
    
    async def fetch_sport(sport_key):
        url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
        params = {"apiKey": ODDS_API_KEY, "regions": "eu", "markets": "h2h", "oddsFormat": "decimal"}
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                return resp.json()
        except Exception:
            return []

    # 1. 橫掃 Tier 1 頂級賽事
    for sport in TIER_1_SPORTS:
        raw_data = await fetch_sport(sport)
        for match in raw_data:
            if not match.get("bookmakers"): continue
            outcomes = match["bookmakers"][0]["markets"][0]["outcomes"]
            boosted = [{"name": o["name"], "odds": round(1 + (o["price"] - 1) * 1.2, 2)} for o in outcomes]
            
            matches_to_insert.append({
                "id": match["id"], "sport_title": match.get("sport_title", "Football"),
                "home_team": match["home_team"], "away_team": match["away_team"],
                "commence_time": match["commence_time"], "odds_data": boosted, "status": 0
            })

    # 2. 動態補水防線 (Fallback)
    if len(matches_to_insert) < 20:
        for sport in TIER_2_SPORTS:
            if len(matches_to_insert) >= 20: break
            raw_data = await fetch_sport(sport)
            for match in raw_data:
                if len(matches_to_insert) >= 20: break
                if not match.get("bookmakers"): continue
                outcomes = match["bookmakers"][0]["markets"][0]["outcomes"]
                boosted = [{"name": o["name"], "odds": round(1 + (o["price"] - 1) * 1.2, 2)} for o in outcomes]
                matches_to_insert.append({
                    "id": match["id"], "sport_title": match.get("sport_title", "Football"),
                    "home_team": match["home_team"], "away_team": match["away_team"],
                    "commence_time": match["commence_time"], "odds_data": boosted, "status": 0
                })

    # 3. 寫入 DB (UPSERT)
    if matches_to_insert:
        supabase.table("Matches").upsert(matches_to_insert).execute()
        
    return {"total_inserted": len(matches_to_insert)}

# ==========================================
# 🚀 外部 API 路由 (Endpoints)
# ==========================================

@router.post("/force_run", dependencies=[Depends(verify_cron_secret)])
async def trigger_full_daily_routine():
    """ 
    終極每日排程入口。
    由 cron-job.org 每日 07:00 (HKT) 呼叫，依序執行：清理 -> 結算 -> 抓盤。
    """
    prune_result = await _prune_internal()
    settle_result = await _settle_internal()
    fetch_result = await _fetch_odds_internal()
    
    return {
        "status": "success",
        "timestamp": datetime.now(ZoneInfo("Asia/Hong Kong")).isoformat(),
        "pruned_matches": prune_result,
        "settlement": settle_result,
        "odds_fetched": fetch_result
    }

# 為了方便後端測試，保留獨立 Endpoint
@router.post("/fetch_odds", dependencies=[Depends(verify_cron_secret)])
async def fetch_daily_odds_route():
    return await _fetch_odds_internal()

@router.post("/daily_settlement", dependencies=[Depends(verify_cron_secret)])
async def execute_daily_settlement_route():
    return await _settle_internal()
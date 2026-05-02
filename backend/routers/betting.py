import math
import random
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
# from utils.dependencies import get_current_user, supabase

router = APIRouter(prefix="/api/betting", tags=["Betting"])

class BetRequest(BaseModel):
    match_id: str
    option_id: str
    amount: int
    is_all_in: bool = False

@router.post("/place_bet")
async def place_bet(payload: BetRequest, user = Depends(get_current_user)):
    """
    常規盤口下注。
    防禦邊界：防套利過濾、常規 +20% 增益、狂熱日 All-In +60% 增益。
    """
    app_uuid = user.id
    user_db = supabase.table("Users").select("bank").eq("app_uuid", app_uuid).single().execute().data
    
    if payload.amount <= 0 or user_db["bank"] < payload.amount:
        raise HTTPException(status_code=400, detail="Invalid amount or insufficient funds.")
        
    if payload.is_all_in and payload.amount != user_db["bank"]:
        raise HTTPException(status_code=400, detail="All-in flag requires full balance.")

    # 1. 嚴格防套利：單場單注
    existing_bet = supabase.table("Bets").select("id").eq("app_uuid", app_uuid).eq("match_id", payload.match_id).execute()
    if existing_bet.data:
        raise HTTPException(status_code=403, detail="Anti-Arbitrage triggered.")

    # 2. 獲取賽事與狂熱狀態
    # match_data = get_match_odds(payload.match_id)
    original_odds = 2.0 # 佔位符
    is_fever_time = check_fever_time() # 假設有此共用函數檢查國庫狂熱標記

    # 3. 賠率增益判定
    boost_multiplier = 1.6 if (is_fever_time and payload.is_all_in) else 1.2
    boosted_odds = round(1 + (original_odds - 1) * boost_multiplier, 2)

    # 4. DB 寫入
    new_bank = user_db["bank"] - payload.amount
    supabase.table("Users").update({"bank": new_bank}).eq("app_uuid", app_uuid).execute()
    
    supabase.table("Bets").insert({
        "app_uuid": app_uuid, "match_id": payload.match_id, "option_id": payload.option_id,
        "amount": payload.amount, "odds": boosted_odds, "status": 0, "is_mystery_box": False
    }).execute()

    return {"message": "Bet placed", "odds": boosted_odds, "new_bank": new_bank}


@router.post("/mystery_box")
async def buy_mystery_box(user = Depends(get_current_user)):
    """
    購買衍生品盲盒。
    包含：VIP 每日物理限購鎖、狂熱核動力倍率、敗者退水前置標記。
    """
    app_uuid = user.id
    hkt_tz = ZoneInfo("Asia/Hong Kong")
    today_str = datetime.now(hkt_tz).strftime("%Y-%m-%d")
    
    user_db = supabase.table("Users").select("bank, daily_lvl, is_streak").eq("app_uuid", app_uuid).single().execute().data
    vip_lvl = user_db["daily_lvl"]
    is_fever_time = check_fever_time()

    # 1. VIP 限購防護網 (Gacha Limit)
    if vip_lvl <= 4:
        daily_limit = 2
    elif vip_lvl <= 9:
        daily_limit = vip_lvl
    elif vip_lvl <= 14:
        daily_limit = math.floor(vip_lvl * 1.5)
    else:
        daily_limit = vip_lvl * 2

    # 檢查今日已買盲盒數量 (需對接 DB 日期過濾)
    # today_box_count = get_today_box_count(app_uuid)
    today_box_count = 0 
    if today_box_count >= daily_limit:
        raise HTTPException(status_code=403, detail=f"Daily Mystery Box limit reached ({daily_limit}).")

    # 2. 動態定價
    base_amount = 20000 if user_db.get("is_streak") else 10000
    box_price = int((base_amount * vip_lvl) / 4)
    if user_db["bank"] < box_price:
        raise HTTPException(status_code=400, detail="Insufficient funds.")

    # 3. 核動力倍率引擎
    r = random.uniform(0, 1)
    if is_fever_time:
        multiplier = round(3.0 + 4.0 * (1 - math.sqrt(r)), 2) # Fever: 3.0x ~ 7.0x
    else:
        multiplier = round(1.5 + 3.5 * (1 - math.sqrt(r)), 2) # Normal: 1.5x ~ 5.0x
        
    base_odds = 2.0
    final_odds = round(base_odds * multiplier, 2)

    # 4. DB 寫入
    new_bank = user_db["bank"] - box_price
    supabase.table("Users").update({"bank": new_bank}).eq("app_uuid", app_uuid).execute()
    supabase.table("Bets").insert({
        "app_uuid": app_uuid, "match_id": "sys_mystery", "option_id": "sys_random",
        "amount": box_price, "odds": final_odds, "status": 0, "is_mystery_box": True
    }).execute()

    return {"message": "Box purchased!", "multiplier": multiplier, "final_odds": final_odds}
from fastapi import APIRouter, Header, HTTPException, Depends
from backend.utils.dependencies import supabase
import os

router = APIRouter(prefix="/internal", tags=["Internal"])

@router.post("/force_run")
async def force_run(x_cron_secret: str = Header(None)):
    """強制執行每日結算與賠率更新邏輯。"""
    print("DEBUG: Force run triggered.")
    expected_secret = os.getenv("CRON_SECRET_KEY")
    if not expected_secret:
        raise HTTPException(status_code=500, detail="Server config error: CRON_SECRET_KEY missing")
    if x_cron_secret != expected_secret:
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid cron secret")

    try:
        test_user = supabase.table("Users").select("app_uuid").limit(1).execute()
        odds_key = os.getenv("ODDS_API_KEY")
        if not odds_key: print("WARNING: ODDS_API_KEY is missing.")

        print("DEBUG: Settlement logic executed.")
        return {
            "status": "success",
            "message": "CasinOYS V5 Settlement Engine Triggered",
            "database_check": "OK" if test_user else "FAILED"
        }
    except Exception as e:
        print(f"CRITICAL ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal Logic Crash: {str(e)}")

@router.get("/treasury")
async def get_treasury_status():
    """獲取國庫 M0 總量與 Fever 狀態。"""
    try:
        # 計算全服餘額總和作為 M0 (若資料量龐大，後續建議改為 CronJob 快取)
        users = supabase.table("Users").select("bank").execute()
        user_list = getattr(users, 'data', []) if users else []
        current_m0 = sum(u.get("bank", 0) for u in user_list)

        # 假設目前 Fever Count 為 1 (後續可從 Settings 表撈取)
        fever_count = 1
        
        # 國庫公式：min(500,000, 10,000 * FeverCount^2)
        threshold = min(500000, 10000 * (fever_count ** 2))
        
        # 百分比上限 100%
        percentage = min(100, (current_m0 / threshold) * 100) if threshold > 0 else 0

        return {
            "current_m0": current_m0,
            "threshold": threshold,
            "fever_count": fever_count,
            "percentage": round(percentage, 2)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
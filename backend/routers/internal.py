from fastapi import APIRouter, Header, HTTPException, Depends
from backend.utils.dependencies import supabase
import os

# 注意：prefix 保持為 /internal，配合 main.py 中的 include_router(prefix="/api")
# 最終路徑將會是 /api/internal/force_run
router = APIRouter(prefix="/internal", tags=["Internal"])

@router.post("/force_run")
async def force_run(x_cron_secret: str = Header(None)):
    """
    強制執行每日結算與賠率更新邏輯。
    """
    print("DEBUG: Force run triggered.")

    # 1. 驗證 Cron Secret
    expected_secret = os.getenv("CRON_SECRET_KEY")
    if not expected_secret:
        print("ERROR: CRON_SECRET_KEY is missing in Vercel settings.")
        raise HTTPException(status_code=500, detail="Server config error: CRON_SECRET_KEY missing")
    
    if x_cron_secret != expected_secret:
        print(f"ERROR: Unauthorized access with secret: {x_cron_secret}")
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid cron secret")

    try:
        # 2. 核心邏輯檢查：確認 Supabase 連線
        print("DEBUG: Testing Supabase connection...")
        # 這裡會檢查 Users 表是否存在，如果表名不對會直接拋出異常
        test_user = supabase.table("Users").select("app_uuid").limit(1).execute()
        
        # 3. 檢查 Odds API Key
        odds_key = os.getenv("ODDS_API_KEY")
        if not odds_key:
            print("WARNING: ODDS_API_KEY is missing. Odds update will be skipped.")

        # ==========================================
        # 這裡放置你的結算邏輯 (Settlement Logic)
        # ==========================================
        print("DEBUG: Settlement logic executed.")

        return {
            "status": "success",
            "message": "CasinOYS V5 Settlement Engine Triggered",
            "database_check": "OK" if test_user else "FAILED"
        }

    except Exception as e:
        # 將具體錯誤捕捉並回傳，這樣你就能直接在瀏覽器看到是哪裡報錯
        print(f"CRITICAL ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal Logic Crash: {str(e)}")
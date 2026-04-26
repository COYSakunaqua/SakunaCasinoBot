from fastapi import APIRouter, Header, HTTPException
from supabase import create_client, Client
import os
from dotenv import load_dotenv

# 讀取環境變數
load_dotenv()
SB_URL = os.getenv('SUPABASE_URL')
SB_KEY = os.getenv('SUPABASE_KEY')

# 初始化 Supabase 連線 (無狀態 RESTful 模式)
db: Client = create_client(SB_URL, SB_KEY)

# 宣告這是一個路由器 (相當於 Cog)
router = APIRouter()

@router.get("/balance", summary="獲取用戶餘額與 VIP 狀態")
def get_balance(x_user_id: str = Header(..., description="Discord 用戶 ID")):
    """
    無狀態查詢：前端必須在 Header 傳入 X-User-ID。
    這是為了防範未經授權的越權存取。
    """
    try:
        # 直接使用 Supabase REST API 查詢
        res = db.table("Users").select("bank, daily_lvl").eq("user_id", x_user_id).execute()
        
        # 邊界防禦：用戶不存在
        if not res.data:
            raise HTTPException(status_code=404, detail="User not found in CasinOYS system.")
            
        user_data = res.data[0]
        return {
            "status": "success",
            "data": {
                "user_id": x_user_id,
                "bank": user_data['bank'],
                "vip_level": user_data['daily_lvl']
            }
        }
    except Exception as e:
        # 攔截所有報錯，防止伺服器崩潰
        raise HTTPException(status_code=500, detail=f"Database connection error: {str(e)}")
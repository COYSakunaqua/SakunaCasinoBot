import os
from fastapi import Header, HTTPException
from supabase import create_client, Client

# ==========================================
# 🛰️ Supabase 初始化 (核心資料交換)
# ==========================================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing Supabase environment variables.")

# 全域 Supabase 實體，供所有 Router 調用
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ==========================================
# 🔑 身分驗證依賴 (V5 App 版)[cite: 6]
# ==========================================
class UserContext:
    def __init__(self, user_id: str):
        self.id = user_id

async def get_current_user(authorization: str = Header(None)):
    """
    V5 身分驗證攔截器。
    目前實作：從 Header 抓取 Bearer Token (app_uuid)。
    未來擴充：可在此進行 JWT 解碼。
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization Header")
    
    # 預期格式: "Bearer <app_uuid>"
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise ValueError()
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid authorization scheme")

    # 驗證該 UUID 是否存在於 Users 表中[cite: 6]
    user_check = supabase.table("Users").select("app_uuid").eq("app_uuid", token).execute()
    
    if not user_check.data:
        raise HTTPException(status_code=401, detail="User not verified or Genesis Airdrop not claimed")

    # 回傳封裝好的用戶對象，供 economy.py 使用 user.id[cite: 6]
    return UserContext(user_id=token)
import os
from fastapi import Header, HTTPException
from supabase import create_client, Client
from dotenv import load_dotenv

# ==========================================
# 🛰️ 載入環境變數 (防禦冷啟動遺失)
# ==========================================
load_dotenv()

# ==========================================
# 🛰️ Supabase 初始化 (核心資料交換)
# ==========================================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing Supabase environment variables. 請確認 SakunaBot 根目錄存在 .env 檔案，並包含 SUPABASE_URL 與 SUPABASE_KEY。")

# 全域 Supabase 實體，供所有 Router 調用
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ==========================================
# 🔑 身分驗證依賴 (V5 App 版)
# ==========================================
class UserContext:
    def __init__(self, user_id: str):
        self.id = user_id

async def get_current_user(authorization: str = Header(None)):
    """
    V5 身分驗證攔截器。從 Header 抓取 Bearer Token 並透過 Supabase Auth 解析出真實 UUID。
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization Header")
    
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer": raise ValueError()
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid authorization scheme")

    # 1. JWT 解碼與驗證：使用 Supabase Auth 抽出真實 UUID，解決 22P02 型別錯誤
    try:
        auth_res = supabase.auth.get_user(token)
        if not auth_res or not auth_res.user:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        
        real_uuid = auth_res.user.id
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Token validation failed: {str(e)}")

    # 2. 移除邏輯死結：不再強制檢查 Users 表
    # 剛註冊 Web 端準備執行 /app-bind 的玩家，此時還沒被綁定到 Users 表。
    # 如果在這裡擋下，/app-bind 永遠無法執行。資料庫的狀態交由 Endpoint 各自把關。

    return UserContext(user_id=real_uuid)
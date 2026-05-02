from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.routers import economy, internal  # 必須引入 internal

# 1. 建立 FastAPI 實體 (總指揮官)
app = FastAPI(
    title="CasinOYS API",
    description="CasinOYS V5.0 App Edition 核心後端系統",
    version="1.0.0"
)

# 2. CORS 防禦網設定 (解耦架構必備)
# 目前允許所有來源 (*)，方便開發與 Vercel 動態網域。上線後可限縮至具體的前端網域。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 3. 註冊路由 (掛載 API 端點)
app.include_router(economy.router, prefix="/api/v1/economy", tags=["Economy"])
app.include_router(internal.router, tags=["Internal Tasks"]) # 掛載排程結算與抓盤引擎

# 4. 系統健康檢查端點 (Render 部署時監控存活狀態用)
@app.get("/api/health", tags=["System"])
def health_check():
    return {
        "status": "online",
        "system": "CasinOYS V5.0 Stateless Backend",
        "defense_level": "Maximum"
    }
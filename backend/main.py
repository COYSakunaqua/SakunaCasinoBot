from fastapi import FastAPI
from backend.routers import economy

# 1. 建立 FastAPI 實體 (總指揮官)
app = FastAPI(
    title="CasinOYS API",
    description="CasinOYS V5.0 App Edition 核心後端系統",
    version="1.0.0"
)

# 2. 註冊路由 (掛載 Cogs)
app.include_router(economy.router, prefix="/api/v1/economy", tags=["Economy"])

# 3. 系統健康檢查端點 (Render 部署時監控存活狀態用)
@app.get("/health", tags=["System"])
def health_check():
    return {
        "status": "online",
        "system": "CasinOYS V5.0 Stateless Backend",
        "defense_level": "Maximum"
    }
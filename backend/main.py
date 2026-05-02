from fastapi import FastAPI
from backend.routers import economy, internal

app = FastAPI(title="CasinOYS V5 Backend")

# 解決 404：強制所有路由在 Vercel 轉發後能正確匹配 /api 前綴
app.include_router(economy.router, prefix="/api")
app.include_router(internal.router, prefix="/api")

@app.get("/api/health", tags=["System"])
async def health_check():
    """系統健康檢查端點"""
    return {
        "status": "online",
        "system": "CasinOYS V5.0 Stateless Backend",
        "defense_level": "Maximum",
        "note": "If you see this, the routing is finally aligned."
    }
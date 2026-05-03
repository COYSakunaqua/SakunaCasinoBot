from fastapi import FastAPI
from backend.routers import economy, internal

app = FastAPI(title="CasinOYS V5 Backend")

# 統一在此處掛載 /api 前綴。完美對接 Vercel Serverless 與 Next.js Proxy
app.include_router(economy.router, prefix="/api")
app.include_router(internal.router, prefix="/api")

@app.get("/api/health", tags=["System"])
async def health_check():
    """系統健康檢查端點"""
    return {
        "status": "online",
        "system": "CasinOYS V5.0 Stateless Backend (Vercel Edition)",
        "defense_level": "Maximum",
        "note": "Global routing standardization deployed."
    }
from fastapi import APIRouter, Depends, HTTPException
# 修正重點：使用絕對路徑並同時引入 get_current_user 與 supabase
from backend.utils.dependencies import get_current_user, supabase 
from pydantic import BaseModel
import math

router = APIRouter(prefix="/api/economy", tags=["Economy"])

@router.post("/upgrade")
async def upgrade_vip(user = Depends(get_current_user)):
    """
    處理玩家 VIP 升級。
    核心邏輯：套用 12,500 * (VIP^2) 的純二次方公式，精準回收 M0。
    """
    # 確保你的 user 對象有 id 屬性 (通常來自 app_uuid)
    app_uuid = user.id 
    
    # 1. 抓取當前資料 (使用正確引入的 supabase)
    user_resp = supabase.table("Users").select("bank, daily_lvl").eq("app_uuid", app_uuid).single().execute()
    if not user_resp.data:
        raise HTTPException(status_code=404, detail="User not found")
        
    current_vip = user_resp.data["daily_lvl"]
    current_bank = user_resp.data["bank"]
    
    # 2. 升級費用計算 (Base 12,500)[cite: 2, 5]
    upgrade_cost = 12500 * (current_vip ** 2)
    
    if current_bank < upgrade_cost:
        raise HTTPException(status_code=400, detail=f"Insufficient funds. Need ${upgrade_cost}.")
        
    # 3. 扣款與等級更新
    new_bank = current_bank - upgrade_cost
    new_vip = current_vip + 1
    
    supabase.table("Users").update({
        "bank": new_bank,
        "daily_lvl": new_vip
    }).eq("app_uuid", app_uuid).execute()
    
    return {"message": "Upgraded successfully", "new_vip": new_vip, "new_bank": new_bank}
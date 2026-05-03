from fastapi import APIRouter, Depends, HTTPException
from backend.utils.dependencies import get_current_user, supabase 
from pydantic import BaseModel
import datetime

router = APIRouter(prefix="/economy", tags=["Economy"])

class BindRequest(BaseModel):
    code: str

@router.post("/upgrade")
async def upgrade_vip(user = Depends(get_current_user)):
    app_uuid = user.id 
    
    user_resp = supabase.table("Users").select("bank, daily_lvl").eq("app_uuid", app_uuid).maybe_single().execute()
    user_data = getattr(user_resp, 'data', None) if user_resp else None
    
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found")
        
    current_vip = user_data["daily_lvl"]
    current_bank = user_data["bank"]
    upgrade_cost = 12500 * (current_vip ** 2)
    
    if current_bank < upgrade_cost:
        raise HTTPException(status_code=400, detail=f"Insufficient funds. Need ${upgrade_cost}.")
        
    new_bank = current_bank - upgrade_cost
    new_vip = current_vip + 1
    
    supabase.table("Users").update({"bank": new_bank, "daily_lvl": new_vip}).eq("app_uuid", app_uuid).execute()
    return {"message": "Upgraded successfully", "new_vip": new_vip, "new_bank": new_bank}

@router.post("/app-bind")
async def bind_app_account(req: BindRequest, user = Depends(get_current_user)):
    app_uuid = user.id

    existing_check = supabase.table("Users").select("user_id").eq("app_uuid", app_uuid).maybe_single().execute()
    existing_data = getattr(existing_check, 'data', None) if existing_check else None
    if existing_data:
        raise HTTPException(status_code=400, detail="此 Web 帳號已綁定過 Discord 檔案。")

    verify_resp = supabase.table("AppVerification").select("*").eq("code", req.code).maybe_single().execute()
    verify_data = getattr(verify_resp, 'data', None) if verify_resp else None
    if not verify_data:
        raise HTTPException(status_code=400, detail="驗證碼錯誤、已失效或已被使用。")
        
    expires_at = datetime.datetime.fromisoformat(verify_data["expires_at"].replace("Z", "+00:00"))
    if datetime.datetime.now(datetime.timezone.utc) > expires_at:
        supabase.table("AppVerification").delete().eq("code", req.code).execute()
        raise HTTPException(status_code=400, detail="驗證碼已過期 (超過 15 分鐘)，請重新於 Discord 生成。")

    discord_id = verify_data["user_id"]

    all_users = supabase.table("Users").select("user_id", "bank").order("bank", desc=True).execute()
    users_list = getattr(all_users, 'data', []) if all_users else []
    
    target_user_data = next((u for u in users_list if u["user_id"] == discord_id), None)
    if not target_user_data:
        raise HTTPException(status_code=404, detail="找不到對應的 Discord 舊帳號資料。")

    rank = users_list.index(target_user_data) + 1
    current_bank = target_user_data["bank"]

    if rank == 1: new_vip, bonus = 5, 50000
    elif rank == 2: new_vip, bonus = 4, 30000
    elif rank == 3: new_vip, bonus = 4, 0
    elif rank == 4: new_vip, bonus = 3, 10000
    elif rank == 5: new_vip, bonus = 3, 0
    else: new_vip, bonus = 2, 5000

    # 核心修復：Hard Reset，新資產直接等於起步紅利
    final_bank = bonus

    supabase.table("Users").update({
        "app_uuid": app_uuid, "daily_lvl": new_vip, "bank": final_bank
    }).eq("user_id", discord_id).execute()

    supabase.table("AppVerification").delete().eq("code", req.code).execute()

    return {
        "message": "Genesis airdrop claimed successfully.",
        "rank": rank, "new_vip": new_vip, "old_bank": current_bank, "bonus": bonus, "new_bank": final_bank
    }
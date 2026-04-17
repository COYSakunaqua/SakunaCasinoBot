def get_user_data(bot, user_id):
    """取得玩家資料，若無則自動初始化，依賴於 bot.db"""
    uid = str(user_id)
    res = bot.db.table("Users").select("*").eq("user_id", uid).execute()
    if not res.data:
        bot.db.table("Users").insert({
            "user_id": uid, "bank": 0, "daily_lvl": 1, 
            "last_claim": "", "weekly_profit": 0, 
            "weekly_bet_count": 0, "current_streak": 0
        }).execute()
        return {
            "user_id": uid, "bank": 0, "daily_lvl": 1, 
            "last_claim": "", "weekly_profit": 0, 
            "weekly_bet_count": 0, "debt": 0, "current_streak": 0
        }
    return res.data[0]

def get_display_choice(title, choice):
    """將 A/B/C 轉換為動態隊名"""
    try:
        h_team, a_team = title.split(' vs ')
        if choice == 'A': return f"{h_team} 勝"
        if choice == 'B': return "和局 (Draw)"
        if choice == 'C': return f"{a_team} 勝"
    except Exception:
        pass
    return choice
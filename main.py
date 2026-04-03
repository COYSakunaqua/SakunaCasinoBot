import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import gc
import aiohttp
from supabase import create_client, Client
from dotenv import load_dotenv

# --- 1. 系統初始化與環境變數 ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('ODDS_API_KEY')
SB_URL = os.getenv('SUPABASE_URL')
SB_KEY = os.getenv('SUPABASE_KEY')
ADMIN_ID = int(os.getenv('ADMIN_ID', 0))

# 初始化 Supabase 客戶端 
supabase: Client = create_client(SB_URL, SB_KEY)

class SakunaBot(commands.Bot):
    def __init__(self):
        # 記憶體優化：僅開啟必要 Intents，關閉成員緩存以節省 RAM
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)
        self.session = None  # 預留持久化 aiohttp session

    async def setup_hook(self):
        # 建立全局 Session 減少 TCP 握手開銷
        self.session = aiohttp.ClientSession()
        # 同步 Slash Command Tree
        await self.tree.sync()
        # 啟動背景任務
        self.auto_settle_task.start()
        self.memory_cleaner.start()
        print(f"✅ CasinOYS 核心啟動 | 運行環境: DisCloud 100MB RAM", flush=True)

    async def close(self):
        # 關閉 Bot 時優雅關閉 Session
        if self.session:
            await self.session.close()
        await super().close()

    # --- 記憶體防禦機制：每 30 分鐘強制回收 ---
    @tasks.loop(minutes=30)
    async def memory_cleaner(self):
        gc.collect()
        print("🧹 [System] Garbage Collection 執行成功", flush=True)

    # --- 自動結算邏輯：API 節流優化 ---
    @tasks.loop(minutes=180)
    async def auto_settle_task(self):
        if not API_KEY: return
        
        # 預檢機制：先檢查資料庫是否有 status 0 (未結算) 的賽事 
        # 避免在沒有比賽時浪費 API Quota 
        check = supabase.table("Events").select("event_id").eq("status", 0).execute()
        if not check.data:
            return

        print("🔍 [Auto-Settle] 檢測到待結算賽事，正在抓取結果...", flush=True)
        url = "https://api.the-odds-api.com/v4/sports/soccer_uefa_champs_league/scores/"
        params = {'apiKey': API_KEY, 'daysFrom': 1}
        
        try:
            async with self.session.get(url, params=params) as resp:
                if resp.status != 200: return
                matches = await resp.json()
                
                for match in matches:
                    if not match['completed']: continue
                    
                    # 提取主客隊比分並判定勝負 (A:主, B:和, C:客)
                    h_team, a_team = match['home_team'], match['away_team']
                    h_score = next(s['score'] for s in match['scores'] if s['name'] == h_team)
                    a_score = next(s['score'] for s in match['scores'] if s['name'] == a_team)
                    win_choice = 'A' if h_score > a_score else 'C' if a_score > h_score else 'B'
                    
                    # 匹配資料庫中的標題
                    title = f"{h_team} vs {a_team}"
                    event_res = supabase.table("Events").select("event_id").eq("title", title).eq("status", 0).execute()
                    
                    if event_res.data:
                        for event in event_res.data:
                            await self.do_payout(event['event_id'], win_choice, title)
                
                # 處理完畢後手動釋放大型 JSON 物件
                del matches
                gc.collect()
        except Exception as e:
            print(f"❌ [Error] 結算過程異常: {e}", flush=True)

    async def do_payout(self, event_id, win_choice, title):
        # 預防重複結算：先更新狀態為 2 (已結算) [cite: 6, 8]
        supabase.table("Events").update({"status": 2}).eq("event_id", event_id).execute()
        
        # 查詢所有中獎注單 [cite: 7]
        bets = supabase.table("Bets").select("*").eq("event_id", event_id).eq("choice", win_choice).execute()
        
        for bet in bets.data:
            # 依據鎖定賠率計算派彩金額 [cite: 7]
            payout = int(bet['amount'] * bet['locked_odds'])
            # 透過 RPC 原子性增加錢包餘額 [cite: 8]
            supabase.rpc('increment_wallet', {'row_id': bet['user_id'], 'amount': payout}).execute()
        
        print(f"💰 [Payout] 賽事 {title} 結算完成", flush=True)

# --- 資料存取層 ---
def get_user_data(user_id):
    uid = str(user_id)
    res = supabase.table("Users").select("*").eq("user_id", uid).execute()
    if not res.data:
        # 新用戶初始化：贈送 1000 元起手勢
        supabase.table("Users").insert({"user_id": uid, "wallet": 1000, "bank": 0}).execute()
        return 1000, 0
    return res.data[0]['wallet'], res.data[0]['bank']

# --- UI 元件 ---
class BetModal(discord.ui.Modal):
    def __init__(self, event_id, choice, odds, title):
        super().__init__(title=f"下注確認 - {title}")
        self.event_id, self.choice, self.odds = event_id, choice, odds
        self.amt = discord.ui.TextInput(label=f"金額 (目前賠率: {odds})", placeholder="100", min_length=1)
        self.add_item(self.amt)

    async def on_submit(self, interaction: discord.Interaction):
        # 1. 驗證輸入格式
        try:
            amt = int(self.amt.value)
            if amt <= 0: raise ValueError
        except:
            return await interaction.response.send_message("❌ 請輸入有效的正整數金額", ephemeral=True)
        
        uid = str(interaction.user.id)
        w, _ = get_user_data(uid)
        
        # 2. 驗證餘額
        if w < amt:
            return await interaction.response.send_message("❌ 錢包餘額不足，快去領低保吧！", ephemeral=True)
        
        # 3. 執行扣款並紀錄注單 (此處建議未來也改為 RPC 以防競爭條件) [cite: 7]
        supabase.table("Users").update({"wallet": w - amt}).eq("user_id", uid).execute()
        supabase.table("Bets").insert({
            "user_id": uid, "event_id": self.event_id, "choice": self.choice, "amount": amt, "locked_odds": self.odds
        }).execute()
        
        await interaction.response.send_message(f"✅ 成功下注 `${amt}`！中獎將依據賠率 `{self.odds}` 派彩。", ephemeral=True)

class BetView(discord.ui.View):
    def __init__(self, event_id, o_a, o_b, o_c, title):
        super().__init__(timeout=None) # 持久化 View，防止重啟失效
        self.eid, self.odds, self.title = event_id, {'A': o_a, 'B': o_b, 'C': o_c}, title

    @discord.ui.button(label="買 A (主勝)", style=discord.ButtonStyle.green, custom_id="bet_a")
    async def b_a(self, i, b): await i.response.send_modal(BetModal(self.eid, 'A', self.odds['A'], self.title))

    @discord.ui.button(label="買 B (和局)", style=discord.ButtonStyle.gray, custom_id="bet_b")
    async def b_b(self, i, b): await i.response.send_modal(BetModal(self.eid, 'B', self.odds['B'], self.title))

    @discord.ui.button(label="買 C (客勝)", style=discord.ButtonStyle.red, custom_id="bet_c")
    async def b_c(self, i, b): await i.response.send_modal(BetModal(self.eid, 'C', self.odds['C'], self.title))

# --- 指令系統 ---
bot = SakunaBot()

@bot.tree.command(name="balance", description="查看我的資產狀況")
async def balance(interaction: discord.Interaction):
    w, b = get_user_data(interaction.user.id)
    await interaction.response.send_message(f"👛 錢包餘額: `${w}`\n🏦 銀行存款: `${b}`", ephemeral=True)

@bot.tree.command(name="auto_open", description="【管理員】抓取最新歐聯賠率並開盤")
async def auto_open(interaction: discord.Interaction):
    if interaction.user.id != ADMIN_ID:
        return await interaction.response.send_message("❌ 權限不足", ephemeral=True)
    
    await interaction.response.defer(ephemeral=True) # 防止 API 響應過慢導致 Timeout
    
    url = "https://api.the-odds-api.com/v4/sports/soccer_uefa_champs_league/odds/"
    params = {'apiKey': API_KEY, 'regions': 'uk', 'markets': 'h2h', 'oddsFormat': 'decimal'}
    
    try:
        async with bot.session.get(url, params=params) as resp:
            data = await resp.json()

        for match in data[:3]: # 每次僅顯示最新 3 場，防止 Discord Embed 堆疊過多
            title = f"{match['home_team']} vs {match['away_team']}"
            outcomes = match['bookmakers'][0]['markets'][0]['outcomes']
            o_a = next(o['price'] for o in outcomes if o['name'] == match['home_team'])
            o_c = next(o['price'] for o in outcomes if o['name'] == match['away_team'])
            o_b = next(o['price'] for o in outcomes if o['name'] == 'Draw')
            
            # 寫入 Events 表 
            res = supabase.table("Events").insert({
                "title": title, "odds_a": o_a, "odds_b": o_b, "odds_c": o_c, "status": 0
            }).execute()
            
            view = BetView(res.data[0]['event_id'], o_a, o_b, o_c, title)
            embed = discord.Embed(title="🏟️ CasinOYS 歐聯即時開盤", description=f"**{title}**", color=0x3498db)
            embed.add_field(name="🏠 主勝 (A)", value=f"賠率: {o_a}")
            embed.add_field(name="🤝 和局 (B)", value=f"賠率: {o_b}")
            embed.add_field(name="🚩 客勝 (C)", value=f"賠率: {o_c}")
            embed.set_footer(text="請選擇下方按鈕進行下注")
            await interaction.channel.send(embed=embed, view=view)
            
        await interaction.followup.send("✅ 歐聯賠率同步完成，盤口已開啟。")
    except Exception as e:
        await interaction.followup.send(f"❌ 開盤失敗: {e}")
    gc.collect()

# --- 主程式進入點 ---
if __name__ == '__main__':
    bot.run(TOKEN)

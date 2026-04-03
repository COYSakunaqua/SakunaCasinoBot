import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import aiohttp
import gc
from supabase import create_client, Client
from dotenv import load_dotenv

# 1. 初始化與環境變數
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('ODDS_API_KEY')
SB_URL = os.getenv('SUPABASE_URL')
SB_KEY = os.getenv('SUPABASE_KEY')
ADMIN_ID = int(os.getenv('ADMIN_ID', 0))

# 初始化 Supabase
supabase: Client = create_client(SB_URL, SB_KEY)

class SakunaBot(commands.Bot):
    def __init__(self):
        # 記憶體優化：只開啟必要的 Intents
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)
        self.session = None # 預留給 aiohttp session

    async def setup_hook(self):
        # 初始化持久化 Session
        self.session = aiohttp.ClientSession()
        # 同步 Slash 指令
        await self.tree.sync()
        self.auto_settle_task.start()
        self.memory_cleaner.start()
        print(f"✅ CasinOYS 系統就緒 | RAM 防護模式已開啟", flush=True)

    async def close(self):
        # 關閉時清理資源
        await super().close()
        if self.session:
            await self.session.close()

    # --- 記憶體防線：每 30 分鐘清理一次 ---
    @tasks.loop(minutes=30)
    async def memory_cleaner(self):
        gc.collect()
        # 針對 DisCloud 100MB 環境，監控並強制釋放
        print("🧹 [System] Memory cleanup executed.", flush=True)

    # --- 背景自動結算：優化 API 配額消耗 ---
    @tasks.loop(minutes=180)
    async def auto_settle_task(self):
        if not API_KEY: return
        
        # 預檢：若無待結算賽事則不調用 API (節省 Quota)
        pending = supabase.table("Events").select("event_id").eq("status", 0).execute()
        if not pending.data:
            return

        print("🔍 [Auto-Settle] Fetching match results...", flush=True)
        url = "https://api.the-odds-api.com/v4/sports/soccer_uefa_champs_league/scores/"
        params = {'apiKey': API_KEY, 'daysFrom': 1}
        
        try:
            async with self.session.get(url, params=params) as resp:
                if resp.status != 200: return
                matches = await resp.json()
                
                for match in matches:
                    if not match['completed']: continue
                    h_team, a_team = match['home_team'], match['away_team']
                    # 邏輯提取比分
                    h_score = next(s['score'] for s in match['scores'] if s['name'] == h_team)
                    a_score = next(s['score'] for s in match['scores'] if s['name'] == a_team)
                    win_choice = 'A' if h_score > a_score else 'C' if a_score > h_score else 'B'
                    title = f"{h_team} vs {a_team}"
                    
                    # 查找對應賽事
                    res = supabase.table("Events").select("event_id").eq("title", title).eq("status", 0).execute()
                    if res.data:
                        for event in res.data:
                            await self.do_payout(event['event_id'], win_choice, title)
                del matches
                gc.collect()
        except Exception as e:
            print(f"❌ Settle Error: {e}", flush=True)

    async def do_payout(self, event_id, win_choice, title):
        # 獲取該賽事的所有中獎注單
        bets = supabase.table("Bets").select("*").eq("event_id", event_id).eq("choice", win_choice).execute()
        
        # 執行派彩流程
        for bet in bets.data:
            payout = int(bet['amount'] * bet['locked_odds'])
            # 使用 RPC 增加餘額
            supabase.rpc('increment_wallet', {'row_id': bet['user_id'], 'amount': payout}).execute()
        
        # 更新賽事狀態為已結算 (2)
        supabase.table("Events").update({"status": 2}).eq("event_id", event_id).execute()
        print(f"💰 Payout completed: {title}", flush=True)

# --- 資料存取層 (DAL) ---
def get_user_data(user_id):
    uid = str(user_id)
    res = supabase.table("Users").select("*").eq("user_id", uid).execute()
    if not res.data:
        supabase.table("Users").insert({"user_id": uid, "wallet": 1000}).execute()
        return 1000, 0
    return res.data[0]['wallet'], res.data[0]['bank']

# --- UI 元件 (Modals & Views) ---
class BetModal(discord.ui.Modal):
    def __init__(self, event_id, choice, odds, title):
        super().__init__(title=f"下注 - {title}")
        self.event_id, self.choice, self.odds = event_id, choice, odds
        self.amt = discord.ui.TextInput(label=f"金額 (賠率 {odds})", placeholder="輸入下注金額...")
        self.add_item(self.amt)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amt = int(self.amt.value)
            if amt <= 0: raise ValueError
        except: 
            return await interaction.response.send_message("❌ 請輸入有效的正整數金額", ephemeral=True)
        
        uid = str(interaction.user.id)
        w, _ = get_user_data(uid)
        
        if w < amt: 
            return await interaction.response.send_message("❌ 錢包餘額不足", ephemeral=True)
        
        # 扣款並寫入注單 (應考慮交易原子性，此處維持現有邏輯)
        supabase.table("Users").update({"wallet": w - amt}).eq("user_id", uid).execute()
        supabase.table("Bets").insert({
            "user_id": uid, "event_id": self.event_id, "choice": self.choice, "amount": amt, "locked_odds": self.odds
        }).execute()
        
        await interaction.response.send_message(f"✅ 成功下注 `${amt}` (賠率 {self.odds})！", ephemeral=True)

class BetView(discord.ui.View):
    def __init__(self, event_id, o_a, o_b, o_c, title):
        super().__init__(timeout=None) # DisCloud 模式下 View 需設為 None 以保持持久性
        self.eid, self.odds, self.title = event_id, {'A': o_a, 'B': o_b, 'C': o_c}, title

    @discord.ui.button(label="買 A (主勝)", style=discord.ButtonStyle.green)
    async def b_a(self, i, b): 
        await i.response.send_modal(BetModal(self.eid, 'A', self.odds['A'], self.title))

    @discord.ui.button(label="買 B (和局)", style=discord.ButtonStyle.gray)
    async def b_b(self, i, b): 
        await i.response.send_modal(BetModal(self.eid, 'B', self.odds['B'], self.title))

    @discord.ui.button(label="買 C (客勝)", style=discord.ButtonStyle.red)
    async def b_c(self, i, b): 
        await i.response.send_modal(BetModal(self.eid, 'C', self.odds['C'], self.title))

# --- Slash Commands ---
bot = SakunaBot()

@bot.tree.command(name="balance", description="查看當前錢包與銀行餘額")
async def balance(interaction: discord.Interaction):
    w, b = get_user_data(interaction.user.id)
    await interaction.response.send_message(f"👛 錢包: `${w}` | 🏦 銀行: `${b}`", ephemeral=True)

@bot.tree.command(name="auto_open", description="【管理員】從 API 獲取最新歐聯賠率並開盤")
async def auto_open(interaction: discord.Interaction):
    if interaction.user.id != ADMIN_ID:
        return await interaction.response.send_message("❌ 權限不足", ephemeral=True)
    
    await interaction.response.defer(ephemeral=True) # 防止超時
    
    url = "https://api.the-odds-api.com/v4/sports/soccer_uefa_champs_league/odds/"
    params = {'apiKey': API_KEY, 'regions': 'uk', 'markets': 'h2h', 'oddsFormat': 'decimal'}
    
    try:
        async with bot.session.get(url, params=params) as resp:
            data = await resp.json()

        for match in data[:3]: # 每次僅顯示前三場
            title = f"{match['home_team']} vs {match['away_team']}"
            outcomes = match['bookmakers'][0]['markets'][0]['outcomes']
            o_a = next(o['price'] for o in outcomes if o['name'] == match['home_team'])
            o_c = next(o['price'] for o in outcomes if o['name'] == match['away_team'])
            o_b = next(o['price'] for o in outcomes if o['name'] == 'Draw')
            
            # 寫入資料庫
            res = supabase.table("Events").insert({
                "title": title, "odds_a": o_a, "odds_b": o_b, "odds_c": o_c, "status": 0
            }).execute()
            
            view = BetView(res.data[0]['event_id'], o_a, o_b, o_c, title)
            embed = discord.Embed(title="🏟️ 歐聯賽事開盤", description=title, color=0x3498db)
            embed.add_field(name="A (主勝)", value=f"{o_a}")
            embed.add_field(name="B (和局)", value=f"{o_b}")
            embed.add_field(name="C (客勝)", value=f"{o_c}")
            await interaction.channel.send(embed=embed, view=view)
            
        await interaction.followup.send("✅ 開盤成功")
    except Exception as e:
        await interaction.followup.send(f"❌ 開盤失敗: {e}")
    gc.collect()

# --- 啟動入口 ---
if __name__ == '__main__':
    bot.run(TOKEN)

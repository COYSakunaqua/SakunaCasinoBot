import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import time
import aiohttp
import gc  # 導入垃圾回收
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
        # 記憶體優化：只開啟必要的 Intents，關閉成員與訊息緩存
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)

    async def setup_hook(self):
        # 同步 Slash 指令
        await self.tree.sync()
        self.auto_settle_task.start()
        print(f"✅ 雲端 Bot 已就緒 | 記憶體防護啟動", flush=True)

    # --- 核心：定時清理記憶體 (每 30 分鐘執行一次) ---
    @tasks.loop(minutes=30)
    async def memory_cleaner(self):
        gc.collect()
        print("🧹 [系統] 執行記憶體清理成功", flush=True)

    # --- 背景自動結算 ---
    @tasks.loop(minutes=180)
    async def auto_settle_task(self):
        if not API_KEY: return
        print("🔍 [自動結算] 正在抓取賽果...", flush=True)
        url = "https://api.the-odds-api.com/v4/sports/soccer_uefa_champs_league/scores/"
        params = {'apiKey': API_KEY, 'daysFrom': 1}
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, params=params) as resp:
                    if resp.status != 200: return
                    matches = await resp.json()
                    # 處理完立刻清理
                    for match in matches:
                        if not match['completed']: continue
                        h_team, a_team = match['home_team'], match['away_team']
                        h_score = next(s['score'] for s in match['scores'] if s['name'] == h_team)
                        a_score = next(s['score'] for s in match['scores'] if s['name'] == a_team)
                        win_choice = 'A' if h_score > a_score else 'C' if a_score > h_score else 'B'
                        title = f"{h_team} vs {a_team}"
                        
                        res = supabase.table("Events").select("event_id").eq("title", title).eq("status", 0).execute()
                        if res.data:
                            for event in res.data:
                                await self.do_payout(event['event_id'], win_choice, title)
                    del matches # 手動釋放記憶體
                    gc.collect()
            except Exception as e:
                print(f"❌ 結算失敗: {e}", flush=True)

    async def do_payout(self, event_id, win_choice, title):
        bets = supabase.table("Bets").select("*").eq("event_id", event_id).eq("choice", win_choice).execute()
        for bet in bets.data:
            payout = int(bet['amount'] * bet['locked_odds'])
            supabase.rpc('increment_wallet', {'row_id': bet['user_id'], 'amount': payout}).execute()
        supabase.table("Events").update({"status": 2}).eq("event_id", event_id).execute()
        print(f"💰 成功結算: {title}", flush=True)

# --- 全域 Helper ---
def get_user_data(user_id):
    uid = str(user_id)
    res = supabase.table("Users").select("*").eq("user_id", uid).execute()
    if not res.data:
        supabase.table("Users").insert({"user_id": uid, "wallet": 1000}).execute()
        return 1000, 0
    return res.data[0]['wallet'], res.data[0]['bank']

# --- UI 元件 ---
class BetModal(discord.ui.Modal):
    def __init__(self, event_id, choice, odds, title):
        super().__init__(title=f"下注 - {title}")
        self.event_id, self.choice, self.odds = event_id, choice, odds
        self.amt = discord.ui.TextInput(label=f"金額 (賠率 {odds})", placeholder="100")
        self.add_item(self.amt)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amt = int(self.amt.value)
            if amt <= 0: raise ValueError
        except: return await interaction.response.send_message("❌ 請輸入正整數", ephemeral=True)
        
        uid = str(interaction.user.id)
        w, _ = get_user_data(uid)
        if w < amt: return await interaction.response.send_message("❌ 錢包不足", ephemeral=True)
        
        supabase.table("Users").update({"wallet": w - amt}).eq("user_id", uid).execute()
        supabase.table("Bets").insert({
            "user_id": uid, "event_id": self.event_id, "choice": self.choice, "amount": amt, "locked_odds": self.odds
        }).execute()
        await interaction.response.send_message(f"✅ 下注 `${amt}` 成功！", ephemeral=True)

class BetView(discord.ui.View):
    def __init__(self, event_id, o_a, o_b, o_c, title):
        super().__init__(timeout=None)
        self.eid, self.odds, self.title = event_id, {'A': o_a, 'B': o_b, 'C': o_c}, title
    @discord.ui.button(label="買 A (主勝)", style=discord.ButtonStyle.green)
    async def b_a(self, i, b): await i.response.send_modal(BetModal(self.eid, 'A', self.odds['A'], self.title))
    @discord.ui.button(label="買 B (和局)", style=discord.ButtonStyle.gray)
    async def b_b(self, i, b): await i.response.send_modal(BetModal(self.eid, 'B', self.odds['B'], self.title))
    @discord.ui.button(label="買 C (客勝)", style=discord.ButtonStyle.red)
    async def b_c(self, i, b): await i.response.send_modal(BetModal(self.eid, 'C', self.odds['C'], self.title))

# --- 指令 ---
bot = SakunaBot()

@bot.tree.command(name="balance", description="查看我的錢包餘額")
async def balance(interaction: discord.Interaction):
    w, b = get_user_data(interaction.user.id)
    await interaction.response.send_message(f"👛 錢包: `${w}` | 🏦 銀行: `${b}`", ephemeral=True)

@bot.tree.command(name="auto_open", description="【管理員】自動開盤 (歐聯)")
async def auto_open(interaction: discord.Interaction):
    if interaction.user.id != ADMIN_ID:
        return await interaction.response.send_message("❌ 權限不足", ephemeral=True)
    
    await interaction.response.send_message("🔍 正在獲取賠率...", ephemeral=True)
    url = "https://api.the-odds-api.com/v4/sports/soccer_uefa_champs_league/odds/"
    params = {'apiKey': API_KEY, 'regions': 'uk', 'markets': 'h2h', 'oddsFormat': 'decimal'}
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            data = await resp.json()

    for match in data[:3]:
        title = f"{match['home_team']} vs {match['away_team']}"
        try:
            outcomes = match['bookmakers'][0]['markets'][0]['outcomes']
            o_a = next(o['price'] for o in outcomes if o['name'] == match['home_team'])
            o_c = next(o['price'] for o in outcomes if o['name'] == match['away_team'])
            o_b = next(o['price'] for o in outcomes if o['name'] == 'Draw')
            
            res = supabase.table("Events").insert({
                "title": title, "odds_a": o_a, "odds_b": o_b, "odds_c": o_c, "status": 0
            }).execute()
            
            view = BetView(res.data[0]['event_id'], o_a, o_b, o_c, title)
            embed = discord.Embed(title="🏟️ 歐聯開盤", description=title, color=0x3498db)
            embed.add_field(name="A 主", value=o_a); embed.add_field(name="B 和", value=o_b); embed.add_field(name="C 客", value=o_c)
            await interaction.channel.send(embed=embed, view=view)
        except: continue
    gc.collect()

# --- 啟動 ---
if __name__ == '__main__':
    bot.run(TOKEN)

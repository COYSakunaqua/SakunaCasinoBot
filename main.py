import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.app_commands import Choice
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

supabase: Client = create_client(SB_URL, SB_KEY)

# 聯賽 API Key 對應表 (Top 5 + Cups + World Cup + UEFA)
LEAGUES = {
    "soccer_epl": "英超 (EPL)",
    "soccer_spain_la_liga": "西甲 (La Liga)",
    "soccer_italy_serie_a": "意甲 (Serie A)",
    "soccer_germany_bundesliga": "德甲 (Bundesliga)",
    "soccer_france_ligue_one": "法甲 (Ligue 1)",
    "soccer_england_efl_cup": "英格蘭聯賽盃 (EFL/FA)",
    "soccer_spain_copa_del_rey": "西班牙國王盃",
    "soccer_italy_coppa_italia": "意大利盃",
    "soccer_germany_dfb_pokal": "德國盃",
    "soccer_france_coupe_de_france": "法國盃",
    "soccer_uefa_champs_league": "歐聯 (UCL)",
    "soccer_uefa_europa_league": "歐霸 (UEL)",
    "soccer_uefa_europa_conference_league": "歐協聯 (UECL)",
    "soccer_fifa_world_cup": "世界盃 (World Cup)"
}

class SakunaBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)
        self.session = None
        # 記憶體優化：只追蹤有開盤的聯賽，避免 API Quota 浪費
        self.active_leagues = set() 

    async def setup_hook(self):
        self.session = aiohttp.ClientSession()
        await self.tree.sync()
        self.auto_settle_task.start()
        self.memory_cleaner.start()
        print(f"✅ CasinOYS 核心啟動 | 銀行模組上線 | 支援 14 大賽事", flush=True)

    async def close(self):
        if self.session: await self.session.close()
        await super().close()

    # --- 記憶體防護：每 30 分鐘執行 ---
    @tasks.loop(minutes=30)
    async def memory_cleaner(self):
        gc.collect()
        print("🧹 [System] GC 回收完成", flush=True)

    # --- 節流優化版：背景自動結算 ---
    @tasks.loop(minutes=180)
    async def auto_settle_task(self):
        if not API_KEY or not self.active_leagues: return
        
        check = supabase.table("Events").select("event_id").eq("status", 0).execute()
        if not check.data: return

        print(f"🔍 [Auto-Settle] 正在掃描活動聯賽: {self.active_leagues}", flush=True)
        
        # 僅針對有開盤的聯賽發送 API，極限節省 Quota
        for sport_key in list(self.active_leagues):
            url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/scores/"
            params = {'apiKey': API_KEY, 'daysFrom': 1}
            
            try:
                async with self.session.get(url, params=params) as resp:
                    if resp.status != 200: continue
                    matches = await resp.json()
                    
                    for match in matches:
                        if not match['completed']: continue
                        
                        h_team, a_team = match['home_team'], match['away_team']
                        h_score = next(s['score'] for s in match['scores'] if s['name'] == h_team)
                        a_score = next(s['score'] for s in match['scores'] if s['name'] == a_team)
                        win_choice = 'A' if h_score > a_score else 'C' if a_score > h_score else 'B'
                        title = f"{h_team} vs {a_team}"
                        
                        event_res = supabase.table("Events").select("event_id").eq("title", title).eq("status", 0).execute()
                        if event_res.data:
                            for event in event_res.data:
                                await self.do_payout(event['event_id'], win_choice, title)
                    del matches
                    gc.collect()
            except Exception as e:
                print(f"❌ [Error] {sport_key} 結算異常: {e}", flush=True)

    async def do_payout(self, event_id, win_choice, title):
        supabase.table("Events").update({"status": 2}).eq("event_id", event_id).execute()
        bets = supabase.table("Bets").select("*").eq("event_id", event_id).eq("choice", win_choice).execute()
        for bet in bets.data:
            payout = int(bet['amount'] * bet['locked_odds'])
            supabase.rpc('increment_wallet', {'row_id': bet['user_id'], 'amount': payout}).execute()
        print(f"💰 [Payout] {title} 結算完成", flush=True)

# --- DAL (資料存取層) ---
def get_user_data(user_id):
    uid = str(user_id)
    res = supabase.table("Users").select("*").eq("user_id", uid).execute()
    if not res.data:
        supabase.table("Users").insert({"user_id": uid, "wallet": 1000, "bank": 0}).execute()
        return 1000, 0
    return res.data[0]['wallet'], res.data[0]['bank']

# --- UI 元件 ---
class BetModal(discord.ui.Modal):
    def __init__(self, event_id, choice, odds, title):
        super().__init__(title=f"下注確認 - {title}")
        self.event_id, self.choice, self.odds = event_id, choice, odds
        self.amt = discord.ui.TextInput(label=f"下注金額 (賠率: {odds})", placeholder="例如: 100")
        self.add_item(self.amt)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amt = int(self.amt.value)
            if amt <= 0: raise ValueError
        except:
            return await interaction.response.send_message("❌ 格式錯誤", ephemeral=True)
        
        uid = str(interaction.user.id)
        w, _ = get_user_data(uid)
        if w < amt: return await interaction.response.send_message("❌ 餘額不足", ephemeral=True)
        
        supabase.table("Users").update({"wallet": w - amt}).eq("user_id", uid).execute()
        supabase.table("Bets").insert({
            "user_id": uid, "event_id": self.event_id, "choice": self.choice, "amount": amt, "locked_odds": self.odds
        }).execute()
        await interaction.response.send_message(f"✅ 成功下注 `${amt}`！", ephemeral=True)

class BetView(discord.ui.View):
    def __init__(self, event_id, o_a, o_b, o_c, title, h_name, a_name):
        super().__init__(timeout=None)
        self.eid, self.odds, self.title = event_id, {'A': o_a, 'B': o_b, 'C': o_c}, title
        self.b_a.label, self.b_b.label, self.b_c.label = f"{h_name} Win", "Draw", f"{a_name} Win"

    @discord.ui.button(label="A", style=discord.ButtonStyle.green, custom_id="btn_a")
    async def b_a(self, i, b): await i.response.send_modal(BetModal(self.eid, 'A', self.odds['A'], self.title))
    @discord.ui.button(label="B", style=discord.ButtonStyle.gray, custom_id="btn_b")
    async def b_b(self, i, b): await i.response.send_modal(BetModal(self.eid, 'B', self.odds['B'], self.title))
    @discord.ui.button(label="C", style=discord.ButtonStyle.red, custom_id="btn_c")
    async def b_c(self, i, b): await i.response.send_modal(BetModal(self.eid, 'C', self.odds['C'], self.title))

# --- 指令系統 ---
bot = SakunaBot()

@bot.tree.command(name="balance", description="查看當前資產")
async def balance(interaction: discord.Interaction):
    w, b = get_user_data(interaction.user.id)
    await interaction.response.send_message(f"👛 錢包: `${w}` | 🏦 銀行: `${b}`", ephemeral=True)

# 銀行金融系統：存款
@bot.tree.command(name="deposit", description="將錢包的錢存入銀行")
async def deposit(interaction: discord.Interaction, amount: int):
    if amount <= 0: return await interaction.response.send_message("❌ 金額必須大於 0", ephemeral=True)
    uid = str(interaction.user.id)
    w, b = get_user_data(uid)
    if w < amount: return await interaction.response.send_message("❌ 錢包餘額不足", ephemeral=True)
    
    supabase.table("Users").update({"wallet": w - amount, "bank": b + amount}).eq("user_id", uid).execute()
    await interaction.response.send_message(f"✅ 成功存款 `${amount}`入銀行！", ephemeral=True)

# 銀行金融系統：提款
@bot.tree.command(name="withdraw", description="將銀行的錢提領至錢包")
async def withdraw(interaction: discord.Interaction, amount: int):
    if amount <= 0: return await interaction.response.send_message("❌ 金額必須大於 0", ephemeral=True)
    uid = str(interaction.user.id)
    w, b = get_user_data(uid)
    if b < amount: return await interaction.response.send_message("❌ 銀行存款不足", ephemeral=True)
    
    supabase.table("Users").update({"wallet": w + amount, "bank": b - amount}).eq("user_id", uid).execute()
    await interaction.response.send_message(f"✅ 成功提款 `${amount}`至錢包！", ephemeral=True)

# 擴展版開盤系統：支援選擇聯賽
@bot.tree.command(name="auto_open", description="【管理員】選擇特定聯賽開盤")
@app_commands.describe(league="選擇要獲取賠率的聯賽")
@app_commands.choices(league=[Choice(name=v, value=k) for k, v in LEAGUES.items()][:25]) # Discord 限制最多 25 個選項
async def auto_open(interaction: discord.Interaction, league: str):
    if interaction.user.id != ADMIN_ID:
        return await interaction.response.send_message("❌ 權限不足", ephemeral=True)
    
    await interaction.response.defer(ephemeral=True)
    bot.active_leagues.add(league) # 將選擇的聯賽加入記憶體追蹤名單
    
    url = f"https://api.the-odds-api.com/v4/sports/{league}/odds/"
    params = {'apiKey': API_KEY, 'regions': 'uk', 'markets': 'h2h', 'oddsFormat': 'decimal'}
    
    try:
        async with bot.session.get(url, params=params) as resp:
            data = await resp.json()
            if not data: return await interaction.followup.send("❌ 該聯賽目前無賽事賠率。")

        for match in data[:3]:
            h_name, a_name = match['home_team'], match['away_team']
            title = f"{h_name} vs {a_name}"
            
            outcomes = match['bookmakers'][0]['markets'][0]['outcomes']
            o_a = next(o['price'] for o in outcomes if o['name'] == h_name)
            o_c = next(o['price'] for o in outcomes if o['name'] == a_name)
            o_b = next(o['price'] for o in outcomes if o['name'] == 'Draw')
            
            res = supabase.table("Events").insert({
                "title": title, "odds_a": o_a, "odds_b": o_b, "odds_c": o_c, "status": 0
            }).execute()
            
            view = BetView(res.data[0]['event_id'], o_a, o_b, o_c, title, h_name, a_name)
            embed = discord.Embed(title=f"🏟️ {LEAGUES[league]} 盤口", description=f"**{title}**", color=0x3498db)
            embed.add_field(name=f"🏠 {h_name}", value=f"賠率: {o_a}")
            embed.add_field(name="🤝 Draw", value=f"賠率: {o_b}")
            embed.add_field(name=f"🚩 {a_name}", value=f"賠率: {o_c}")
            await interaction.channel.send(embed=embed, view=view)
            
        await interaction.followup.send(f"✅ {LEAGUES[league]} 開盤完成。")
    except Exception as e:
        await interaction.followup.send(f"❌ 開盤失敗: {e}")
    gc.collect()

if __name__ == '__main__':
    bot.run(TOKEN)

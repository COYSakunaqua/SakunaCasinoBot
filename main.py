import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import gc
import aiohttp
import datetime
import asyncio
from supabase import create_client, Client
from dotenv import load_dotenv

# --- 1. 系統初始化與環境變數 ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('ODDS_API_KEY')
SB_URL = os.getenv('SUPABASE_URL')
SB_KEY = os.getenv('SUPABASE_KEY')

supabase: Client = create_client(SB_URL, SB_KEY)

# ▼▼▼ 必須修改區：請在這裡填入你剛剛複製的 Discord 頻道 ID ▼▼▼
CHANNEL_ID_ENGLISH = 1489625770232909985  # 替換為英超頻道 ID
CHANNEL_ID_SPAIN   = 1489625792903118929  # 替換為西甲頻道 ID
CHANNEL_ID_GERMAN  = 1489625813098692698  # 替換為德甲頻道 ID
CHANNEL_ID_UEFA    = 1489625832166002850  # 替換為 UEFA 頻道 ID (歐聯與歐霸共用)
# ▲▲▲ 必須修改區：請在這裡填入你剛剛複製的 Discord 頻道 ID ▲▲▲

# --- 2. 聯賽與專屬頻道映射表 ---
LEAGUE_CHANNELS = {
    "soccer_epl": {"name": "英超 (EPL)", "id": CHANNEL_ID_ENGLISH},
    "soccer_spain_la_liga": {"name": "西甲 (La Liga)", "id": CHANNEL_ID_SPAIN},
    "soccer_germany_bundesliga": {"name": "德甲 (Bundesliga)", "id": CHANNEL_ID_GERMAN},
    "soccer_uefa_champs_league": {"name": "歐聯 (UCL)", "id": CHANNEL_ID_UEFA},
    "soccer_uefa_europa_league": {"name": "歐霸 (UEL)", "id": CHANNEL_ID_UEFA}
}

HKT = datetime.timezone(datetime.timedelta(hours=8))
SCAN_TIME = datetime.time(hour=7, minute=0, tzinfo=HKT)

class SakunaBot(commands.Bot):
    def __init__(self):
        # 記憶體防護：關閉非必要 Intents
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)
        self.session = None

    async def setup_hook(self):
        self.session = aiohttp.ClientSession()
        await self.tree.sync()
        self.daily_routine_task.start()
        self.memory_cleaner.start()
        print(f"✅ CasinOYS 啟動 | 防超時 defer() 機制已實裝", flush=True)

    async def close(self):
        if self.session: await self.session.close()
        await super().close()

    @tasks.loop(minutes=30)
    async def memory_cleaner(self):
        gc.collect()

    @tasks.loop(time=SCAN_TIME)
    async def daily_routine_task(self):
        if not API_KEY: return
        print("🌅 [Daily Routine] 開始執行每日 07:00 例行任務...", flush=True)
        await self.process_settlements()
        await self.process_new_odds()
        print("✅ [Daily Routine] 今日結算與開盤全數完成！", flush=True)

    async def process_settlements(self):
        check = supabase.table("Events").select("event_id").eq("status", 0).execute()
        if not check.data: return

        for league_key in LEAGUE_CHANNELS.keys():
            url = f"https://api.the-odds-api.com/v4/sports/{league_key}/scores/"
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
                        
                        res = supabase.table("Events").select("event_id").eq("title", title).eq("status", 0).execute()
                        if res.data:
                            for event in res.data:
                                await self.do_payout(event['event_id'], win_choice, title)
                    del matches
                    gc.collect() 
            except Exception as e:
                print(f"❌ [Error] 結算異常: {e}", flush=True)

    async def process_new_odds(self):
        for league_key, info in LEAGUE_CHANNELS.items():
            channel = self.get_channel(info["id"])
            if not channel: continue
                
            url = f"https://api.the-odds-api.com/v4/sports/{league_key}/odds/"
            params = {'apiKey': API_KEY, 'regions': 'uk', 'markets': 'h2h', 'oddsFormat': 'decimal'}
            
            try:
                async with self.session.get(url, params=params) as resp:
                    if resp.status != 200: continue
                    data = await resp.json()
                    if not data: continue

                for match in data[:3]:
                    h_name, a_name = match['home_team'], match['away_team']
                    title = f"{h_name} vs {a_name}"
                    
                    duplicate = supabase.table("Events").select("event_id").eq("title", title).eq("status", 0).execute()
                    if duplicate.data: continue
                    
                    outcomes = match['bookmakers'][0]['markets'][0]['outcomes']
                    o_a = next(o['price'] for o in outcomes if o['name'] == h_name)
                    o_c = next(o['price'] for o in outcomes if o['name'] == a_name)
                    o_b = next(o['price'] for o in outcomes if o['name'] == 'Draw')
                    
                    res = supabase.table("Events").insert({
                        "title": title, "odds_a": o_a, "odds_b": o_b, "odds_c": o_c, "status": 0
                    }).execute()
                    
                    view = BetView(res.data[0]['event_id'], o_a, o_b, o_c, title, h_name, a_name)
                    embed = discord.Embed(title=f"🏟️ {info['name']} 今日盤口", description=f"**{title}**", color=0x3498db)
                    embed.add_field(name=f"🏠 {h_name}", value=f"賠率: {o_a}")
                    embed.add_field(name="🤝 Draw", value=f"賠率: {o_b}")
                    embed.add_field(name=f"🚩 {a_name}", value=f"賠率: {o_c}")
                    
                    await channel.send(embed=embed, view=view)
                    await asyncio.sleep(1) 
                    
            except Exception as e:
                print(f"❌ [Error] 獲取 {info['name']} 賠率失敗: {e}", flush=True)
            gc.collect()

    async def do_payout(self, event_id, win_choice, title):
        supabase.table("Events").update({"status": 2}).eq("event_id", event_id).execute()
        bets = supabase.table("Bets").select("*").eq("event_id", event_id).eq("choice", win_choice).execute()
        for bet in bets.data:
            payout = int(bet['amount'] * bet['locked_odds'])
            supabase.rpc('increment_wallet', {'row_id': bet['user_id'], 'amount': payout}).execute()

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

# --- 指令系統 (全面加入 defer 機制) ---
bot = SakunaBot()

@bot.tree.command(name="balance", description="查看當前資產")
async def balance(interaction: discord.Interaction):
    # 第一步：先延遲回應，爭取處理時間
    await interaction.response.defer(ephemeral=True)
    try:
        w, b = get_user_data(interaction.user.id)
        # 第二步：處理完成後回傳結果 (使用 followup)
        await interaction.followup.send(f"👛 錢包: `${w}` | 🏦 銀行: `${b}`", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ 讀取資料失敗: {e}", ephemeral=True)

@bot.tree.command(name="deposit", description="將錢包的錢存入銀行")
async def deposit(interaction: discord.Interaction, amount: int):
    await interaction.response.defer(ephemeral=True)
    try:
        if amount <= 0: 
            return await interaction.followup.send("❌ 金額必須大於 0", ephemeral=True)
        
        uid = str(interaction.user.id)
        w, b = get_user_data(uid)
        
        if w < amount: 
            return await interaction.followup.send("❌ 錢包餘額不足", ephemeral=True)
        
        supabase.table("Users").update({"wallet": w - amount, "bank": b + amount}).eq("user_id", uid).execute()
        await interaction.followup.send(f"✅ 成功存款 `${amount}`入銀行！", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ 存款失敗: {e}", ephemeral=True)

@bot.tree.command(name="withdraw", description="將銀行的錢提領至錢包")
async def withdraw(interaction: discord.Interaction, amount: int):
    await interaction.response.defer(ephemeral=True)
    try:
        if amount <= 0: 
            return await interaction.followup.send("❌ 金額必須大於 0", ephemeral=True)
        
        uid = str(interaction.user.id)
        w, b = get_user_data(uid)
        
        if b < amount: 
            return await interaction.followup.send("❌ 銀行存款不足", ephemeral=True)
        
        supabase.table("Users").update({"wallet": w + amount, "bank": b - amount}).eq("user_id", uid).execute()
        await interaction.followup.send(f"✅ 成功提款 `${amount}`至錢包！", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ 提款失敗: {e}", ephemeral=True)

if __name__ == '__main__':
    bot.run(TOKEN)

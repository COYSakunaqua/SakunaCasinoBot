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

# --- 1. 系統初始化 ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('ODDS_API_KEY')
SB_URL = os.getenv('SUPABASE_URL')
SB_KEY = os.getenv('SUPABASE_KEY')
ADMIN_ID = int(os.getenv('ADMIN_ID', 0))

supabase: Client = create_client(SB_URL, SB_KEY)

# --- 2. 頻道設定 ---
# 請務必填入正確的頻道 ID
CHANNEL_ID_ENGLISH = 1489625770232909985  # 替換為英超頻道 ID
CHANNEL_ID_SPAIN   = 1489625792903118929  # 替換為西甲頻道 ID
CHANNEL_ID_GERMAN  = 1489625813098692698  # 替換為德甲頻道 ID
CHANNEL_ID_UEFA    = 1489625832166002850  # 替換為 UEFA 頻道 ID (歐聯與歐霸共用)
CHANNEL_ID_GUIDE   = 1489640799636554070  # 「新手指南」頻道 ID
CHANNEL_ID_BUG     = 1489643447861248133  # 「questions-bugs-suggestions」頻道 ID

ERR_FOOTER = f"\n⚠️ 如持續出錯，請前往 <#{CHANNEL_ID_BUG}> 回報。"

LEAGUE_CHANNELS = {
    "soccer_epl": {"name": "英超 (EPL)", "id": CHANNEL_ID_ENGLISH},
    "soccer_spain_la_liga": {"name": "西甲 (La Liga)", "id": CHANNEL_ID_SPAIN},
    "soccer_germany_bundesliga": {"name": "德甲 (Bund)", "id": CHANNEL_ID_GERMAN},
    "soccer_uefa_champs_league": {"name": "歐聯 (UCL)", "id": CHANNEL_ID_UEFA},
    "soccer_uefa_europa_league": {"name": "歐霸 (UEL)", "id": CHANNEL_ID_UEFA}
}

HKT = datetime.timezone(datetime.timedelta(hours=8))
SCAN_TIME = datetime.time(hour=7, minute=0, tzinfo=HKT)
FINANCE_TIME = datetime.time(hour=7, minute=15, tzinfo=HKT)

class SakunaBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True # 開啟新人偵測
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)
        self.session = None

    async def setup_hook(self):
        self.session = aiohttp.ClientSession()
        await self.tree.sync()
        self.daily_routine_task.start()
        self.finance_routine_task.start() 
        self.memory_cleaner.start()
        print(f"✅ CasinOYS 核心啟動 | 數據庫: Users | 利息: 0.2%", flush=True)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        channel = self.get_channel(CHANNEL_ID_GUIDE)
        if channel:
            await channel.send(f"🎊 歡迎 {member.mention}！請閱讀上方指南，並輸入 `/daily` 領取開局 **$10,000** 資本！")

    @tasks.loop(minutes=30)
    async def memory_cleaner(self):
        gc.collect()

    # --- 每日 07:00 掃描 ---
    @tasks.loop(time=SCAN_TIME)
    async def daily_routine_task(self):
        if not API_KEY: return
        await self.process_settlements()
        await self.process_new_odds()

    # --- 每日 07:15 利息 ---
    @tasks.loop(time=FINANCE_TIME)
    async def finance_routine_task(self):
        try:
            supabase.rpc('process_daily_finance', {}).execute()
        except Exception:
            pass

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
                            for event in res.data: await self.do_payout(event['event_id'], win_choice, title)
                    del matches
                    gc.collect() 
            except Exception: pass

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
                for match in data[:3]:
                    h_name, a_name = match['home_team'], match['away_team']
                    title = f"{h_name} vs {a_name}"
                    duplicate = supabase.table("Events").select("event_id").eq("title", title).eq("status", 0).execute()
                    if duplicate.data: continue
                    outcomes = match['bookmakers'][0]['markets'][0]['outcomes']
                    o_a = next(o['price'] for o in outcomes if o['name'] == h_name)
                    o_c = next(o['price'] for o in outcomes if o['name'] == a_name)
                    o_b = next(o['price'] for o in outcomes if o['name'] == 'Draw')
                    o_a, o_b, o_c = round(o_a * 1.2, 2), round(o_b * 1.2, 2), round(o_c * 1.2, 2)
                    res = supabase.table("Events").insert({"title": title, "odds_a": o_a, "odds_b": o_b, "odds_c": o_c, "status": 0}).execute()
                    view = BetView(res.data[0]['event_id'], o_a, o_b, o_c, title, h_name, a_name)
                    embed = discord.Embed(title=f"🏟️ {info['name']} 今日盤口", description=f"**{title}**", color=0xf1c40f)
                    embed.add_field(name=f"🏠 {h_name}", value=f"賠率: {o_a}"); embed.add_field(name="🤝 Draw", value=f"賠率: {o_b}"); embed.add_field(name=f"🚩 {a_name}", value=f"賠率: {o_c}")
                    await channel.send(embed=embed, view=view)
                    await asyncio.sleep(1) 
            except Exception: pass
            gc.collect()

    async def do_payout(self, event_id, win_choice, title):
        supabase.table("Events").update({"status": 2}).eq("event_id", event_id).execute()
        bets = supabase.table("Bets").select("*").eq("event_id", event_id).eq("choice", win_choice).execute()
        for bet in bets.data:
            payout = int(bet['amount'] * bet['locked_odds'])
            supabase.rpc('increment_bank', {'row_id': bet['user_id'], 'amount': payout}).execute()

def get_user_data(user_id):
    uid = str(user_id)
    res = supabase.table("Users").select("*").eq("user_id", uid).execute()
    if not res.data:
        supabase.table("Users").insert({"user_id": uid, "bank": 0, "daily_lvl": 1, "last_claim": ""}).execute()
        return {"user_id": uid, "bank": 0, "daily_lvl": 1, "last_claim": ""}
    return res.data[0]

class BetModal(discord.ui.Modal):
    def __init__(self, event_id, choice, odds, title):
        super().__init__(title=f"下注確認 - {title}")
        self.event_id, self.choice, self.odds = event_id, choice, odds
        self.amt = discord.ui.TextInput(label=f"銀行存款直扣 (賠率: {odds})", placeholder="100")
        self.add_item(self.amt)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amt = int(self.amt.value)
            if amt <= 0: raise ValueError
        except: return await interaction.response.send_message("❌ 請輸入正整數", ephemeral=True)
        uid = str(interaction.user.id); user = get_user_data(uid); b = user['bank']
        if b < amt: return await interaction.response.send_message(f"❌ 存款不足{ERR_FOOTER}", ephemeral=True)
        supabase.table("Users").update({"bank": b - amt}).eq("user_id", uid).execute()
        supabase.table("Bets").insert({"user_id": uid, "event_id": self.event_id, "choice": self.choice, "amount": amt, "locked_odds": self.odds}).execute()
        await interaction.response.send_message(f"✅ 成功從銀行下注 `${amt}`！", ephemeral=True)

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

bot = SakunaBot()

@bot.tree.command(name="balance", description="查看我的銀行資產 (僅自己可見)")
async def balance(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        user = get_user_data(interaction.user.id); lvl = user['daily_lvl']; rate = 0.2 * (2 ** (lvl-1))
        await interaction.followup.send(f"🏦 銀行存款: `${int(user['bank'])}`\n⭐ VIP 等級: `{lvl}` (日息 {rate}%)", ephemeral=True)
    except Exception as e: await interaction.followup.send(f"❌ 錯誤: {e}{ERR_FOOTER}", ephemeral=True)

@bot.tree.command(name="daily", description="領取每日獎勵金 (07:15 重置)")
async def daily(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        uid = str(interaction.user.id); user = get_user_data(uid); today = datetime.datetime.now(HKT).strftime('%Y-%m-%d')
        if user['last_claim'] == today: return await interaction.followup.send("❌ 今天領過了！", ephemeral=True)
        lvl = user['daily_lvl']; reward = int(10000 * (2 ** (lvl - 1)))
        supabase.table("Users").update({"bank": user['bank'] + reward, "last_claim": today}).eq("user_id", uid).execute()
        await interaction.followup.send(f"🎁 領取了 `${reward}`！", ephemeral=True)
    except Exception as e: await interaction.followup.send(f"❌ 錯誤: {e}{ERR_FOOTER}", ephemeral=True)

@bot.tree.command(name="upgrade", description="提升 VIP 等級")
async def upgrade(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        uid = str(interaction.user.id); user = get_user_data(uid); lvl = user['daily_lvl']; b = user['bank']
        cost = int(20000 * (2 ** lvl))
        if b < cost: return await interaction.followup.send(f"❌ 存款不足！升級 VIP {lvl+1} 需要 `${cost}`。", ephemeral=True)
        supabase.table("Users").update({"bank": b - cost, "daily_lvl": lvl + 1}).eq("user_id", uid).execute()
        await interaction.followup.send(f"🎉 成功升級至 VIP {lvl+1}！", ephemeral=True)
    except Exception as e: await interaction.followup.send(f"❌ 錯誤: {e}{ERR_FOOTER}", ephemeral=True)

@bot.tree.command(name="force_run", description="【管理員】立即抓取最新盤口")
async def force_run(interaction: discord.Interaction):
    if interaction.user.id != ADMIN_ID: return await interaction.response.send_message("❌ 權限不足", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    await bot.process_new_odds()
    await interaction.followup.send("🚀 開盤完成！")

if __name__ == '__main__':
    bot.run(TOKEN)

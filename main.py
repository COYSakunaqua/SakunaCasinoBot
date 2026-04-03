import discord
from discord.ext import commands, tasks
import os
import time
import aiohttp
from supabase import create_client, Client
from dotenv import load_dotenv

# 1. 環境變數加載
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('ODDS_API_KEY')
SB_URL = os.getenv('SUPABASE_URL')
SB_KEY = os.getenv('SUPABASE_KEY')

# ADMIN_ID 防呆處理
admin_str = os.getenv('ADMIN_ID', '0')
ADMIN_ID = int(admin_str) if admin_str.isdigit() else 0

# 2. 初始化 Supabase 雲端客戶端
if not SB_URL or not SB_KEY:
    print("❌ 錯誤：Supabase 憑證缺失，請檢查 Secrets 設定。")
supabase: Client = create_client(SB_URL, SB_KEY)

class SakunaBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)

    async def setup_hook(self):
        # 同步斜線指令
        await self.tree.sync()
        # 啟動背景結算任務
        self.auto_settle_task.start()
        print(f"✅ 雲端 Bot 已就緒 | 自動結算已掛載")

    # --- 核心自動結算 (每 3 小時執行一次以節省 API) ---
    @tasks.loop(minutes=180)
    async def auto_settle_task(self):
        if not API_KEY: return
        print("🔍 [自動結算] 正在從雲端抓取賽果...")
        url = "https://api.the-odds-api.com/v4/sports/soccer_uefa_champs_league/scores/"
        params = {'apiKey': API_KEY, 'daysFrom': 1}
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, params=params) as resp:
                    if resp.status != 200: return
                    matches = await resp.json()
            except Exception as e:
                print(f"❌ API 抓取失敗: {e}")
                return

        for match in matches:
            if not match['completed']: continue
            try:
                h_team, a_team = match['home_team'], match['away_team']
                h_score = next(s['score'] for s in match['scores'] if s['name'] == h_team)
                a_score = next(s['score'] for s in match['scores'] if s['name'] == a_team)
                
                # 判定勝負 (A:主勝, B:和局, C:客勝)
                win_choice = 'A' if h_score > a_score else 'C' if a_score > h_score else 'B'
                title = f"{h_team} vs {a_team}"
                
                # 在 Supabase 查找該場次且狀態為 0 (未結算) 的事件
                res = supabase.table("Events").select("event_id").eq("title", title).eq("status", 0).execute()
                if res.data:
                    for event in res.data:
                        await self.do_payout(event['event_id'], win_choice, title)
            except Exception as e:
                print(f"⚠️ 處理賽事 {match.get('home_team')} 錯誤: {e}")
                continue

    async def do_payout(self, event_id, win_choice, title):
        # 1. 找出所有押中的玩家
        bets = supabase.table("Bets").select("*").eq("event_id", event_id).eq("choice", win_choice).execute()
        for bet in bets.data:
            payout = int(bet['amount'] * bet['locked_odds'])
            # 2. 調用我們在 SQL Editor 寫的 RPC 函數 (increment_wallet)
            supabase.rpc('increment_wallet', {'row_id': bet['user_id'], 'amount': payout}).execute()
        
        # 3. 將事件標記為已結算 (status=2)
        supabase.table("Events").update({"status": 2}).eq("event_id", event_id).execute()
        print(f"💰 成功結算賽事: {title} | 勝方: {win_choice}")

# --- 全域功能函數 ---
def get_user_data(user_id):
    uid = str(user_id)
    res = supabase.table("Users").select("*").eq("user_id", uid).execute()
    if not res.data:
        supabase.table("Users").insert({"user_id": uid, "wallet": 1000}).execute()
        return 1000, 0
    return res.data[0]['wallet'], res.data[0]['bank']

# --- UI 元件 (Modal & View) ---
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
        if w < amt: return await interaction.response.send_message("❌ 你的錢包不夠錢", ephemeral=True)
        
        # 雲端原子操作：扣錢 + 存注單
        supabase.table("Users").update({"wallet": w - amt}).eq("user_id", uid).execute()
        supabase.table("Bets").insert({
            "user_id": uid, "event_id": self.event_id, 
            "choice": self.choice, "amount": amt, "locked_odds": self.odds
        }).execute()
        await interaction.response.send_message(f"✅ 下注成功！ `${amt}` 買了 {self.choice}", ephemeral=True)

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

# --- 指令集 ---
bot = SakunaBot()

@bot.command()
async def auto_open(ctx):
    """【自動開盤】從 API 抓取賠率並發布到頻道"""
    await ctx.send("🔍 正在抓取最新歐聯賠率...")
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
            
            # 存入雲端數據庫
            res = supabase.table("Events").insert({
                "title": title, "odds_a": o_a, "odds_b": o_b, "odds_c": o_c, 
                "creator_id": str(bot.user.id), "created_at": int(time.time())
            }).execute()
            
            event_id = res.data[0]['event_id']
            view = BetView(event_id, o_a, o_b, o_c, title)
            embed = discord.Embed(title="🏟️ 雲端自動開盤", description=f"賽事: **{title}**", color=0x3498db)
            embed.add_field(name="A (主)", value=o_a); embed.add_field(name="B (和)", value=o_b); embed.add_field(name="C (客)", value=o_c)
            await ctx.send(embed=embed, view=view)
        except: continue

@bot.tree.command(name="balance", description="查看我的雲端錢包")
async def balance(interaction: discord.Interaction):
    w, b = get_user_data(interaction.user.id)
    await interaction.response.send_message(f"👛 錢包: `${w}` | 🏦 銀行: `${b}` (數據已加密同步)", ephemeral=True)

if __name__ == '__main__':
    max_retries = 20
    retry_delay = 20
    
    print("⏳ [系統] 正在喚醒雲端容器，強制實時日誌模式已開啟...", flush=True)
    
    for attempt in range(max_retries):
        try:
            # 每次重試都清理一下舊的日誌處理器，防止日誌爆炸
            import logging
            for handler in logging.root.handlers[:]:
                logging.root.removeHandler(handler)
            
            if attempt == 0:
                time.sleep(10)
            
            print(f"🚀 [啟動] 嘗試連接 Discord (第 {attempt+1}/{max_retries} 次)...", flush=True)
            
            # 重新實例化 Bot，確保乾淨的狀態
            bot = SakunaBot()
            bot.run(TOKEN)
            break
            
        except Exception as e:
            err_msg = str(e)
            print(f"❌ [失敗] 原始錯誤: {err_msg}", flush=True)
            
            # 這是關鍵：如果還是連不上，代表 Hugging Face 網路沒通
            if any(word in err_msg.lower() for word in ["hostname", "address", "getaddrinfo", "dns", "443"]):
                print(f"⚠️ [網路] 偵測到環境 DNS 未就緒，{retry_delay} 秒後自動重試...", flush=True)
                time.sleep(retry_delay)
            elif "improper token" in err_msg.lower():
                print("🛑 [終止] Token 錯誤！請檢查 Secrets 裡的 DISCORD_TOKEN。", flush=True)
                break
            else:
                print(f"🔄 [異常] 未知錯誤，{retry_delay} 秒後重試...", flush=True)
                time.sleep(retry_delay)

import discord
import time
import datetime
from utils.helpers import get_user_data, get_display_choice

class BetView(discord.ui.View):
    # 接收 bot 實例，實踐依賴注入
    def __init__(self, bot, event_id=None, o_a=None, o_b=None, o_c=None, title=None, h_name=None, a_name=None):
        super().__init__(timeout=None)
        self.bot = bot
        self.eid = event_id
        self.cooldowns = {} 
        
        # 動態渲染按鈕名稱
        if h_name and a_name:
            self.b_a.label = f"{h_name} Win"
            self.b_b.label = "Draw"
            self.b_c.label = f"{a_name} Win"

    @discord.ui.button(label="A", style=discord.ButtonStyle.green, custom_id="persistent_bet_a")
    async def b_a(self, i, b): await self.handle_bet(i, 'A')

    @discord.ui.button(label="B", style=discord.ButtonStyle.gray, custom_id="persistent_bet_b")
    async def b_b(self, i, b): await self.handle_bet(i, 'B')

    @discord.ui.button(label="C", style=discord.ButtonStyle.red, custom_id="persistent_bet_c")
    async def b_c(self, i, b): await self.handle_bet(i, 'C')

    async def handle_bet(self, interaction, choice):
        now = time.time()
        uid = interaction.user.id
        
        # 全域防連點 (Debouncer)：防禦重複扣款
        if uid in self.cooldowns and (now - self.cooldowns[uid]) < 2.0:
            return await interaction.response.send_message("⚠️ 系統冷卻中：你的手速太快了，請等待 2 秒後再操作！", ephemeral=True)
        self.cooldowns[uid] = now

        embed = interaction.message.embeds[0]
        title = embed.description 
        
        # 解析賠率
        odds_str = "1.0"
        for field in embed.fields:
            if choice == 'A' and "🏠" in field.name: odds_str = field.value.replace("賠率: ", "")
            elif choice == 'B' and "🤝" in field.name: odds_str = field.value.replace("賠率: ", "")
            elif choice == 'C' and "🚩" in field.name: odds_str = field.value.replace("賠率: ", "")
            
        try: odds = float(odds_str)
        except: odds = 1.0

        display_choice = get_display_choice(title, choice)
        try:
            # 透過掛載的 bot.db 呼叫資料庫
            res = self.bot.db.table("Users").select("bank").eq("user_id", str(uid)).execute()
            bank_balance = res.data[0]['bank'] if res.data else 0
        except Exception:
            bank_balance = "?"

        # 將 bot 傳遞給 Modal
        await interaction.response.send_modal(BetModal(self.bot, choice, odds, title, display_choice, bank_balance))

class BetModal(discord.ui.Modal):
    def __init__(self, bot, choice, odds, title, display_choice, bank_balance):
        super().__init__(title=f"押注: {display_choice}"[:45])
        self.bot = bot
        self.choice = choice
        self.odds = odds
        self.event_title = title
        
        label_text = f"銀行餘額: ${bank_balance:,} | 賠率: {odds}" if isinstance(bank_balance, int) else f"本金直扣 (賠率: {odds})"
        self.amt = discord.ui.TextInput(label=label_text[:45], placeholder="100", min_length=1)
        self.add_item(self.amt)

    async def on_submit(self, interaction: discord.Interaction):
        # 【強制規定】第一行攔截並進入 defer 狀態，防止處理超時
        await interaction.response.defer(ephemeral=True)
        try:
            amt = int(self.amt.value)
            if amt <= 0: raise ValueError
        except: return await interaction.followup.send("❌ 請輸入正整數", ephemeral=True)
        
        uid = str(interaction.user.id)
        
        # 檢查賽事狀態
        res = self.bot.db.table("Events").select("*").eq("title", self.event_title).eq("status", 0).execute()
        if not res.data:
            return await interaction.followup.send("❌ 賽事已關閉或已結算", ephemeral=True)
            
        event = res.data[0]
        real_event_id = event['event_id']
        
        # VAR 開賽鎖定防護
        current_timestamp = int(datetime.datetime.now().timestamp())
        if event.get('commence_time') and current_timestamp >= event['commence_time']:
            return await interaction.followup.send("❌ 嗶嗶！比賽已經開始，系統已停止接受此場賽事的下注。", ephemeral=True)
        
        # 防套利檢查 (Anti-Arbitrage)
        existing_bets = self.bot.db.table("Bets").select("choice").eq("user_id", uid).eq("event_id", real_event_id).execute()
        if existing_bets.data:
            first_choice = existing_bets.data[0]['choice']
            if self.choice != first_choice:
                display_first = get_display_choice(self.event_title, first_choice)
                return await interaction.followup.send(f"❌ **拒絕套利！**\n你已經在這場比賽下注了 `{display_first}`。\n💡 *規則：每場賽事只能押注單一結果。*", ephemeral=True)
        
        # 餘額檢查
        user = get_user_data(self.bot, uid)
        if user['bank'] < amt: 
            return await interaction.followup.send(f"❌ 存款不足", ephemeral=True)
        
        # 扣款與統計更新
        new_bank = user['bank'] - amt
        new_profit = user.get('weekly_profit', 0) - amt
        new_bet_count = user.get('weekly_bet_count', 0) + 1
        self.bot.db.table("Users").update({
            "bank": new_bank, 
            "weekly_profit": new_profit,
            "weekly_bet_count": new_bet_count
        }).eq("user_id", uid).execute()
        
        real_odds = event['odds_a'] if self.choice == 'A' else event['odds_b'] if self.choice == 'B' else event['odds_c']
        
        # 寫入注單
        self.bot.db.table("Bets").insert({"user_id": uid, "event_id": real_event_id, "choice": self.choice, "amount": amt, "locked_odds": real_odds}).execute()
        await interaction.followup.send(f"✅ 成功下注 `${amt:,}`！期待你的好消息。", ephemeral=True)

        # 鯨魚警報 (Whale Alert)
        if amt >= 100000:
            # 從 utils 引入 CHANNEL_ID_WHALE_ALERT
            from utils.config import CHANNEL_ID_WHALE_ALERT
            whale_channel = interaction.client.get_channel(CHANNEL_ID_WHALE_ALERT)
            if whale_channel:
                await whale_channel.send(f"🚨 【鯨魚警報】某位 VIP 玩家剛在「{self.event_title}」砸下了 `${amt:,}` 的重注！")
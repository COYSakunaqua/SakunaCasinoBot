import discord
from discord.ext import commands
from discord import app_commands
from utils.config import ADMIN_ID, ERR_FOOTER

class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="admin_stats", description="【管理員專屬】莊家風險與宏觀經濟監控儀表板")
    async def admin_stats(self, interaction: discord.Interaction):
        if interaction.user.id != ADMIN_ID: 
            return await interaction.response.send_message("❌ 權限不足", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        try:
            users_res = self.bot.db.table("Users").select("bank, debt").execute()
            total_m0 = sum(u.get('bank', 0) for u in users_res.data)
            total_debt = sum(u.get('debt', 0) for u in users_res.data if u.get('debt'))
            
            active_events = self.bot.db.table("Events").select("event_id").eq("status", 0).execute()
            total_liability = 0
            total_wagered = 0
            
            if active_events.data:
                event_ids = [e['event_id'] for e in active_events.data]
                if event_ids:
                    bets_res = self.bot.db.table("Bets").select("amount, locked_odds").in_("event_id", event_ids).execute()
                    for bet in bets_res.data:
                        total_wagered += bet['amount']
                        total_liability += int(bet['amount'] * bet['locked_odds'])

            treasury_res = self.bot.db.table("Users").select("bank").eq("user_id", "TREASURY").execute()
            treasury_bank = treasury_res.data[0]['bank'] if treasury_res.data else 0
            
            embed = discord.Embed(title="📊 莊家宏觀經濟監控 (Risk Dashboard)", color=0x9b59b6)
            embed.add_field(name="🏦 貨幣發行總量 (M0)", value=f"`${total_m0:,}`\n*(全服玩家存款總和)*", inline=False)
            embed.add_field(name="💸 玩家未還總欠款", value=f"`${total_debt:,}`\n*(高利貸放款壞帳風險)*", inline=False)
            embed.add_field(name="⚖️ 盤口未結算本金", value=f"`${total_wagered:,}`\n*(目前卡在盤口上的總金額)*", inline=False)
            embed.add_field(name="⚠️ 莊家最大可能賠付", value=f"`${total_liability:,}`\n*(如果玩家全贏，系統需印出的鈔票)*", inline=False)
            embed.add_field(name="🏛️ 莊家國庫餘額 (稅收)", value=f"`${treasury_bank:,}`\n*(從 VIP 玩家贏錢派彩中抽取的 2% 總額)*", inline=False)
            embed.set_footer(text="身為莊家，請時刻留意 M0 通膨與 Liability 風險。")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e: await interaction.followup.send(f"❌ 撈取數據失敗: {e}{ERR_FOOTER}", ephemeral=True)

    @app_commands.command(name="force_run", description="【管理員】立即結算賽事並抓取新盤口")
    async def force_run(self, interaction: discord.Interaction):
        if interaction.user.id != ADMIN_ID: return await interaction.response.send_message("❌ 權限不足", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        
        # 呼叫 tasks 模組裡的開盤與結算引擎
        tasks_cog = self.bot.get_cog("TasksCog")
        if tasks_cog:
            await tasks_cog.process_settlements()
            await tasks_cog.process_new_odds()
            await interaction.followup.send("🚀 強制結算與開盤程序已執行完畢！請提醒玩家重新檢查 `/balance` 或是 `/mybets`。", ephemeral=True)
        else:
            await interaction.followup.send("❌ 錯誤：找不到排程引擎模組。", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Admin(bot))
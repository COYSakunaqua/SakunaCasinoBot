import discord
from discord.ext import commands
from discord import app_commands
import datetime
import asyncio

from utils.config import VIP_ROLES, ERR_FOOTER, HKT
from utils.helpers import get_user_data

# --- 無上限豪華版線性擴展模型 ---
DAILY_REWARDS_BASE = {1: 50000, 2: 100000, 3: 160000, 4: 230000, 5: 300000, 6: 370000}
INTEREST_RATES_BASE = {1: 0.5, 2: 0.9, 3: 1.3, 4: 1.7, 5: 2.0, 6: 2.2}

def get_daily_reward(lvl):
    if lvl <= 6: 
        return DAILY_REWARDS_BASE.get(lvl, 50000)
    # VIP 7 以上：每級固定增加 7萬
    return 370000 + (lvl - 6) * 70000

def get_interest_rate(lvl):
    if lvl <= 6: 
        return INTEREST_RATES_BASE.get(lvl, 0.5)
    # VIP 7 以上：每級固定增加 0.2%
    return round(2.2 + (lvl - 6) * 0.2, 2)

class Economy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="balance", description="查看銀行餘額 (會自動幫您同步 VIP 身份組)")
    async def balance(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            user = get_user_data(self.bot, interaction.user.id)
            lvl = user['daily_lvl']
            rate = get_interest_rate(lvl)
            profit = user.get('weekly_profit', 0)
            debt = user.get('debt', 0)
            streak = user.get('current_streak', 0)
            
            sync_msg = ""
            if isinstance(interaction.user, discord.Member):
                role_to_add_id = VIP_ROLES.get(lvl)
                role_to_add = interaction.guild.get_role(role_to_add_id) if role_to_add_id else None
                all_vip_roles = [interaction.guild.get_role(r_id) for r_id in VIP_ROLES.values() if interaction.guild.get_role(r_id)]
                roles_to_remove = [r for r in all_vip_roles if r in interaction.user.roles and r != role_to_add]
                if roles_to_remove: await interaction.user.remove_roles(*roles_to_remove, reason="VIP 狀態被動同步")
                if role_to_add and role_to_add not in interaction.user.roles:
                    await interaction.user.add_roles(role_to_add, reason=f"查詢餘額時自動同步 VIP {lvl}")
                    sync_msg = f"\n\n🔄 *系統已為您補發 VIP {lvl} 專屬身份組！*"

            debt_str = f"\n🩸 未結清高利貸: `${debt:,}`" if debt > 0 else ""
            
            streak_str = ""
            if streak > 0:
                pct_sum = sum([5, 4, 3, 2] + [1] * max(0, streak - 4))[:streak] if streak > 4 else sum([5, 4, 3, 2][:streak])
                streak_str = f"\n🔥 目前連勝: `{streak}` 場 (下場派彩紅利: `+{pct_sum}%`)"

            await interaction.followup.send(f"🏦 銀行存款: `${int(user['bank']):,}`{debt_str}\n⭐ VIP 等級: `{lvl}` (日息 {rate}%)\n📈 本週下注純利: `${profit:,}`{streak_str}{sync_msg}", ephemeral=True)
        except Exception as e: 
            await interaction.followup.send(f"❌ 錯誤: {e}{ERR_FOOTER}", ephemeral=True)

    @app_commands.command(name="daily", description="領取每日獎勵金 (07:15 重置)")
    async def daily(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            uid = str(interaction.user.id)
            user = get_user_data(self.bot, uid)
            today = datetime.datetime.now(HKT).strftime('%Y-%m-%d')
            
            if user['last_claim'] and user['last_claim'] >= today: 
                unlock_date = (datetime.datetime.strptime(user['last_claim'], '%Y-%m-%d') + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
                return await interaction.followup.send(f"❌ 今天已經領過，或目前處於「期貨預支」冷卻期！(預計解鎖日: {unlock_date})", ephemeral=True)
                
            lvl = user['daily_lvl']
            reward = get_daily_reward(lvl)
            
            self.bot.db.table("Users").update({"bank": user['bank'] + reward, "last_claim": today}).eq("user_id", uid).execute()
            await interaction.followup.send(f"🎁 領取了 `${reward:,}`！", ephemeral=True)

            # 涓滴效應：VIP 5+ 觸發全服 VIP 1~3 印鈔救濟金
            if lvl >= 5:
                res_poor = self.bot.db.table("Users").select("user_id, daily_lvl").in_("daily_lvl", [1, 2, 3]).execute()
                if res_poor.data:
                    for p_user in res_poor.data:
                        p_lvl = p_user['daily_lvl']
                        p_amt = get_daily_reward(p_lvl)
                        self.bot.db.rpc('increment_bank', {'row_id': p_user['user_id'], 'amount': p_amt}).execute()
                        # Event Loop 讓出，防止 10062 超時
                        await asyncio.sleep(0.05)

        except Exception as e: 
            await interaction.followup.send(f"❌ 錯誤: {e}{ERR_FOOTER}", ephemeral=True)

    @app_commands.command(name="upgrade", description="提升 VIP 等級並同步 Discord 身份組")
    async def upgrade(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            uid = str(interaction.user.id)
            user = get_user_data(self.bot, uid)
            lvl = user['daily_lvl']
            b = user['bank']
            
            cost = int(20000 * (2 ** lvl))
            if b < cost: 
                return await interaction.followup.send(f"❌ 存款不足！升級至 VIP {lvl + 1} 需要 `${cost:,}`。", ephemeral=True)
            
            new_lvl = lvl + 1
            self.bot.db.table("Users").update({"bank": b - cost, "daily_lvl": new_lvl}).eq("user_id", uid).execute()
            
            if isinstance(interaction.user, discord.Member):
                role_to_add_id = VIP_ROLES.get(new_lvl)
                role_to_add = interaction.guild.get_role(role_to_add_id) if role_to_add_id else None
                all_vip_roles = [interaction.guild.get_role(r_id) for r_id in VIP_ROLES.values() if interaction.guild.get_role(r_id)]
                roles_to_remove = [r for r in all_vip_roles if r in interaction.user.roles]
                if roles_to_remove: await interaction.user.remove_roles(*roles_to_remove, reason="VIP 升級同步")
                if role_to_add: await interaction.user.add_roles(role_to_add, reason=f"系統自動升級至 VIP {new_lvl}")

            await interaction.followup.send(f"🎉 成功升級至 VIP {new_lvl}！你的專屬身份組已同步更新。", ephemeral=True)
            
        except discord.Forbidden:
            await interaction.followup.send(f"🎉 成功升級至 VIP {new_lvl}！\n⚠️ *但機器人權限不足或階級過低，無法指派身份組。*", ephemeral=True)
        except Exception as e: 
            await interaction.followup.send(f"❌ 錯誤: {e}{ERR_FOOTER}", ephemeral=True)

    @app_commands.command(name="pawn", description="🏛️ 典當行：降級 VIP 瞬間 100% 換回升級本金 (資金周轉)")
    async def pawn(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            uid = str(interaction.user.id)
            user = get_user_data(self.bot, uid)
            lvl = user['daily_lvl']
            
            if lvl <= 1:
                return await interaction.followup.send("❌ 典當失敗！你已經是最低的 VIP 1，無產階級沒有東西可以抵押了。", ephemeral=True)
            
            pawn_value = int(20000 * (2 ** (lvl - 1)))
            new_lvl = lvl - 1
            new_bank = user['bank'] + pawn_value
            
            self.bot.db.table("Users").update({"bank": new_bank, "daily_lvl": new_lvl}).eq("user_id", uid).execute()
            
            if isinstance(interaction.user, discord.Member):
                role_to_add_id = VIP_ROLES.get(new_lvl)
                role_to_add = interaction.guild.get_role(role_to_add_id) if role_to_add_id else None
                all_vip_roles = [interaction.guild.get_role(r_id) for r_id in VIP_ROLES.values() if interaction.guild.get_role(r_id)]
                roles_to_remove = [r for r in all_vip_roles if r in interaction.user.roles]
                if roles_to_remove: await interaction.user.remove_roles(*roles_to_remove, reason="VIP 典當降級")
                if role_to_add: await interaction.user.add_roles(role_to_add, reason=f"典當降級至 VIP {new_lvl}")

            embed = discord.Embed(title="🏛️ 典當成功！資金已入帳", color=0xe67e22)
            embed.add_field(name="📉 VIP 降級", value=f"`VIP {lvl} ➔ VIP {new_lvl}`", inline=False)
            embed.add_field(name="💰 獲得典當金 (100% 原價回收)", value=f"`${pawn_value:,}`", inline=False)
            embed.set_footer(text="提示：你犧牲了高額日息與簽到金，快去盤口把錢贏回來！")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send(f"🏛️ 成功降級並獲得資金！\n⚠️ *但機器人權限不足或階級過低，無法即時拔除你的 Discord 身份組。*", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 系統錯誤: {e}{ERR_FOOTER}", ephemeral=True)

    @app_commands.command(name="cashout", description="⏳ 期貨合約：立即預支未來 3 天的低保獎勵 (75% 貼現)")
    async def cashout(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            uid = str(interaction.user.id)
            user = get_user_data(self.bot, uid)
            today = datetime.datetime.now(HKT).strftime('%Y-%m-%d')
            
            if user['last_claim'] and user['last_claim'] >= today:
                return await interaction.followup.send("❌ 你今天的獎勵已經領過，或目前正處於期貨預支冷卻期，無法簽署新合約。", ephemeral=True)
            
            lvl = user['daily_lvl']
            daily_reward = get_daily_reward(lvl)
            
            advance_cash = int(daily_reward * 3 * 0.75)
            
            lock_date = (datetime.datetime.now(HKT) + datetime.timedelta(days=2)).strftime('%Y-%m-%d')
            unlock_display_date = (datetime.datetime.now(HKT) + datetime.timedelta(days=3)).strftime('%Y-%m-%d')
            
            new_bank = user['bank'] + advance_cash
            self.bot.db.table("Users").update({"bank": new_bank, "last_claim": lock_date}).eq("user_id", uid).execute()
            
            embed = discord.Embed(title="⏳ 期貨預支合約生效", color=0xf1c40f)
            embed.add_field(name="💰 獲得預支金 (75% 貼現)", value=f"`${advance_cash:,}`", inline=False)
            embed.add_field(name="🔒 帳戶凍結", value=f"未來 3 天無法領取 `/daily`", inline=False)
            embed.set_footer(text=f"提示：你的下一次可領取日常獎勵日期為 {unlock_display_date}")
            
            await interaction.followup.send(embed=embed, ephemeral=True)

            # 涓滴效應 (期貨觸發)：VIP 5+ 觸發全服 VIP 1~3 貼現印鈔
            if lvl >= 5:
                res_poor = self.bot.db.table("Users").select("user_id, daily_lvl").in_("daily_lvl", [1, 2, 3]).execute()
                if res_poor.data:
                    for p_user in res_poor.data:
                        p_lvl = p_user['daily_lvl']
                        p_amt = int(get_daily_reward(p_lvl) * 3 * 0.75)
                        self.bot.db.rpc('increment_bank', {'row_id': p_user['user_id'], 'amount': p_amt}).execute()
                        await asyncio.sleep(0.05)

        except Exception as e:
            await interaction.followup.send(f"❌ 系統錯誤: {e}{ERR_FOOTER}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Economy(bot))
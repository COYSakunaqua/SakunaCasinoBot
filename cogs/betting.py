import discord
from discord.ext import commands
from discord import app_commands
import random
import math

from utils.config import ERR_FOOTER
from utils.helpers import get_user_data, get_display_choice

class Betting(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="mystery_box", description="🎲 花費 $5,000 購買盲盒注單 (隨機賽事/選項/暴擊賠率)")
    async def mystery_box(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            uid = str(interaction.user.id)
            user = get_user_data(self.bot, uid)
            amt = 5000

            if user['bank'] < amt:
                return await interaction.followup.send(f"❌ 存款不足！購買盲盒需要 `${amt:,}`。{ERR_FOOTER}", ephemeral=True)

            events_res = self.bot.db.table("Events").select("*").eq("status", 0).execute()
            if not events_res.data:
                return await interaction.followup.send("❌ 目前沒有待開賽的盤口，無法抽取盲盒。", ephemeral=True)

            bets_res = self.bot.db.table("Bets").select("event_id").eq("user_id", uid).execute()
            bet_event_ids = {b['event_id'] for b in bets_res.data} if bets_res.data else set()
            
            available_events = [e for e in events_res.data if e['event_id'] not in bet_event_ids]
            
            if not available_events:
                return await interaction.followup.send("❌ 你已經在所有待開賽事中下過注了！為防止套利，盲盒暫時無法抽取。", ephemeral=True)

            event = random.choice(available_events)
            choice = random.choice(['A', 'B', 'C'])

            base_odds = event['odds_a'] if choice == 'A' else event['odds_b'] if choice == 'B' else event['odds_c']
            r = random.random()
            multiplier = round(1.5 + 3.5 * (1 - math.sqrt(r)), 2)
            final_odds = round(base_odds * multiplier, 2)
            real_event_id = event['event_id']

            new_bank = user['bank'] - amt
            new_profit = user.get('weekly_profit', 0) - amt
            new_bet_count = user.get('weekly_bet_count', 0) + 1
            
            self.bot.db.table("Users").update({
                "bank": new_bank,
                "weekly_profit": new_profit,
                "weekly_bet_count": new_bet_count
            }).eq("user_id", uid).execute()

            self.bot.db.table("Bets").insert({
                "user_id": uid,
                "event_id": real_event_id,
                "choice": choice,
                "amount": amt,
                "locked_odds": final_odds
            }).execute()

            display_choice = get_display_choice(event['title'], choice)

            embed = discord.Embed(title="🎁 盲盒注單開啟成功！", color=0x9b59b6)
            embed.add_field(name="🎯 鎖定賽事", value=f"`{event['title']}`", inline=False)
            embed.add_field(name="🚩 盲猜選項", value=f"`{display_choice}` (原賠率: {base_odds})", inline=True)
            embed.add_field(name="⚡ 暴擊倍率", value=f"`{multiplier}x`", inline=True)
            embed.add_field(name="🔥 最終賠率", value=f"`{final_odds}`", inline=True)
            embed.set_footer(text="祝你好運！此注單已同步至 /mybets")

            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 系統錯誤: {e}{ERR_FOOTER}", ephemeral=True)

    @app_commands.command(name="mybets", description="查看最近的 10 筆賽事注單 (自動聚合加碼本金)")
    async def mybets(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            uid = str(interaction.user.id)
            user = get_user_data(self.bot, uid)
            bets = self.bot.db.table("Bets").select("*").eq("user_id", uid).order("bet_id", desc=True).limit(100).execute()
            
            if not bets.data:
                return await interaction.followup.send("📭 你還沒有任何下注紀錄喔！", ephemeral=True)
                
            aggregated_bets = {}
            event_order = []
            
            for bet in bets.data:
                eid = bet['event_id']
                if eid not in aggregated_bets:
                    aggregated_bets[eid] = {
                        'choice': bet['choice'],
                        'total_amount': 0,
                        'total_payout': 0
                    }
                    event_order.append(eid)
                
                aggregated_bets[eid]['total_amount'] += bet['amount']
                aggregated_bets[eid]['total_payout'] += int(bet['amount'] * bet['locked_odds'])

            embed = discord.Embed(title="📊 你的最近注單 (Top 10 賽事)", color=0x3498db)
            
            count = 0
            for eid in event_order:
                if count >= 10: break
                
                ev = self.bot.db.table("Events").select("*").eq("event_id", eid).execute()
                if ev.data:
                    event = ev.data[0]
                    agg_bet = aggregated_bets[eid]
                    status_icon = "⏳ 待開賽" if event['status'] == 0 else "結算中"
                    
                    total_amt = agg_bet['total_amount']
                    total_pay = agg_bet['total_payout'] 
                    avg_odds = round(total_pay / total_amt, 2)
                    
                    display_choice = get_display_choice(event['title'], agg_bet['choice'])
                    result = f"預期基礎派彩: `${total_pay:,}`"
                    
                    if event['status'] == 2:
                        if agg_bet['choice'] == event.get('winning_choice'):
                            status_icon = "✅ 贏得"
                            net_profit = total_pay - total_amt
                            result = f"基礎派彩: `${total_pay:,}` | (本金淨利: `+{net_profit:,}`)"
                        else:
                            status_icon = "❌ 輸掉"
                            result = f"虧損: `-${total_amt:,}`"
                    
                    desc = f"**選項:** `{display_choice}` | **總本金:** `${total_amt:,}` | **均賠率:** `{avg_odds}`\n{result}"
                    embed.add_field(name=f"{status_icon} | {event['title']}", value=desc, inline=False)
                    count += 1
            
            tax_disclaimer = "\n註: VIP 3 (含)以上玩家，贏錢結算時將自動扣除 2% 納入莊家國庫。" if user.get('daily_lvl', 1) >= 3 else ""
            embed.set_footer(text=f"提示: 若有連勝加成，將在派彩時自動外加。{tax_disclaimer}")
                    
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e: await interaction.followup.send(f"❌ 讀取失敗: {e}{ERR_FOOTER}", ephemeral=True)

    @app_commands.command(name="leaderboard", description="🏆 隨時查看本週純利排行榜 (個人可見)")
    async def leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True) 
        try:
            top = self.bot.db.table("Users").select("user_id, weekly_profit").order("weekly_profit", desc=True).limit(10).execute()
            if not top.data:
                return await interaction.followup.send("📭 目前還沒有人有下注獲利紀錄。", ephemeral=True)
                
            embed = discord.Embed(title="🏆 CasinOYS 賭神週榜 (實時更新)", description="結算時間：每週一 07:05 (HKT) 自動派發至名人堂\n*只計算下注純利，不受簽到與升級影響*", color=0xe67e22)
            medals = ["🥇", "🥈", "🥉", "4.", "5.", "6.", "7.", "8.", "9.", "10."]
            
            desc_text = ""
            for i, user in enumerate(top.data):
                profit = user.get('weekly_profit', 0)
                desc_text += f"**{medals[i]}** <@{user['user_id']}> ─ `${profit:,}`\n\n"
                
            embed.description += f"\n\n{desc_text}"
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e: await interaction.followup.send(f"❌ 讀取失敗: {e}{ERR_FOOTER}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Betting(bot))
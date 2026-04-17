import discord
from discord.ext import commands, tasks
import gc
import datetime
import asyncio
# 【修正點】精準導入 ODDS_API_KEY
from utils.config import SCAN_TIME, FINANCE_TIME, WEEKLY_TIME, HKT, ODDS_API_KEY, LEAGUE_CHANNELS, CHANNEL_ID_LEADERBOARD
from utils.helpers import get_user_data
from ui.views import BetView

class TasksCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.memory_cleaner.start()
        self.daily_routine_task.start()
        self.finance_routine_task.start()
        self.weekly_leaderboard_task.start()

    def cog_unload(self):
        self.memory_cleaner.cancel()
        self.daily_routine_task.cancel()
        self.finance_routine_task.cancel()
        self.weekly_leaderboard_task.cancel()

    @tasks.loop(minutes=30)
    async def memory_cleaner(self):
        gc.collect()

    @tasks.loop(time=SCAN_TIME)
    async def daily_routine_task(self):
        # 【修正點】
        if not ODDS_API_KEY: return
        await self.process_settlements()
        await self.process_new_odds()

    @tasks.loop(time=FINANCE_TIME)
    async def finance_routine_task(self):
        try: self.bot.db.rpc('process_daily_finance', {}).execute()
        except Exception: pass

    @tasks.loop(time=WEEKLY_TIME)
    async def weekly_leaderboard_task(self):
        now = datetime.datetime.now(HKT)
        if now.weekday() == 0:
            try:
                last_monday = now - datetime.timedelta(days=7)
                last_sunday = now - datetime.timedelta(days=1)
                date_range_str = f"{last_monday.day}/{last_monday.month} - {last_sunday.day}/{last_sunday.month}"

                all_users = self.bot.db.table("Users").select("*").gt("weekly_bet_count", 0).order("weekly_profit", desc=True).execute()
                if not all_users.data: return
                
                channel = self.bot.get_channel(CHANNEL_ID_LEADERBOARD) 
                if channel:
                    embed = discord.Embed(title=f"🏆 CasinOYS 賭神週榜結算 ({date_range_str})", description="上週的王者與參與獎金已自動派發至銀行：", color=0xffd700)
                    rewards = [75000, 50000, 25000, 12500]
                    medals = ["🥇", "🥈", "🥉", "🏅"]
                    
                    desc_top = ""
                    for i, user in enumerate(all_users.data):
                        uid = user['user_id']
                        profit = user.get('weekly_profit', 0)
                        
                        if i < len(rewards):
                            reward = rewards[i]
                            self.bot.db.table("Users").update({"bank": user['bank'] + reward}).eq("user_id", uid).execute()
                            desc_top += f"{medals[i]} 第 {i+1} 名: <@{uid}>\n純利: `${profit:,}` | 獲得: `${reward:,}`\n\n"
                        else:
                            self.bot.db.table("Users").update({"bank": user['bank'] + 5000}).eq("user_id", uid).execute()
                    
                    embed.add_field(name="🌟 Top 4 賭神", value=desc_top or "無", inline=False)
                    embed.add_field(name="🎁 參與獎勵", value="其餘本週有下注的玩家，已全數自動獲得 `$5,000` 參與獎金！", inline=False)
                    embed.set_footer(text="積分已全數歸零，新一週的廝殺正式開始！")
                    await channel.send(embed=embed)
                
                self.bot.db.rpc('reset_weekly_profit', {}).execute()
            except Exception: pass

    async def process_settlements(self):
        check = self.bot.db.table("Events").select("event_id").eq("status", 0).execute()
        if not check.data: return
        for league_key in LEAGUE_CHANNELS.keys():
            url = f"https://api.the-odds-api.com/v4/sports/{league_key}/scores/"
            # 【修正點】
            params = {'apiKey': ODDS_API_KEY, 'daysFrom': 3}
            try:
                async with self.bot.session.get(url, params=params) as resp:
                    if resp.status != 200: continue
                    matches = await resp.json()
                    for match in matches:
                        if not match['completed']: continue
                        h_team, a_team = match['home_team'], match['away_team']
                        h_score = next(s['score'] for s in match['scores'] if s['name'] == h_team)
                        a_score = next(s['score'] for s in match['scores'] if s['name'] == a_team)
                        win_choice = 'A' if h_score > a_score else 'C' if a_score > h_score else 'B'
                        title = f"{h_team} vs {a_team}"
                        res = self.bot.db.table("Events").select("event_id").eq("title", title).eq("status", 0).execute()
                        if res.data:
                            for event in res.data: await self.do_payout(event['event_id'], win_choice, title)
                    del matches
                    gc.collect() 
            except Exception: pass

    async def process_new_odds(self):
        now_hkt = datetime.datetime.now(HKT)
        for league_key, info in LEAGUE_CHANNELS.items():
            channel = self.bot.get_channel(info["id"])
            if not channel: continue
            url = f"https://api.the-odds-api.com/v4/sports/{league_key}/odds/"
            # 【修正點】
            params = {'apiKey': ODDS_API_KEY, 'regions': 'uk', 'markets': 'h2h', 'oddsFormat': 'decimal'}
            try:
                async with self.bot.session.get(url, params=params) as resp:
                    if resp.status != 200: continue
                    data = await resp.json()
                
                upcoming_matches = []
                for match in data:
                    match_time_utc = datetime.datetime.strptime(match['commence_time'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
                    match_time_hkt = match_time_utc.astimezone(HKT)
                    if match_time_hkt > now_hkt and match_time_hkt < now_hkt + datetime.timedelta(hours=48):
                        upcoming_matches.append((match, match_time_hkt))
                
                upcoming_matches.sort(key=lambda x: x[1])
                
                for match, match_time_hkt in upcoming_matches[:15]:
                    h_name, a_name = match['home_team'], match['away_team']
                    title = f"{h_name} vs {a_name}"
                    time_display = match_time_hkt.strftime('%m-%d %H:%M')
                    commence_ts = int(match_time_hkt.timestamp()) 

                    duplicate = self.bot.db.table("Events").select("event_id").eq("title", title).eq("status", 0).execute()
                    if duplicate.data: continue
                    outcomes = match['bookmakers'][0]['markets'][0]['outcomes']
                    o_a = next(o['price'] for o in outcomes if o['name'] == h_name)
                    o_c = next(o['price'] for o in outcomes if o['name'] == a_name)
                    o_b = next(o['price'] for o in outcomes if o['name'] == 'Draw')
                    
                    o_a, o_b, o_c = round(o_a * 1.2, 2), round(o_b * 1.2, 2), round(o_c * 1.2, 2)
                    
                    res = self.bot.db.table("Events").insert({
                        "title": title, "odds_a": o_a, "odds_b": o_b, "odds_c": o_c, "status": 0, "commence_time": commence_ts
                    }).execute()
                    
                    view = BetView(self.bot, res.data[0]['event_id'], o_a, o_b, o_c, title, h_name, a_name)
                    embed = discord.Embed(title=f"🏟️ {info['name']} 最新盤口 (+20%)", description=f"{title}", color=0xf1c40f)
                    embed.add_field(name="⏱️ 開賽時間 (HKT)", value=f"`{time_display}`\n*(開賽後自動鎖定)*", inline=False)
                    embed.add_field(name=f"🏠 {h_name}", value=f"賠率: {o_a}")
                    embed.add_field(name="🤝 Draw", value=f"賠率: {o_b}")
                    embed.add_field(name=f"🚩 {a_name}", value=f"賠率: {o_c}")
                    await channel.send(embed=embed, view=view)
                    await asyncio.sleep(1) 
            except Exception: pass
            gc.collect()

    async def do_payout(self, event_id, win_choice, title):
        self.bot.db.table("Events").update({"status": 2, "winning_choice": win_choice}).eq("event_id", event_id).execute()
        all_bets = self.bot.db.table("Bets").select("*").eq("event_id", event_id).execute()
        
        treasury_tax_total = 0
        user_bet_results = {} 

        for bet in all_bets.data:
            await asyncio.sleep(0.05)
            
            uid = bet['user_id']
            if uid not in user_bet_results:
                user_bet_results[uid] = {'win_base_payout': 0, 'is_win': False}
            
            if bet['choice'] == win_choice:
                user_bet_results[uid]['is_win'] = True
                user_bet_results[uid]['win_base_payout'] += int(bet['amount'] * bet['locked_odds'])

        for uid, result in user_bet_results.items():
            await asyncio.sleep(0.05)
            
            user = get_user_data(self.bot, uid)
            streak = user.get('current_streak', 0)

            if result['is_win']:
                pct_sum = 0.0
                for i in range(1, streak + 1):
                    if i == 1: pct_sum += 0.05
                    elif i == 2: pct_sum += 0.04
                    elif i == 3: pct_sum += 0.03
                    elif i == 4: pct_sum += 0.02
                    else: pct_sum += 0.01

                base_payout = result['win_base_payout']
                payout_with_bonus = int(base_payout * (1 + pct_sum))

                tax_amount = 0
                final_payout = payout_with_bonus
                if user.get('daily_lvl', 1) >= 3:
                    tax_amount = int(payout_with_bonus * 0.02)
                    final_payout -= tax_amount
                    treasury_tax_total += tax_amount

                debt = user.get('debt', 0)
                actual_deposit = final_payout
                
                if debt > 0:
                    if final_payout >= debt:
                        actual_deposit = final_payout - debt
                        self.bot.db.table("Users").update({"debt": 0, "current_streak": streak + 1}).eq("user_id", uid).execute()
                    else:
                        actual_deposit = 0
                        self.bot.db.table("Users").update({"debt": debt - final_payout, "current_streak": streak + 1}).eq("user_id", uid).execute()
                else:
                    self.bot.db.table("Users").update({"current_streak": streak + 1}).eq("user_id", uid).execute()
                
                if actual_deposit > 0:
                    self.bot.db.rpc('increment_bank', {'row_id': uid, 'amount': actual_deposit}).execute()
            else:
                self.bot.db.table("Users").update({"current_streak": 0}).eq("user_id", uid).execute()

        if treasury_tax_total > 0:
            t_user = get_user_data(self.bot, "TREASURY")
            self.bot.db.table("Users").update({"bank": t_user['bank'] + treasury_tax_total}).eq("user_id", "TREASURY").execute()

async def setup(bot):
    await bot.add_cog(TasksCog(bot))
import discord
from discord import app_commands
from discord.ext import commands
import random
import datetime
from utils.helpers import async_db_execute

class AppBridge(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="app-bind",
        description="【App 轉型】生成 4 位數驗證碼以綁定 CasinOYS App"
    )
    async def app_bind(self, interaction: discord.Interaction):
        # 1. 強制 Defer，防止資料庫寫入超時導致 10062 錯誤
        await interaction.response.defer(ephemeral=True)
        
        user_id = str(interaction.user.id)
        
        # 2. 生成 4 位數隨機驗證碼
        bind_code = f"{random.randint(0, 9999):04d}"
        
        # 3. 設定 15 分鐘時效
        expiry_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=15)
        expiry_str = expiry_time.isoformat()

        # 4. 寫入資料庫 (Burn on Use 策略，拔除 is_used)
        try:
            query = self.bot.db.table("AppVerification").upsert({
                "user_id": user_id,
                "code": bind_code,
                "expires_at": expiry_str
            })
            
            res = await async_db_execute(query)
            
            if res.data:
                embed = discord.Embed(
                    title="🔐 CasinOYS App 帳號綁定",
                    description="請在 App 登入介面輸入以下驗證碼：",
                    color=discord.Color.blue()
                )
                embed.add_field(name="驗證碼 (Code)", value=f"```\n{bind_code}\n```", inline=False)
                embed.add_field(name="有效時間", value="15 分鐘", inline=True)
                embed.set_footer(text="請勿將此代碼分享給任何人 | CDM 系統守護中")
                
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.followup.send("❌ 寫入失敗，請稍後再試。", ephemeral=True)

        except Exception as e:
            print(f"[AppBridge Error] {e}")
            await interaction.followup.send(f"❌ 系統發生預期外錯誤，無法生成驗證碼。請聯絡架構師。", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(AppBridge(bot))
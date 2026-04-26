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
        
        # 2. 生成 4 位數隨機驗證碼 (方案 A: 1A 選項)
        bind_code = f"{random.randint(0, 9999):04d}"
        
        # 3. 設定 15 分鐘時效 (方案 B: 15mins 選項)
        expiry_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=15)
        expiry_str = expiry_time.isoformat()

        # 4. 寫入資料庫 (使用獨立表 AppVerification)
        # 使用 UPSERT 邏輯：如果用戶已生成過，則覆蓋舊碼並刷新時間
        query = """
        INSERT INTO "AppVerification" (user_id, code, expires_at)
        VALUES ($1, $2, $3)
        ON CONFLICT (user_id) 
        DO UPDATE SET code = $2, expires_at = $3;
        """
        
        success = await async_db_execute(query, user_id, bind_code, expiry_str)

        if success:
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
            await interaction.followup.send(
                "❌ 資料庫連線異常，請稍後再試。若持續失敗請聯絡架構師。", 
                ephemeral=True
            )

async def setup(bot: commands.Bot):
    await bot.add_cog(AppBridge(bot))
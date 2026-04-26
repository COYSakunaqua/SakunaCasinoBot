import discord
from discord.ext import commands
import os
import asyncio
import asyncpg
import aiohttp
from utils.config import TOKEN, DB_DSN

class CasinOYSBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix='!', 
            intents=discord.Intents.all(),
            help_command=None
        )
        self.db = None
        self.session = None

    async def setup_hook(self):
        # 初始化資料庫連線池 (對齊 V4.3.0 雙軌架構)
        print("[System] Initializing Database Connection Pool...")
        try:
            self.db = await asyncpg.create_pool(DB_DSN)
            print("[System] Database Connected Successfully.")
        except Exception as e:
            print(f"[Error] Failed to connect to Database: {e}")

        # 初始化 aiohttp session
        self.session = aiohttp.ClientSession()

        # 動態載入 cogs 資料夾下的所有模組 (包含新加入的 app_bridge.py)
        print("[System] Loading Cogs...")
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py') and not filename.startswith('_'):
                try:
                    await self.load_extension(f'cogs.{filename[:-3]}')
                    print(f"[Loaded] {filename}")
                except Exception as e:
                    print(f"[Error] Failed to load cog {filename}: {e}")

        # 同步 Slash Commands
        print("[System] Syncing Slash Commands...")
        await self.tree.sync()
        print("[System] Sync Complete.")

    async def close(self):
        # 確保關閉時釋放資源，防止 Event Loop 阻塞
        print("[System] Shutting down and releasing resources...")
        if self.session:
            await self.session.close()
        if self.db:
            await self.db.close()
        await super().close()

    async def on_ready(self):
        print(f'========== CasinOYS V4.3.0 ==========')
        print(f'Logged in as: {self.user.name} (ID: {self.user.id})')
        print(f'Status: Dual-Track Readiness Edition')
        print(f'=====================================')
        await self.change_presence(activity=discord.Game(name="CasinOYS App 轉型中..."))

bot = CasinOYSBot()

if __name__ == "__main__":
    bot.run(TOKEN)
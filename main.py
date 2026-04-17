import discord
from discord.ext import commands
import os
import aiohttp
from supabase import create_client, Client
from dotenv import load_dotenv

from utils.config import CHANNEL_ID_GUIDE
from ui.views import BetView  # 引入視圖

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
SB_URL = os.getenv('SUPABASE_URL')
SB_KEY = os.getenv('SUPABASE_KEY')

class SakunaBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True 
        intents.message_content = True 

        super().__init__(
            command_prefix='!', 
            intents=intents, 
            chunk_guilds_at_startup=False, 
            max_messages=10
        )
        self.session: aiohttp.ClientSession = None
        self.db: Client = None

    async def setup_hook(self):
        # 1. 資源綁定 (依賴注入)
        self.db = create_client(SB_URL, SB_KEY)
        self.session = aiohttp.ClientSession()

        # 2. 持久化視圖 (確保重啟後按鈕依舊可以按)
        self.add_view(BetView(bot=self)) 

        # 3. 喚醒所有模組！
        initial_extensions = [
            'cogs.economy',
            'cogs.betting',
            'cogs.tasks',
            'cogs.admin'
        ]
        for ext in initial_extensions:
            await self.load_extension(ext)
            
        await self.tree.sync()
        print(f"✅ CasinOYS V4.1.0 (全模組火力全開) 啟動！", flush=True)

    async def on_member_join(self, member):
        channel = self.get_channel(CHANNEL_ID_GUIDE)
        if channel:
            await channel.send(f"🎊 歡迎 {member.mention}！請閱讀上方指南，並輸入 `/daily` 領取開局 $10,000 資本！")

bot = SakunaBot()

if __name__ == '__main__':
    bot.run(TOKEN)
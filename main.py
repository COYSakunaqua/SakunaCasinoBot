import discord
from discord.ext import commands
import os
import aiohttp
from supabase import create_client, Client
from dotenv import load_dotenv

# 引入剛建好的 config
from utils.config import CHANNEL_ID_GUIDE

# 載入環境變數
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
SB_URL = os.getenv('SUPABASE_URL')
SB_KEY = os.getenv('SUPABASE_KEY')

class SakunaBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True 
        intents.message_content = True 

        # 嚴格遵循 DisCloud 100MB 限制規範：關閉 chunk_guilds 並限制快取
        super().__init__(
            command_prefix='!', 
            intents=intents, 
            chunk_guilds_at_startup=False, 
            max_messages=10
        )
        
        # Option Y: 依賴注入 (Dependency Injection) 的容器準備
        self.session: aiohttp.ClientSession = None
        self.db: Client = None

    async def setup_hook(self):
        # 1. 初始化持久化資源 (整個系統共用這唯一一組)
        self.db = create_client(SB_URL, SB_KEY)
        self.session = aiohttp.ClientSession()

        # 2. 預留：稍後我們會將 BetView 放進 ui/views.py 並在這裡掛載確保按鈕持久化
        # from ui.views import BetView
        # self.add_view(BetView(bot=self)) 

        # 3. 動態載入所有業務邏輯模組 (Cogs)
        # 注意：我們接下來才會建立這些檔案，所以這裡先註解掉，建好一個開一個
        initial_extensions = [
            # 'cogs.economy',
            # 'cogs.betting',
            # 'cogs.tasks',
            # 'cogs.admin'
        ]
        for ext in initial_extensions:
            await self.load_extension(ext)
            
        await self.tree.sync()
        print(f"✅ CasinOYS V4.0.6 (Modular) 啟動 | 依賴注入模式就緒", flush=True)

    async def on_member_join(self, member):
        channel = self.get_channel(CHANNEL_ID_GUIDE)
        if channel:
            await channel.send(f"🎊 歡迎 {member.mention}！請閱讀上方指南，並輸入 `/daily` 領取開局 $10,000 資本！")

# --- 啟動程序 ---
bot = SakunaBot()

if __name__ == '__main__':
    bot.run(TOKEN)
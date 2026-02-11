
import asyncio
from typing import ClassVar

from astrbot.api import logger
from ..config import PluginConfig
from ..model import Platform, Song
from .base import BaseMusicPlayer

class YoutubeMusic(BaseMusicPlayer):
    """
    Youtube 平台实现
    """

    platform: ClassVar[Platform] = Platform(
        name="youtube",
        display_name="Youtube",
        keywords=["yt", "油管", "youtube"],
    )

    def __init__(self, config: PluginConfig):
        super().__init__(config)

    async def fetch_songs(
        self, keyword: str, limit: int, extra: str | None = None
    ) -> list[Song]:
        """
        搜索歌曲
        :param keyword: 搜索关键字
        :param limit: 搜索数量
        """
        try:
            import yt_dlp
        except ImportError:
            logger.error("请先安装 yt-dlp: pip install yt-dlp")
            return []

        search_query = f"ytsearch{limit}:{keyword}"

        # 配置 yt-dlp 选项
        ydl_opts = {
            'quiet': True,
            'ignoreerrors': True,
            'no_warnings': True,
            'extract_flat': True, # 快速提取，不获取流地址
            'socket_timeout': 10,
        }
        
        cookies_path = self.cfg.data_dir / "cookies.txt"
        if cookies_path.exists():
             ydl_opts['cookiefile'] = str(cookies_path)

        try:
            # 在线程中运行搜索，避免阻塞
            loop = asyncio.get_running_loop()
            info = await loop.run_in_executor(
                None, 
                lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(search_query, download=False)
            )

            if not info:
                return []

            songs = []
            entries = info.get('entries', [])
            
            for entry in entries:
                if not entry:
                    continue
                    
                video_id = entry.get('id')
                title = entry.get('title', 'Unknown Title')
                uploader = entry.get('uploader', 'Unknown Artist')
                # 构建 Youtube 链接
                url = entry.get('url') or f"https://www.youtube.com/watch?v={video_id}"
                
                # 尝试获取封面，flat 模式下可能没有 thumbnail
                cover = entry.get('thumbnail') or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

                songs.append(Song(
                    id=video_id,
                    name=title,
                    artists=uploader,
                    audio_url=url, # 下游 Downloader 会识别这个 URL 并调用 yt-dlp 下载
                    cover_url=cover,
                ))

            logger.debug(f"Youtube 搜索到 {len(songs)} 首歌曲")
            return songs

        except Exception as e:
            logger.error(f"Youtube 搜索失败: {e}")
            return []

import asyncio
import shutil
import uuid
from pathlib import Path

import aiofiles
import aiohttp

from astrbot.api import logger

from .config import PluginConfig


class Downloader:
    """下载器"""

    def __init__(self, config: PluginConfig):
        self.cfg = config
        self.songs_dir = self.cfg.songs_dir
        self.session = aiohttp.ClientSession(proxy=self.cfg.http_proxy)


    async def initialize(self):
        if self.cfg.clear_cache:
            self._ensure_cache_dir()

    async def close(self):
        await self.session.close()

    def _ensure_cache_dir(self) -> None:
        """重建缓存目录：存在则清空，不存在则新建"""
        if self.songs_dir.exists():
            shutil.rmtree(self.songs_dir)
        self.songs_dir.mkdir(parents=True, exist_ok=True)
        logger.debug(f"缓存目录已重建：{self.songs_dir}")

    async def download_image(self, url: str, close_ssl: bool = True) -> bytes | None:
        """下载图片"""
        url = url.replace("https://", "http://") if close_ssl else url
        try:
            async with self.session.get(url) as response:
                img_bytes = await response.read()
                return img_bytes
        except Exception as e:
            logger.error(f"图片下载失败: {e}")

    async def download_song(self, url: str) -> Path | None:
        """下载歌曲，返回保存路径"""
        if "youtube.com" in url or "youtu.be" in url:
            return await self.download_youtube(url)

        song_uuid = uuid.uuid4().hex
        file_path = self.songs_dir / f"{song_uuid}.mp3"
        try:
            async with self.session.get(url) as response:
                if response.status != 200:
                    logger.error(f"歌曲下载失败，HTTP 状态码：{response.status}")
                    return None
                # 流式写入
                async with aiofiles.open(file_path, "wb") as f:
                    async for chunk in response.content.iter_chunked(1024):
                        await f.write(chunk)

            logger.debug(f"歌曲下载完成，保存在：{file_path}")
            return file_path

        except Exception as e:
            logger.error(f"歌曲下载失败，错误信息：{e}")
            return None

    async def download_youtube(self, url: str) -> Path | None:
        """从 Youtube 下载音频并转换为 mp3"""
        try:
            import yt_dlp
        except ImportError:
            logger.error("请先安装 yt-dlp: pip install yt-dlp")
            return None

        song_uuid = uuid.uuid4().hex
        # yt-dlp 会自动添加扩展名，所以这里只需要模板
        output_template = self.songs_dir / f"{song_uuid}"
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': str(output_template),
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'quiet': True,
            'no_warnings': True,
            # 显式指定 JS 运行时(node)，解决 n-challenge 失败问题
            'js_runtimes': {'node': {}},
        }
        
        cookies_path = self.cfg.data_dir / "cookies.txt"
        if cookies_path.exists():
             ydl_opts['cookiefile'] = str(cookies_path)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # 在线程池中运行，避免阻塞主循环
                await asyncio.to_thread(ydl.download, [url])
            
            # 最终文件路径
            final_path = self.songs_dir / f"{song_uuid}.mp3"
            if final_path.exists():
                logger.debug(f"Youtube 下载完成，保存在：{final_path}")
                return final_path
            else:
                logger.error("Youtube 下载失败，文件未生成")
                return None
                
        except Exception as e:
            logger.error(f"Youtube 下载失败: {e}")
            return None

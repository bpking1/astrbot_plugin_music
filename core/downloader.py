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
        """从 Youtube 下载音频并转换为 mp3 (独立子进程防污染版)"""
        import asyncio
        import sys
        
        song_uuid = uuid.uuid4().hex
        output_template = self.songs_dir / f"{song_uuid}"
        
        # 构建干净的命令行下载指令
        cmd = [
            sys.executable, "-m", "yt_dlp",
            "--format", "bestaudio/best",
            "--output", str(output_template) + ".%(ext)s",
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "192",
            "--no-warnings"
        ]
        
        # 你的原本逻辑：JS 运行时和 Cookie (可选添加)
        cookies_path = self.cfg.data_dir / "cookies.txt"
        if cookies_path.exists():
            cmd.extend(["--cookies", str(cookies_path)])
            
        cmd.append(url)
        
        try:
            logger.info(f"拉起独立子进程下载: {' '.join(cmd)}")
            
            # 异步执行终端命令，不会阻塞机器人回复！
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            # 等待下载完全结束
            stdout, stderr = await process.communicate()
            
            # 因为 yt-dlp 自行处理了后缀名，我们只需要检查目标路径有没有 .mp3 即可
            final_path = self.songs_dir / f"{song_uuid}.mp3"
            
            if process.returncode == 0 and final_path.exists():
                logger.debug(f"Youtube 独立进程下载完成，保存在：{final_path}")
                return final_path
            else:
                stderr_str = stderr.decode('utf-8', errors='ignore') if stderr else '未知错误'
                logger.error(f"Youtube 下载进程报错，退出码 {process.returncode}:\n{stderr_str}")
                return None
                
        except Exception as e:
            logger.error(f"Youtube 下载拉起进程失败: {e}")
            return None



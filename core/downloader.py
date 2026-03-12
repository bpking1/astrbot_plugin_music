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
        """从 Youtube 下载音频并转换为 mp3 (带 js_runtime 的独立子进程版)"""
        import asyncio
        import sys
        import json
        
        song_uuid = uuid.uuid4().hex
        output_template = self.songs_dir / f"{song_uuid}"
        final_path = self.songs_dir / f"{song_uuid}.mp3"
        
        # 将复杂的配置参数包装成字典
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': str(output_template) + ".%(ext)s",
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'quiet': True,
            'no_warnings': True,
            # 找回你最关键的 js 运行时指令！
            'js_runtimes': {'node': {}},
        }
        
        cookies_path = self.cfg.data_dir / "cookies.txt"
        if cookies_path.exists():
            ydl_opts['cookiefile'] = str(cookies_path)
            
        # 核心：我们将这一段代码作为一个微型的独立 Python 脚本来运行
        # 这样它在一个全新的进程里，既不会被 AstrBot 污染，又继承了这套复杂的配置
        script_code = f"""
import sys
import yt_dlp
import json

ydl_opts = json.loads('''{json.dumps(ydl_opts)}''')
url = '{url}'

try:
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    sys.exit(0)
except Exception as e:
    print(f"ERROR: {{e}}", file=sys.stderr)
    sys.exit(1)
"""

        try:
            logger.info("启动防污染 Python 子进程执行精确配置的 yt-dlp...")
            # 异步执行包裹好的 Python 代码
            process = await asyncio.create_subprocess_exec(
                sys.executable, "-c", script_code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0 and final_path.exists():
                logger.debug(f"Youtube 下载完成，保存在：{final_path}")
                return final_path
            else:
                stderr_str = stderr.decode('utf-8', errors='ignore') if stderr else '未知错误'
                logger.error(f"Youtube 子进程下载失败，退出码 {process.returncode}:\n{stderr_str}")
                return None
                
        except Exception as e:
            logger.error(f"Youtube 下载进程拉起失败: {e}")
            return None


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
    ) -> list:
        import json
        import asyncio
        import sys
        search_query = f"ytsearch{limit}:{keyword}"
        # 核心魔法：拼装独立的进程启动命令
        # 使用 sys.executable 确保依然使用当前的 python 环境
        cmd = [
            sys.executable, "-m", "yt_dlp",
            "-J",               # 👇 极度关键：--dump-single-json 缩写，yt-dlp会将获取的数据作为单纯的 JSON 字典打印到 stdout 控制台
            "--flat-playlist",  # 快速提取，不获取流地址
            "--ignore-errors",
            "--no-warnings",
            "--socket-timeout", "10",
        ]
        cookies_path = self.cfg.data_dir / "cookies.txt"
        if cookies_path.exists():
            cmd.extend(["--cookies", str(cookies_path)])
            
        cmd.append(search_query)
        try:
            logger.info(f"开启无污染独立子进程搜索: {' '.join(cmd)}")
            
            # 使用 asyncio 异步创建纯净的子进程
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=1024 * 1024 * 5 # 赋予子进程 5MB 缓冲区，足量接收 JSON
            )
            
            # 异步非阻塞等待进程执行完成，拿到标准输出
            stdout, stderr = await process.communicate()
            if not stdout:
                logger.error(f"Youtube 子进程搜索抛异常:\n{stderr.decode('utf-8', errors='ignore')}")
                return []
            # 因为开启了 -J，yt-dlp所有的过程日志会走 stderr，而纯净的 JSON 结果全在 stdout 里
            try:
                # 解析获取到的纯净 JSON，它的结构和之前直接调用代码拿到的字典是一模一样的！
                raw_json_str = stdout.decode('utf-8', errors='ignore')
                info = json.loads(raw_json_str)
            except json.JSONDecodeError as e:
                logger.error(f"读取子进程 JSON 失败: {e}\n原文前 200 字: {raw_json_str[:200]}")
                return []

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

"""Codex 平台插件。

主项目当前不再使用自实现运行时，实际执行改为外部原脚本桥接。
"""

from core.registry import register
from platforms.chatgpt.plugin import ChatGPTPlatform


@register
class CodexPlatform(ChatGPTPlatform):
    name = "codex"
    display_name = "Codex"
    version = "1.0.0"

    def register(self, email: str = None, password: str = None):
        raise RuntimeError("Codex 当前已切换为原脚本桥接执行，不应走内嵌 runtime")

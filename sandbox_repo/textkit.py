"""極小的文字工具函式庫（實戰 B 的玩具專案）。"""
from __future__ import annotations

import re


def slugify(text: str) -> str:
    """把文字轉成 URL slug：小寫、非英數字元換成連字號、去頭尾連字號。"""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")

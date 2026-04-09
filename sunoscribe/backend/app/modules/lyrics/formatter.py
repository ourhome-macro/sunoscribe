from __future__ import annotations

import re
from typing import Any


_NON_LYRIC_MARKERS = {
    "[音乐]",
    "[music]",
    "(music)",
    "（音乐）",
    "[instrumental]",
    "(instrumental)",
    "（间奏）",
    "[间奏]",
    "[intro]",
    "[outro]",
}

_BRACKET_TAG_PATTERN = re.compile(r"^[\s\[\(（【<].*[\]\)）】>]\s*$", re.IGNORECASE)


def _clean_text(text: str) -> str:
    normalized = " ".join((text or "").strip().split())
    if not normalized:
        return ""

    lowered = normalized.lower()
    if lowered in _NON_LYRIC_MARKERS:
        return ""

    if _BRACKET_TAG_PATTERN.match(normalized):
        return ""

    return normalized


def format_whisper_segments(raw_result: dict[str, Any]) -> list[dict[str, Any]]:
    """
    将 Whisper 原生结果展平为标准 List[Dict]，仅保留 segment 级别时间戳。

    返回结构：
    [
      {"start": 0.0, "end": 1.23, "text": "..."},
      ...
    ]
    """
    segments = raw_result.get("segments", []) if isinstance(raw_result, dict) else []
    if not isinstance(segments, list):
        return []

    flattened: list[dict[str, Any]] = []

    for seg in segments:
        if not isinstance(seg, dict):
            continue

        text = _clean_text(str(seg.get("text", "")))
        if not text:
            continue

        try:
            start = float(seg.get("start", 0.0))
            end = float(seg.get("end", start))
        except (TypeError, ValueError):
            continue

        if end < start:
            end = start

        flattened.append(
            {
                "start": round(start, 3),
                "end": round(end, 3),
                "text": text,
            }
        )

    return flattened

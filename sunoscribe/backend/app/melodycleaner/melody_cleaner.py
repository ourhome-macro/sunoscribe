from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


# -----------------------------
# 基础工具函数（安全取值）
# -----------------------------

def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = -10_000) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_note_id(note: dict[str, Any], index: int) -> str:
    raw = note.get("id")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return f"note_{index:06d}"


def _normalize_note(note: dict[str, Any], index: int) -> dict[str, Any]:
    """将输入音符规范化为可计算结构，缺字段时兜底，避免崩溃。"""
    n = dict(note or {})

    start = _to_float(n.get("start_time"), 0.0)
    end = _to_float(n.get("end_time"), start)
    if end < start:
        end = start

    # duration 优先使用已有字段，不可信时回退 end - start
    duration = _to_float(n.get("duration_sec"), end - start)
    if duration <= 0:
        duration = max(0.0, end - start)

    n["id"] = _safe_note_id(n, index)
    n["start_time"] = start
    n["end_time"] = end
    n["duration_sec"] = duration
    n["pitch_midi"] = _to_int(n.get("pitch_midi"), -10_000)
    n["confidence"] = _to_float(n.get("confidence"), 0.0)
    n["is_candidate_ornament"] = bool(n.get("is_candidate_ornament", False))
    return n


# -----------------------------
# 清洗步骤函数
# -----------------------------

def filter_by_pitch_range(notes: list[dict[str, Any]], low: int = 52, high: int = 76) -> list[dict[str, Any]]:
    """只保留 pitch_midi 在 [low, high] 的音符。"""
    return [n for n in notes if low <= _to_int(n.get("pitch_midi"), -10_000) <= high]


def filter_short_low_conf(notes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按规则 B 执行基础过滤。"""
    kept: list[dict[str, Any]] = []
    for n in notes:
        duration = _to_float(n.get("duration_sec"), 0.0)
        conf = _to_float(n.get("confidence"), 0.0)
        is_ornament = bool(n.get("is_candidate_ornament", False))

        if is_ornament:
            continue
        if duration < 0.12:
            continue
        if conf < 0.52:
            continue
        if duration < 0.16 and conf < 0.60:
            continue
        kept.append(n)
    return kept


def merge_adjacent_same_pitch(notes: list[dict[str, Any]], max_gap_sec: float = 0.08) -> list[dict[str, Any]]:
    """
    合并相邻同音：
    - pitch_midi 相同
    - next.start_time - current.end_time <= max_gap_sec
    """
    if not notes:
        return []

    sorted_notes = sorted(
        notes,
        key=lambda n: (
            _to_float(n.get("start_time"), 0.0),
            _to_int(n.get("pitch_midi"), -10_000),
        ),
    )

    merged: list[dict[str, Any]] = []
    current = dict(sorted_notes[0])
    current.setdefault("merged_from", [current.get("id")])

    for nxt in sorted_notes[1:]:
        cur_pitch = _to_int(current.get("pitch_midi"), -10_000)
        nxt_pitch = _to_int(nxt.get("pitch_midi"), -10_000)

        cur_end = _to_float(current.get("end_time"), _to_float(current.get("start_time"), 0.0))
        nxt_start = _to_float(nxt.get("start_time"), 0.0)
        gap = nxt_start - cur_end

        if cur_pitch == nxt_pitch and gap <= max_gap_sec:
            # 合并到 current：保留前者主体字段，更新末尾时间与时长、置信度。
            nxt_end = _to_float(nxt.get("end_time"), nxt_start)
            current["end_time"] = max(cur_end, nxt_end)
            current["duration_sec"] = max(0.0, _to_float(current.get("end_time"), cur_end) - _to_float(current.get("start_time"), 0.0))
            current["confidence"] = max(
                _to_float(current.get("confidence"), 0.0),
                _to_float(nxt.get("confidence"), 0.0),
            )

            merged_from = list(current.get("merged_from", []))
            nxt_id = nxt.get("id")
            if nxt_id and nxt_id not in merged_from:
                merged_from.append(nxt_id)
            current["merged_from"] = merged_from
        else:
            merged.append(current)
            current = dict(nxt)
            current.setdefault("merged_from", [current.get("id")])

    merged.append(current)
    return merged


def _choose_best_in_group(
    group: list[dict[str, Any]],
    prev_kept_pitch: int | None,
) -> dict[str, Any]:
    """按 D 规则从冲突组中选 1 个最佳音符。"""

    def ranking(note: dict[str, Any]) -> tuple[float, float, float, float, str]:
        duration = _to_float(note.get("duration_sec"), 0.0)
        conf = _to_float(note.get("confidence"), 0.0)
        pitch = _to_int(note.get("pitch_midi"), -10_000)

        # 第三优先级：越接近前一已保留音越好（用负值让“更小差值”排序更靠前）
        if prev_kept_pitch is None:
            pitch_closeness = 0.0
        else:
            pitch_closeness = -abs(pitch - prev_kept_pitch)

        start = _to_float(note.get("start_time"), 0.0)
        note_id = str(note.get("id", ""))

        # 排序：duration desc, confidence desc, closeness desc，再用 start asc / id asc 保持稳定
        return (duration, conf, pitch_closeness, -start, note_id)

    return max(group, key=ranking)


def resolve_near_simultaneous_conflicts(
    notes: list[dict[str, Any]],
    group_window_sec: float = 0.10,
) -> list[dict[str, Any]]:
    """
    近时间冲突消解：
    - start_time 落在同一 0.10s 窗内视为一组
    - 每组保留 1 个（按 D 规则）
    """
    if not notes:
        return []

    sorted_notes = sorted(
        notes,
        key=lambda n: (
            _to_float(n.get("start_time"), 0.0),
            _to_int(n.get("pitch_midi"), -10_000),
        ),
    )

    result: list[dict[str, Any]] = []
    i = 0

    while i < len(sorted_notes):
        anchor_start = _to_float(sorted_notes[i].get("start_time"), 0.0)
        group = [sorted_notes[i]]
        j = i + 1

        while j < len(sorted_notes):
            s = _to_float(sorted_notes[j].get("start_time"), 0.0)
            if s - anchor_start <= group_window_sec:
                group.append(sorted_notes[j])
                j += 1
            else:
                break

        prev_pitch = None
        if result:
            prev_pitch = _to_int(result[-1].get("pitch_midi"), -10_000)

        winner = _choose_best_in_group(group, prev_pitch)
        result.append(dict(winner))
        i = j

    return result


def remove_big_leaps(
    notes: list[dict[str, Any]],
    leap_semitones: int = 12,
    short_duration_threshold: float = 0.25,
    low_conf_threshold: float = 0.62,
) -> list[dict[str, Any]]:
    """
    删除异常大跳：
    若与前一保留音高差 >= 12 且 (duration < 0.25 或 confidence < 0.62) 则删除当前音。
    """
    if not notes:
        return []

    sorted_notes = sorted(notes, key=lambda n: _to_float(n.get("start_time"), 0.0))

    kept: list[dict[str, Any]] = [dict(sorted_notes[0])]
    for current in sorted_notes[1:]:
        prev = kept[-1]
        prev_pitch = _to_int(prev.get("pitch_midi"), -10_000)
        cur_pitch = _to_int(current.get("pitch_midi"), -10_000)
        leap = abs(cur_pitch - prev_pitch)

        cur_duration = _to_float(current.get("duration_sec"), 0.0)
        cur_conf = _to_float(current.get("confidence"), 0.0)

        if leap >= leap_semitones and (cur_duration < short_duration_threshold or cur_conf < low_conf_threshold):
            continue
        kept.append(dict(current))

    return kept


# -----------------------------
# 主清洗函数
# -----------------------------

def clean_melody_notes(score_ir: dict[str, Any]) -> list[dict[str, Any]]:
    """
    清洗 basic-pitch 音符，输出更接近单旋律主唱的 clean_notes。

    流程：
    A 预处理 -> B 基础过滤 -> C 同音合并 -> D 冲突消解 -> E 大跳删除 -> F 二次同音合并
    """
    raw_notes = score_ir.get("notes", []) if isinstance(score_ir, dict) else []
    if not isinstance(raw_notes, list):
        raw_notes = []

    # A. 预处理：安全规范化 + 按 (start_time, pitch_midi) 排序
    normalized = [_normalize_note(n if isinstance(n, dict) else {}, idx) for idx, n in enumerate(raw_notes, start=1)]
    normalized.sort(key=lambda n: (_to_float(n.get("start_time"), 0.0), _to_int(n.get("pitch_midi"), -10_000)))

    # B. 基础过滤
    step_b = filter_by_pitch_range(normalized, 52, 76)
    step_b = filter_short_low_conf(step_b)

    # C. 合并相邻同音
    step_c = merge_adjacent_same_pitch(step_b, max_gap_sec=0.08)

    # D. 近时间冲突消解
    step_d = resolve_near_simultaneous_conflicts(step_c, group_window_sec=0.10)

    # E. 异常大跳删除
    step_e = remove_big_leaps(
        step_d,
        leap_semitones=12,
        short_duration_threshold=0.25,
        low_conf_threshold=0.62,
    )

    # F. 二次同音合并
    clean_notes = merge_adjacent_same_pitch(step_e, max_gap_sec=0.08)

    # 最后按时间排序输出，保证稳定
    clean_notes.sort(key=lambda n: (_to_float(n.get("start_time"), 0.0), _to_int(n.get("pitch_midi"), -10_000)))
    return clean_notes


# -----------------------------
# 统计函数
# -----------------------------

def summarize_cleaning(original_notes: list[dict[str, Any]], clean_notes: list[dict[str, Any]]) -> dict[str, Any]:
    """输出清洗前后数量统计。"""
    original_count = len(original_notes or [])
    clean_count = len(clean_notes or [])
    removed_count = max(0, original_count - clean_count)

    keep_ratio = (clean_count / original_count) if original_count > 0 else 0.0
    remove_ratio = (removed_count / original_count) if original_count > 0 else 0.0

    return {
        "original_count": original_count,
        "clean_count": clean_count,
        "removed_count": removed_count,
        "keep_ratio": round(keep_ratio, 4),
        "remove_ratio": round(remove_ratio, 4),
    }


# -----------------------------
# main 示例
# -----------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Clean melody notes from score_ir.json")
    parser.add_argument("--input", default="score_ir.json", help="Path to input score_ir.json")
    parser.add_argument("--output", default="clean_notes.json", help="Path to output clean_notes.json")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists() or not input_path.is_file():
        print(f"Input file not found: {input_path}")
        return 1

    with input_path.open("r", encoding="utf-8") as f:
        score_ir = json.load(f)

    original_notes = score_ir.get("notes", []) if isinstance(score_ir, dict) else []
    if not isinstance(original_notes, list):
        original_notes = []

    clean_notes = clean_melody_notes(score_ir)
    summary = summarize_cleaning(original_notes, clean_notes)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(clean_notes, f, ensure_ascii=False, indent=2)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Saved clean notes to: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

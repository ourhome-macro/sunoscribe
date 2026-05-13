from __future__ import annotations

import math
import re
from collections import Counter
from statistics import mean, median, pstdev
from typing import Any

from app.schemas.audio_analysis import (
    AudioAnalysisExpression,
    AudioAnalysisLyrics,
    AudioAnalysisPitch,
    AudioAnalysisRange,
    AudioAnalysisReport,
    AudioAnalysisRhythm,
    AudioAnalysisSummary,
)

from .types import AgentRevisionContext

_PITCH_PATTERN = re.compile(r"^([A-Ga-g])([#b]?)(-?\d+)$")
_PITCH_CLASS_TO_SEMITONE = {
    "C": 0,
    "C#": 1,
    "DB": 1,
    "D": 2,
    "D#": 3,
    "EB": 3,
    "E": 4,
    "F": 5,
    "F#": 6,
    "GB": 6,
    "G": 7,
    "G#": 8,
    "AB": 8,
    "A": 9,
    "A#": 10,
    "BB": 10,
    "B": 11,
}
_PITCH_NAMES = ("C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")

_POSITIVE_WORDS = {
    "爱",
    "喜欢",
    "快乐",
    "开心",
    "希望",
    "光",
    "梦",
    "自由",
    "温暖",
    "笑",
    "拥抱",
    "晴",
    "春",
    "home",
    "love",
    "hope",
    "happy",
    "free",
    "dream",
    "light",
    "smile",
}
_NEGATIVE_WORDS = {
    "痛",
    "哭",
    "泪",
    "孤独",
    "离开",
    "失去",
    "黑夜",
    "遗憾",
    "冷",
    "碎",
    "伤",
    "悲",
    "sad",
    "cry",
    "tear",
    "lonely",
    "lost",
    "dark",
    "cold",
    "hurt",
    "broken",
}


class AudioAnalysisAgent:
    """Deterministic post-revision report over typed Score/F0/Rhythm/Lyrics data."""

    VERSION = "audio_analysis_report_v1"

    def run(self, context: AgentRevisionContext, *, lyrics: dict[str, Any] | None = None) -> AudioAnalysisReport:
        warnings = list(context.warnings or [])
        notes = _extract_score_notes(context.score_ir)
        f0_frames = _extract_f0_frames(context.f0_track)
        rhythm_grid = context.rhythm_grid if isinstance(context.rhythm_grid, dict) else {}
        lyrics_payload = lyrics if isinstance(lyrics, dict) else None

        if not notes:
            warnings.append("audio_analysis_missing_score_notes")
        if not f0_frames:
            warnings.append("audio_analysis_missing_f0_track")

        pitch = self._analyze_pitch(notes=notes, f0_frames=f0_frames, warnings=warnings)
        range_report = self._analyze_range(notes=notes, score_ir=context.score_ir, warnings=warnings)
        expression = self._analyze_expression(notes=notes, f0_frames=f0_frames, warnings=warnings)
        rhythm = self._analyze_rhythm(notes=notes, rhythm_grid=rhythm_grid, score_ir=context.score_ir, warnings=warnings)
        lyrics_report = self._analyze_lyrics(lyrics=lyrics_payload, notes=notes, warnings=warnings)
        summary = self._build_summary(
            pitch=pitch,
            range_report=range_report,
            expression=expression,
            rhythm=rhythm,
            lyrics_report=lyrics_report,
            warnings=warnings,
        )

        return AudioAnalysisReport(
            version=self.VERSION,
            project_id=context.project_id,
            revision_id=context.revision_id,
            status="partial" if warnings else "ok",
            pitch=pitch,
            expression=expression,
            range=range_report,
            rhythm=rhythm,
            lyrics=lyrics_report,
            summary=summary,
            warnings=_dedupe_strings(warnings),
        )

    def _analyze_pitch(
        self,
        *,
        notes: list[dict[str, Any]],
        f0_frames: list[dict[str, float]],
        warnings: list[str],
    ) -> AudioAnalysisPitch:
        midi_values = [_note_midi(note) for note in notes]
        midi_values = [value for value in midi_values if value is not None]
        voiced_midi = [frame["pitch_midi"] for frame in f0_frames if frame.get("voiced") and frame.get("pitch_midi", 0.0) > 0.0]
        source_values = midi_values or voiced_midi

        if not source_values:
            return AudioAnalysisPitch(available=False, evidence="missing_pitch_evidence")

        pitch_classes = Counter(_pitch_class_name(int(round(value)) % 12) for value in source_values)
        most_common = [name for name, _count in pitch_classes.most_common(5)]
        intervals = [midi_values[index + 1] - midi_values[index] for index in range(len(midi_values) - 1)]
        upward = sum(1 for item in intervals if item > 0.5)
        downward = sum(1 for item in intervals if item < -0.5)
        repeated = max(0, len(intervals) - upward - downward)
        direction = "balanced"
        if upward > downward * 1.25 and upward >= 2:
            direction = "ascending_bias"
        elif downward > upward * 1.25 and downward >= 2:
            direction = "descending_bias"

        confidence_values = [_safe_float(note.get("confidence")) for note in notes]
        confidence_values = [value for value in confidence_values if value is not None]
        if confidence_values and mean(confidence_values) < 0.5:
            warnings.append("audio_analysis_low_pitch_confidence")

        return AudioAnalysisPitch(
            available=True,
            note_count=len(notes),
            voiced_frame_count=len(voiced_midi),
            pitch_class_histogram=dict(sorted(pitch_classes.items())),
            most_common_pitch_classes=most_common,
            melodic_direction=direction,
            ascending_interval_count=upward,
            descending_interval_count=downward,
            repeated_interval_count=repeated,
            average_note_confidence=round(mean(confidence_values), 3) if confidence_values else None,
            evidence="score_ir_notes" if midi_values else "f0_track_frames",
        )

    def _analyze_range(
        self,
        *,
        notes: list[dict[str, Any]],
        score_ir: dict[str, Any],
        warnings: list[str],
    ) -> AudioAnalysisRange:
        note_points = [(note, _note_midi(note)) for note in notes]
        note_points = [(note, midi) for note, midi in note_points if midi is not None]
        if not note_points:
            return AudioAnalysisRange(available=False, evidence="missing_score_notes")

        midi_values = [float(midi) for _note, midi in note_points]
        lowest = int(round(min(midi_values)))
        highest = int(round(max(midi_values)))
        tessitura_values = _middle_percentile_values(midi_values, lower=0.1, upper=0.9)
        highest_notes = sorted(
            (
                {
                    "note_id": str(note.get("id") or ""),
                    "pitch": _midi_to_pitch_name(int(round(float(midi)))),
                    "pitch_midi": int(round(float(midi))),
                    "measure_num": note.get("measure_num"),
                    "start_time": _safe_float(note.get("start_time")),
                }
                for note, midi in note_points
                if float(midi) >= highest - 1
            ),
            key=lambda item: (_safe_float(item.get("start_time")) or 0.0, str(item.get("note_id") or "")),
        )[:8]

        section_ranges = self._section_ranges(score_ir=score_ir, note_points=note_points)
        return AudioAnalysisRange(
            available=True,
            lowest_pitch=_midi_to_pitch_name(lowest),
            highest_pitch=_midi_to_pitch_name(highest),
            lowest_pitch_midi=lowest,
            highest_pitch_midi=highest,
            span_semitones=highest - lowest,
            tessitura_low_midi=int(round(min(tessitura_values))) if tessitura_values else None,
            tessitura_high_midi=int(round(max(tessitura_values))) if tessitura_values else None,
            tessitura_low=_midi_to_pitch_name(int(round(min(tessitura_values)))) if tessitura_values else None,
            tessitura_high=_midi_to_pitch_name(int(round(max(tessitura_values)))) if tessitura_values else None,
            highest_note_locations=highest_notes,
            section_ranges=section_ranges,
            evidence="score_ir_notes",
        )

    def _section_ranges(self, *, score_ir: dict[str, Any], note_points: list[tuple[dict[str, Any], float]]) -> list[dict[str, Any]]:
        sections = score_ir.get("form_sections") if isinstance(score_ir.get("form_sections"), list) else []
        result: list[dict[str, Any]] = []
        for index, section in enumerate(sections[:12], start=1):
            if not isinstance(section, dict):
                continue
            start = _safe_float(section.get("start_time"))
            end = _safe_float(section.get("end_time"))
            if start is None or end is None or end <= start:
                continue
            values = [midi for note, midi in note_points if _note_overlaps(note, start, end)]
            if not values:
                continue
            low = int(round(min(values)))
            high = int(round(max(values)))
            result.append(
                {
                    "id": str(section.get("id") or f"section_{index}"),
                    "label": str(section.get("label") or f"Section {index}"),
                    "start_time": start,
                    "end_time": end,
                    "lowest_pitch": _midi_to_pitch_name(low),
                    "highest_pitch": _midi_to_pitch_name(high),
                    "span_semitones": high - low,
                    "note_count": len(values),
                }
            )
        return result

    def _analyze_expression(
        self,
        *,
        notes: list[dict[str, Any]],
        f0_frames: list[dict[str, float]],
        warnings: list[str],
    ) -> AudioAnalysisExpression:
        voiced = [frame for frame in f0_frames if frame.get("voiced") and frame.get("pitch_midi", 0.0) > 0.0]
        if len(voiced) < 8:
            return AudioAnalysisExpression(available=False, evidence="insufficient_f0_frames")

        vibrato_segments: list[dict[str, Any]] = []
        slide_segments: list[dict[str, Any]] = []
        stability_values: list[float] = []
        suspicious_note_ids: list[str] = []

        for note in notes:
            start = _safe_float(note.get("performance_start_time_sec"))
            if start is None:
                start = _safe_float(note.get("start_time"))
            end = _safe_float(note.get("performance_end_time_sec"))
            if end is None:
                end = _safe_float(note.get("end_time"))
            if start is None or end is None or end <= start:
                continue
            frames = [frame for frame in voiced if start <= frame["time_sec"] <= end]
            if len(frames) < 5:
                continue
            values = [frame["pitch_midi"] for frame in frames]
            spread = max(values) - min(values)
            stability = max(0.0, 1.0 - min(spread / 2.0, 1.0))
            stability_values.append(stability)

            duration = end - start
            if duration >= 0.45:
                oscillations = _count_direction_changes(values)
                rate = oscillations / max(duration, 0.001)
                if 4.0 <= rate <= 9.5 and 0.25 <= spread <= 2.5:
                    vibrato_segments.append(
                        {
                            "note_id": str(note.get("id") or ""),
                            "start_time": start,
                            "end_time": end,
                            "rate_hz": round(rate, 2),
                            "extent_semitones": round(spread, 2),
                            "confidence": _bounded((spread / 2.0 + min(rate / 8.0, 1.0)) / 2.0),
                        }
                    )

            if duration >= 0.18 and abs(values[-1] - values[0]) >= 1.5:
                slide_segments.append(
                    {
                        "note_id": str(note.get("id") or ""),
                        "start_time": start,
                        "end_time": end,
                        "delta_semitones": round(values[-1] - values[0], 2),
                        "confidence": _bounded(min(abs(values[-1] - values[0]) / 6.0, 1.0)),
                    }
                )

            target = _note_midi(note)
            if target is not None and abs(median(values) - float(target)) >= 1.5:
                note_id = str(note.get("id") or "").strip()
                if note_id:
                    suspicious_note_ids.append(note_id)

        if not stability_values:
            warnings.append("audio_analysis_expression_no_note_frame_overlap")

        return AudioAnalysisExpression(
            available=bool(stability_values),
            vibrato_segment_count=len(vibrato_segments),
            slide_segment_count=len(slide_segments),
            long_note_stability=round(mean(stability_values), 3) if stability_values else None,
            vibrato_segments=vibrato_segments[:12],
            slide_segments=slide_segments[:12],
            suspicious_pitch_note_ids=_dedupe_strings(suspicious_note_ids)[:24],
            evidence="f0_track_frames_and_score_ir_notes",
        )

    def _analyze_rhythm(
        self,
        *,
        notes: list[dict[str, Any]],
        rhythm_grid: dict[str, Any],
        score_ir: dict[str, Any],
        warnings: list[str],
    ) -> AudioAnalysisRhythm:
        meta = score_ir.get("meta") if isinstance(score_ir.get("meta"), dict) else {}
        bpm = _safe_float(rhythm_grid.get("bpm")) or _safe_float(meta.get("bpm"))
        beat_times = _safe_float_list(rhythm_grid.get("beat_times"))
        stability = _safe_float(rhythm_grid.get("stability_score"))
        if stability is None and len(beat_times) >= 4:
            intervals = [beat_times[index + 1] - beat_times[index] for index in range(len(beat_times) - 1)]
            avg_interval = mean(intervals)
            stability = max(0.0, min(1.0, 1.0 - (pstdev(intervals) / avg_interval if avg_interval > 0 else 1.0)))

        offsets: list[float] = []
        if beat_times:
            for note in notes:
                start = _safe_float(note.get("performance_start_time_sec"))
                if start is None:
                    start = _safe_float(note.get("start_time"))
                if start is None:
                    continue
                offsets.append(min(abs(start - beat_time) for beat_time in beat_times))

        durations = [_safe_float(note.get("duration_beats")) for note in notes]
        durations = [value for value in durations if value is not None]
        syncopated = 0
        weak_start = 0
        for note in notes:
            beat_position = _safe_float(note.get("beat_position"))
            if beat_position is None:
                continue
            fractional = abs(beat_position - round(beat_position))
            if 0.2 <= fractional <= 0.8:
                syncopated += 1
            if beat_position > 1.25:
                weak_start += 1

        available = bool(bpm or beat_times or notes)
        if not available:
            warnings.append("audio_analysis_missing_rhythm_evidence")

        return AudioAnalysisRhythm(
            available=available,
            bpm=round(bpm, 3) if bpm is not None else None,
            bpm_confidence=_safe_float(rhythm_grid.get("bpm_confidence")) or _safe_float(meta.get("bpm_confidence")),
            rhythm_type=str(rhythm_grid.get("rhythm_type") or meta.get("rhythm_type") or "") or None,
            stability_score=round(stability, 3) if stability is not None else None,
            beat_count=len(beat_times),
            average_grid_offset_sec=round(mean(offsets), 4) if offsets else None,
            median_grid_offset_sec=round(median(offsets), 4) if offsets else None,
            syncopation_note_count=syncopated,
            weak_beat_start_count=weak_start,
            average_duration_beats=round(mean(durations), 3) if durations else None,
            evidence="rhythm_grid_and_score_ir_notes",
        )

    def _analyze_lyrics(
        self,
        *,
        lyrics: dict[str, Any] | None,
        notes: list[dict[str, Any]],
        warnings: list[str],
    ) -> AudioAnalysisLyrics:
        if not lyrics:
            warnings.append("missing_lyrics")
            return AudioAnalysisLyrics(available=False, status="missing_lyrics", evidence="lyrics_not_provided")

        text = str(lyrics.get("text") or "").strip()
        timeline = lyrics.get("timeline")
        segments = _normalize_lyrics_segments(text=text, timeline=timeline)
        if not text and not segments:
            warnings.append("missing_lyrics")
            return AudioAnalysisLyrics(available=False, status="missing_lyrics", evidence="empty_lyrics")

        tokens = _extract_keywords(text)
        positive_hits = _keyword_hits(text, _POSITIVE_WORDS)
        negative_hits = _keyword_hits(text, _NEGATIVE_WORDS)
        score = len(positive_hits) - len(negative_hits)
        mood = "neutral"
        if score >= 2:
            mood = "positive"
        elif score <= -2:
            mood = "negative"
        elif positive_hits and negative_hits:
            mood = "mixed"

        emotion_curve: list[dict[str, Any]] = []
        for index, segment in enumerate(segments[:32], start=1):
            segment_text = str(segment.get("text") or "")
            segment_score = len(_keyword_hits(segment_text, _POSITIVE_WORDS)) - len(_keyword_hits(segment_text, _NEGATIVE_WORDS))
            start = _safe_float(segment.get("start"))
            end = _safe_float(segment.get("end"))
            overlapping_midi = [
                midi
                for note in notes
                for midi in [_note_midi(note)]
                if midi is not None and start is not None and end is not None and _note_overlaps(note, start, end)
            ]
            emotion_curve.append(
                {
                    "segment_id": str(segment.get("id") or f"lyrics_segment_{index}"),
                    "start": start,
                    "end": end,
                    "text": segment_text,
                    "sentiment_score": segment_score,
                    "average_pitch_midi": round(mean(overlapping_midi), 2) if overlapping_midi else None,
                    "note_count": len(overlapping_midi),
                }
            )

        return AudioAnalysisLyrics(
            available=True,
            status="ok",
            line_count=len([line for line in text.splitlines() if line.strip()]) or len(segments),
            keyword_candidates=tokens[:12],
            sentiment_label=mood,
            sentiment_score=score,
            positive_keyword_hits=positive_hits[:12],
            negative_keyword_hits=negative_hits[:12],
            emotion_curve=emotion_curve,
            evidence="lyrics_text_and_timeline" if segments else "lyrics_text",
        )

    def _build_summary(
        self,
        *,
        pitch: AudioAnalysisPitch,
        range_report: AudioAnalysisRange,
        expression: AudioAnalysisExpression,
        rhythm: AudioAnalysisRhythm,
        lyrics_report: AudioAnalysisLyrics,
        warnings: list[str],
    ) -> AudioAnalysisSummary:
        highlights: list[str] = []
        if range_report.available and range_report.lowest_pitch and range_report.highest_pitch:
            highlights.append(
                f"主旋律音域约为 {range_report.lowest_pitch} 到 {range_report.highest_pitch}，跨度 {range_report.span_semitones} 个半音。"
            )
        if pitch.available:
            if pitch.melodic_direction == "ascending_bias":
                highlights.append("旋律整体更偏上行推进。")
            elif pitch.melodic_direction == "descending_bias":
                highlights.append("旋律整体更偏下行回落。")
            elif pitch.note_count:
                highlights.append("旋律上下行分布相对均衡。")
        if expression.available:
            if expression.vibrato_segment_count:
                highlights.append(f"检测到 {expression.vibrato_segment_count} 个疑似颤音长音片段。")
            if expression.slide_segment_count:
                highlights.append(f"检测到 {expression.slide_segment_count} 个疑似滑音片段。")
        if rhythm.available and rhythm.bpm:
            rhythm_desc = "较稳定" if rhythm.stability_score is not None and rhythm.stability_score >= 0.75 else "有一定波动"
            highlights.append(f"节奏约 {rhythm.bpm:g} BPM，稳定性{rhythm_desc}。")
        if lyrics_report.available and lyrics_report.sentiment_label:
            label_map = {"positive": "偏积极", "negative": "偏消极", "mixed": "正负交织", "neutral": "较中性"}
            highlights.append(f"歌词情绪规则判断为{label_map.get(lyrics_report.sentiment_label, lyrics_report.sentiment_label)}。")

        if not highlights:
            highlights.append("可用证据不足，暂时只能生成有限的音频分析。")

        confidence = 1.0
        if not pitch.available:
            confidence -= 0.25
        if not range_report.available:
            confidence -= 0.2
        if not expression.available:
            confidence -= 0.2
        if not rhythm.available:
            confidence -= 0.15
        if not lyrics_report.available:
            confidence -= 0.1
        confidence -= min(len(warnings), 5) * 0.03

        return AudioAnalysisSummary(
            headline=highlights[0],
            highlights=highlights[:6],
            confidence=round(_bounded(confidence), 3),
            evidence_count=sum(
                1
                for available in (
                    pitch.available,
                    range_report.available,
                    expression.available,
                    rhythm.available,
                    lyrics_report.available,
                )
                if available
            ),
        )


def _extract_score_notes(score_ir: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(score_ir, dict):
        return []
    notes = score_ir.get("notes")
    if not isinstance(notes, list):
        return []
    return [dict(note) for note in notes if isinstance(note, dict)]


def _extract_f0_frames(f0_track: dict[str, Any] | None) -> list[dict[str, float]]:
    if not isinstance(f0_track, dict):
        return []
    frames = f0_track.get("frames")
    if not isinstance(frames, list):
        return []
    result: list[dict[str, float]] = []
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        time_sec = _safe_float(frame.get("time_sec") if "time_sec" in frame else frame.get("time"))
        frequency = _safe_float(frame.get("frequency_hz") if "frequency_hz" in frame else frame.get("frequency"))
        confidence = _safe_float(frame.get("confidence"))
        voiced = bool(frame.get("voiced"))
        pitch_midi = _safe_float(frame.get("pitch_midi"))
        if pitch_midi is None and frequency is not None and frequency > 0:
            pitch_midi = 69.0 + 12.0 * math.log2(frequency / 440.0)
        if time_sec is None or pitch_midi is None:
            continue
        result.append(
            {
                "time_sec": time_sec,
                "frequency_hz": frequency or 0.0,
                "confidence": confidence if confidence is not None else 0.0,
                "voiced": voiced or bool(frequency and frequency > 0),
                "pitch_midi": pitch_midi,
            }
        )
    return sorted(result, key=lambda item: item["time_sec"])


def _note_midi(note: dict[str, Any]) -> float | None:
    raw = _safe_float(note.get("pitch_midi"))
    if raw is not None:
        return raw
    return _pitch_name_to_midi(str(note.get("pitch") or ""))


def _pitch_name_to_midi(pitch: str) -> float | None:
    match = _PITCH_PATTERN.match(str(pitch or "").strip())
    if not match:
        return None
    name, accidental, octave_raw = match.groups()
    key = f"{name.upper()}{accidental.upper()}"
    semitone = _PITCH_CLASS_TO_SEMITONE.get(key)
    if semitone is None:
        return None
    return float((int(octave_raw) + 1) * 12 + semitone)


def _midi_to_pitch_name(midi: int) -> str:
    return f"{_PITCH_NAMES[midi % 12]}{(midi // 12) - 1}"


def _pitch_class_name(value: int) -> str:
    return _PITCH_NAMES[value % 12]


def _note_overlaps(note: dict[str, Any], start: float, end: float) -> bool:
    note_start = _safe_float(note.get("performance_start_time_sec"))
    if note_start is None:
        note_start = _safe_float(note.get("start_time"))
    note_end = _safe_float(note.get("performance_end_time_sec"))
    if note_end is None:
        note_end = _safe_float(note.get("end_time"))
    if note_start is None or note_end is None:
        return False
    return note_start < end and note_end > start


def _count_direction_changes(values: list[float]) -> int:
    directions: list[int] = []
    for index in range(len(values) - 1):
        delta = values[index + 1] - values[index]
        if abs(delta) < 0.05:
            continue
        directions.append(1 if delta > 0 else -1)
    return sum(1 for index in range(len(directions) - 1) if directions[index] != directions[index + 1])


def _middle_percentile_values(values: list[float], *, lower: float, upper: float) -> list[float]:
    if not values:
        return []
    ordered = sorted(values)
    start = int(math.floor(len(ordered) * lower))
    end = int(math.ceil(len(ordered) * upper))
    return ordered[start:max(start + 1, end)]


def _safe_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _safe_float_list(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    return [item for item in (_safe_float(raw) for raw in value) if item is not None]


def _bounded(value: float) -> float:
    return round(max(0.0, min(1.0, float(value))), 3)


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _normalize_lyrics_segments(*, text: str, timeline: Any) -> list[dict[str, Any]]:
    raw_segments: list[Any]
    if isinstance(timeline, list):
        raw_segments = timeline
    elif isinstance(timeline, dict) and isinstance(timeline.get("segments"), list):
        raw_segments = list(timeline.get("segments") or [])
    else:
        raw_segments = []

    segments: list[dict[str, Any]] = []
    for index, item in enumerate(raw_segments, start=1):
        if not isinstance(item, dict):
            continue
        segment_text = str(item.get("text") or item.get("raw_text") or "").strip()
        if not segment_text:
            continue
        segments.append(
            {
                "id": str(item.get("id") or f"lyrics_segment_{index}"),
                "start": _safe_float(item.get("start") if "start" in item else item.get("start_time")),
                "end": _safe_float(item.get("end") if "end" in item else item.get("end_time")),
                "text": segment_text,
            }
        )
    if segments:
        return segments

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return [{"id": f"lyrics_line_{index}", "start": None, "end": None, "text": line} for index, line in enumerate(lines, start=1)]


def _extract_keywords(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z']+|[\u4e00-\u9fff]{1,4}", text.lower())
    stop_words = {"the", "and", "you", "me", "i", "a", "to", "of", "in", "is", "it", "my", "your", "我", "你", "的", "了", "在"}
    counts = Counter(word for word in words if word not in stop_words)
    return [word for word, _count in counts.most_common(16)]


def _keyword_hits(text: str, lexicon: set[str]) -> list[str]:
    lowered = text.lower()
    return sorted({word for word in lexicon if word.lower() in lowered})

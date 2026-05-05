from __future__ import annotations


class RhythmQuantizationService:
    """Extract RhythmGrid payload from semantic audio outputs."""

    def build_rhythm_grid_payload(self, semantic_audio_dict: dict | None) -> dict | None:
        if not isinstance(semantic_audio_dict, dict):
            return None
        rhythm_grid = semantic_audio_dict.get("rhythm_grid")
        return dict(rhythm_grid) if isinstance(rhythm_grid, dict) else None

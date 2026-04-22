from __future__ import annotations

import numpy as np


def note_to_midi(note_name: str) -> int:
    import pretty_midi

    return int(pretty_midi.note_name_to_number(str(note_name)))


def midi_to_note(midi_note: int | float) -> str:
    import pretty_midi

    return str(pretty_midi.note_number_to_name(int(round(float(midi_note)))))


def hz_to_midi(frequencies: np.ndarray) -> np.ndarray:
    values = np.asarray(frequencies, dtype=float)
    result = np.full(values.shape, np.nan, dtype=float)
    valid = np.isfinite(values) & (values > 0.0)
    if np.any(valid):
        result[valid] = 69.0 + (12.0 * np.log2(values[valid] / 440.0))
    return result

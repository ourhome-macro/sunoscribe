from app.modules.lyrics.formatter import format_whisper_segments


def test_format_whisper_segments_filters_non_lyrics_and_normalizes_text() -> None:
    raw = {
        "segments": [
            {"start": 0.0, "end": 1.2, "text": "  hello   world  "},
            {"start": 1.2, "end": 2.3, "text": "[音乐]"},
            {"start": 2.3, "end": 3.0, "text": "（间奏）"},
            {"start": 3.0, "end": 4.0, "text": "[Chorus]"},
            {"start": 4.0, "end": 4.8, "text": "we sing"},
        ]
    }

    got = format_whisper_segments(raw)

    assert got == [
        {"start": 0.0, "end": 1.2, "text": "hello world"},
        {"start": 4.0, "end": 4.8, "text": "we sing"},
    ]


def test_format_whisper_segments_handles_invalid_payload() -> None:
    assert format_whisper_segments({"segments": "invalid"}) == []
    assert format_whisper_segments({}) == []

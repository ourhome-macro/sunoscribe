from app.modules.lyrics.formatter import format_whisper_segments


def test_lyrics_smoke_output_shape() -> None:
    raw = {
        "segments": [
            {"start": 0, "end": 1, "text": "hello"},
        ]
    }
    got = format_whisper_segments(raw)

    assert isinstance(got, list)
    assert isinstance(got[0], dict)
    assert set(got[0].keys()) == {"start", "end", "text"}

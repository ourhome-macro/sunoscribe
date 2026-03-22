from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.modules.audio.config import AudioConfig
from app.modules.audio.exceptions import InvalidTimeRangeError
from app.modules.audio.processor import AudioProcessor
from app.modules.audio.utils import build_slice_command


class TestAudioProcessor(unittest.TestCase):
    def test_convert_appends_default_suffix_when_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_file = temp_path / "input.mp4"
            input_file.write_bytes(b"dummy")

            output_no_suffix = temp_path / "out" / "processed_audio"
            processor = AudioProcessor(AudioConfig(output_format="wav"))

            with patch("app.modules.audio.utils.ensure_ffmpeg_available", return_value="ffmpeg"):
                with patch("app.modules.audio.processor.run_ffmpeg_command") as mocked_run:
                    output = processor.convert(str(input_file), str(output_no_suffix))

            self.assertTrue(output.endswith(".wav"))
            self.assertTrue(mocked_run.called)

    def test_slice_raises_on_invalid_time_range(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_file = temp_path / "input.wav"
            input_file.write_bytes(b"dummy")

            processor = AudioProcessor()

            with self.assertRaises(InvalidTimeRangeError):
                processor.slice(
                    input_path=str(input_file),
                    output_path=str(temp_path / "seg.wav"),
                    start_sec=5.0,
                    end_sec=5.0,
                )

            with self.assertRaises(InvalidTimeRangeError):
                processor.slice(
                    input_path=str(input_file),
                    output_path=str(temp_path / "seg.wav"),
                    start_sec=8.0,
                    end_sec=3.0,
                )

    def test_build_slice_command_fast_seek_places_ss_before_i(self) -> None:
        cfg = AudioConfig()

        with patch("app.modules.audio.utils.ensure_ffmpeg_available", return_value="ffmpeg"):
            cmd = build_slice_command(
                input_path=Path("C:/Temp/in file.mp4"),
                output_path=Path("C:/Temp/out.wav"),
                start_sec=10.0,
                duration_sec=2.5,
                config=cfg,
                fast_seek=True,
            )

        ss_index = cmd.index("-ss")
        i_index = cmd.index("-i")
        self.assertLess(ss_index, i_index)

    def test_build_slice_command_accurate_seek_places_ss_after_i(self) -> None:
        cfg = AudioConfig()

        with patch("app.modules.audio.utils.ensure_ffmpeg_available", return_value="ffmpeg"):
            cmd = build_slice_command(
                input_path=Path("C:/Temp/in file.mp4"),
                output_path=Path("C:/Temp/out.wav"),
                start_sec=10.0,
                duration_sec=2.5,
                config=cfg,
                fast_seek=False,
            )

        ss_index = cmd.index("-ss")
        i_index = cmd.index("-i")
        self.assertGreater(ss_index, i_index)


if __name__ == "__main__":
    unittest.main()

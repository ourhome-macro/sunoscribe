import importlib
import unittest


def _load_arbitrator_module():
    try:
        return importlib.import_module("app.modules.pitch.melody_source_arbitrator")
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "app.modules.pitch.melody_source_arbitrator is required for deterministic melody source arbitration"
        ) from exc


def _make_note(module, *, pitch, start, end, confidence, source, source_stem):
    source_note = getattr(module, "SourceNote", None)
    payload = {
        "pitch": pitch,
        "start_time": start,
        "end_time": end,
        "confidence": confidence,
        "source": source,
        "source_stem": source_stem,
    }
    if source_note is None:
        return payload
    try:
        return source_note(**payload)
    except TypeError:
        payload["detector"] = payload.pop("source")
        return source_note(**payload)


def _get_value(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _note_source(note):
    return _get_value(note, "source", _get_value(note, "detector"))


def _overlaps(note, start, end):
    return float(_get_value(note, "start_time")) < end and float(_get_value(note, "end_time")) > start


def _active_count(notes, timestamp):
    return sum(
        1
        for note in notes
        if float(_get_value(note, "start_time")) <= timestamp < float(_get_value(note, "end_time"))
    )


class TestMelodySourceArbitrator(unittest.TestCase):
    def setUp(self):
        self.module = _load_arbitrator_module()
        config_cls = getattr(self.module, "MelodySourceArbitrationConfig", None)
        if config_cls is None:
            self.arbitrator = self.module.MelodySourceArbitrator()
            return

        self.arbitrator = self.module.MelodySourceArbitrator(
            config_cls(
                transition_window_sec=0.25,
                max_polyphony=2,
            )
        )

    def _arbitrate(self, *, rmvpe_notes=None, basic_pitch_notes=None, vocal_activity=None, max_polyphony=None):
        kwargs = {
            "rmvpe_notes": rmvpe_notes or [],
            "basic_pitch_notes": basic_pitch_notes or [],
            "vocal_activity": vocal_activity or [],
        }
        if max_polyphony is not None:
            kwargs["max_polyphony"] = max_polyphony
        try:
            return self.arbitrator.arbitrate(**kwargs)
        except TypeError:
            kwargs["basic_notes"] = kwargs.pop("basic_pitch_notes")
            return self.arbitrator.arbitrate(**kwargs)

    def test_vocal_segments_prefer_rmvpe_and_basic_pitch_does_not_steal_lead(self):
        rmvpe_notes = [
            _make_note(self.module, pitch="C4", start=0.00, end=0.80, confidence=0.82, source="rmvpe", source_stem="vocals"),
            _make_note(self.module, pitch="D4", start=0.82, end=1.60, confidence=0.80, source="rmvpe", source_stem="vocals"),
        ]
        basic_pitch_notes = [
            _make_note(self.module, pitch="G5", start=0.00, end=0.75, confidence=0.98, source="basic-pitch", source_stem="mix"),
            _make_note(self.module, pitch="A5", start=0.82, end=1.60, confidence=0.99, source="basic-pitch", source_stem="mix"),
        ]

        result = self._arbitrate(
            rmvpe_notes=rmvpe_notes,
            basic_pitch_notes=basic_pitch_notes,
            vocal_activity=[{"start_time": 0.0, "end_time": 1.7, "state": "vocal"}],
        )

        lead_notes = list(_get_value(result, "lead_notes", []))
        self.assertEqual([_note_source(note) for note in lead_notes], ["rmvpe", "rmvpe"])
        self.assertEqual([_get_value(note, "pitch") for note in lead_notes], ["C4", "D4"])

    def test_instrumental_segments_do_not_force_a_lead_from_basic_pitch(self):
        basic_pitch_notes = [
            _make_note(self.module, pitch="C5", start=2.00, end=2.70, confidence=0.96, source="basic-pitch", source_stem="other"),
            _make_note(self.module, pitch="E5", start=2.75, end=3.40, confidence=0.95, source="basic-pitch", source_stem="other"),
        ]

        result = self._arbitrate(
            rmvpe_notes=[],
            basic_pitch_notes=basic_pitch_notes,
            vocal_activity=[{"start_time": 2.0, "end_time": 3.5, "state": "inactive"}],
        )

        lead_notes = list(_get_value(result, "lead_notes", []))
        self.assertFalse([note for note in lead_notes if _overlaps(note, 2.0, 3.5)])
        self.assertGreaterEqual(len(_get_value(result, "support_notes", [])), 1)

    def test_transition_window_conflicts_keep_only_one_lead_source(self):
        rmvpe_notes = [
            _make_note(self.module, pitch="E4", start=1.86, end=2.20, confidence=0.78, source="rmvpe", source_stem="vocals"),
        ]
        basic_pitch_notes = [
            _make_note(self.module, pitch="F4", start=1.95, end=2.30, confidence=0.96, source="basic-pitch", source_stem="mix"),
        ]

        result = self._arbitrate(
            rmvpe_notes=rmvpe_notes,
            basic_pitch_notes=basic_pitch_notes,
            vocal_activity=[
                {"start_time": 0.0, "end_time": 2.0, "state": "vocal"},
                {"start_time": 2.0, "end_time": 3.0, "state": "inactive"},
            ],
        )

        transition_leads = [note for note in _get_value(result, "lead_notes", []) if _overlaps(note, 1.75, 2.25)]
        self.assertLessEqual(len({_note_source(note) for note in transition_leads}), 1)
        self.assertLessEqual(len(transition_leads), 1)

    def test_max_polyphony_limiter_caps_support_notes(self):
        rmvpe_notes = [
            _make_note(self.module, pitch="C4", start=0.0, end=1.0, confidence=0.85, source="rmvpe", source_stem="vocals"),
        ]
        basic_pitch_notes = [
            _make_note(self.module, pitch="E4", start=0.0, end=1.0, confidence=0.90, source="basic-pitch", source_stem="other"),
            _make_note(self.module, pitch="G4", start=0.0, end=1.0, confidence=0.88, source="basic-pitch", source_stem="other"),
            _make_note(self.module, pitch="B4", start=0.0, end=1.0, confidence=0.87, source="basic-pitch", source_stem="other"),
        ]

        result = self._arbitrate(
            rmvpe_notes=rmvpe_notes,
            basic_pitch_notes=basic_pitch_notes,
            vocal_activity=[{"start_time": 0.0, "end_time": 1.0, "state": "vocal"}],
            max_polyphony=2,
        )

        arranged_notes = list(_get_value(result, "lead_notes", [])) + list(_get_value(result, "support_notes", []))
        self.assertLessEqual(_active_count(arranged_notes, 0.5), 2)
        self.assertEqual(len(_get_value(result, "support_notes", [])), 1)


if __name__ == "__main__":
    unittest.main()

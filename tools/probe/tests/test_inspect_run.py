"""Looking back at a finished measurement from its event log."""

import json
from pathlib import Path

from pureprotect_probe import inspect_run


def write(path: Path, events: list[dict]) -> Path:
    path.write_text("".join(json.dumps(event) + "\n" for event in events) + '{"t": 9, "ev": "cut off', encoding="utf-8")
    return path


def frame(t: float, *, reported: dict | None = None, changed: dict | None = None) -> dict:
    return {"t": t, "ev": "frame", "decode": "ok", "reported": reported, "changed": changed, "identical": reported is None and not changed}


def test_describe_tells_power_state_changes_and_what_followed_a_registration(tmp_path: Path) -> None:
    events = [
        {"t": 0.0, "ev": "tx", "what": "register"},
        frame(0.5, reported={"D03102": 1, "D03134": 0, "D0310C": 0, "D03221": 3}),
        frame(10.0, changed={"D03221": 4}),
        {"t": 60.0, "ev": "tx", "what": "refresh-same"},
        frame(70.0, changed={"D03221": 5}),
        {"t": 120.0, "ev": "tx", "what": "refresh-same"},
        frame(121.0),  # repeats the known status: an answer
        {"t": 180.0, "ev": "tx", "what": "refresh-same"},
        frame(200.0, changed={"D03102": 0}),
        {"t": 30.0, "ev": "sync", "ok": True, "latency": 0.1},
        {"t": 31.0, "ev": "sync", "ok": False, "latency": None},
        {"t": 32.0, "ev": "sync", "ok": False, "latency": None},
        {"t": 33.0, "ev": "sync", "ok": True, "latency": 0.3},
        {"t": 3600.0, "ev": "result"},
    ]
    text = "\n".join(inspect_run.describe(inspect_run.load(write(tmp_path / "events.jsonl", events))))
    assert "Duur 1.0 uur, 5 statusberichten" in text
    assert "Bij het eerste bericht: aan/uit (D03102) = 1, sensoren in stand-by (D03134) = 0" in text
    assert "Aan/uit veranderde tijdens de meting: 3 min: 0." in text
    assert "D03221 (fijnstof PM2.5): 2 keer" in text
    assert "Vernieuwen met hetzelfde kenmerk: 3 keer verstuurd; 1 keer kwam er een bericht, 1 keer een bericht dat de bekende status herhaalde." in text
    assert "Ter vergelijking, 2 momenten zonder aanvraag: 0 keer een bericht" in text
    assert "Sync: 2 van 4 beantwoord" in text and "langste reeks missers op rij: 2" in text


def test_main_reads_a_directory_and_reports_a_missing_log(tmp_path: Path, capsys) -> None:
    assert inspect_run.main([str(tmp_path)]) == 2
    write(tmp_path / "events.jsonl", [{"t": 0.0, "ev": "start"}, {"t": 5.0, "ev": "result"}])
    assert inspect_run.main([str(tmp_path)]) == 0
    assert "geen leesbaar statusbericht" in capsys.readouterr().out

"""Look back at a finished measurement: what does its event log say?

    python -m pureprotect_probe.inspect_run metingen/20261122-214359-liveness

Reads ``events.jsonl`` only; nothing is sent to the device. It answers
questions a summary did not ask at the time: was the purifier on, which
values changed how often, and what followed each registration.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

WINDOW = 3.0  # seconds after a registration in which an answer would arrive
KEY_NAMES = {
    "D03102": "aan/uit",
    "D03103": "kinderslot",
    "D03105": "helderheid",
    "D0310C": "stand",
    "D0310D": "toerental",
    "D03110": "timer",
    "D03211": "timer, minuten over",
    "D03120": "allergenenindex",
    "D03221": "fijnstof PM2.5",
    "D03224": "temperatuur",
    "D03125": "luchtvochtigheid",
    "D03134": "sensoren in stand-by",
    "D03135": "lampfunctie",
    "D0520D": "uren tot reinigen",
    "D0540E": "uren filter over",
}


def load(path: Path) -> list[dict[str, Any]]:
    """Read the events; a line that was cut off by a crash is skipped."""
    events: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and "t" in event and "ev" in event:
                events.append(event)
    return events


def percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(share * len(ordered)))]


def followed(frames: list[dict[str, Any]], moments: list[float]) -> dict[str, Any]:
    """Count the moments that were followed by a frame, and by a frame that repeated the known status."""
    any_frame = repeat = 0
    latencies: list[float] = []
    index = 0
    for moment in moments:
        while index < len(frames) and frames[index]["t"] < moment:
            index += 1
        window = []
        probe = index
        while probe < len(frames) and frames[probe]["t"] <= moment + WINDOW:
            window.append(frames[probe])
            probe += 1
        if window:
            any_frame += 1
            latencies.append(window[0]["t"] - moment)
        if any(frame.get("identical") for frame in window):
            repeat += 1
    return {"moments": len(moments), "any": any_frame, "repeat": repeat, "median": statistics.median(latencies) if latencies else None}


def describe(events: list[dict[str, Any]]) -> list[str]:
    """Return the findings as Dutch lines."""
    lines: list[str] = []
    frames = [e for e in events if e["ev"] == "frame" and str(e.get("decode", "")).startswith("ok")]
    all_frames = [e for e in events if e["ev"] == "frame"]
    duration = events[-1]["t"] - events[0]["t"] if events else 0.0
    lines.append(f"Duur {duration / 3600:.1f} uur, {len(all_frames)} statusberichten, waarvan {len(all_frames) - len(frames)} niet te lezen.")
    unreadable = Counter(str(e.get("decode")) for e in all_frames if not str(e.get("decode", "")).startswith("ok"))
    if unreadable:
        lines.append("Waarom niet te lezen: " + ", ".join(f"{reason} {count} keer" for reason, count in unreadable.most_common()) + ".")
    if not frames:
        lines.append("Er is geen leesbaar statusbericht; het apparaat stond vermoedelijk in stand-by of was onbereikbaar.")
    else:
        state: dict[str, Any] = {}
        changes: Counter[str] = Counter()
        power_log: list[str] = []
        on_seconds, last_t, last_power = 0.0, frames[0]["t"], None
        for frame in frames:
            if isinstance(frame.get("reported"), dict):
                state.update(frame["reported"])
                first_power = state.get("D03102")
                last_power = first_power
                lines.append(
                    f"Bij het eerste bericht: aan/uit (D03102) = {first_power}, sensoren in stand-by (D03134) = {state.get('D03134')}, "
                    f"stand (D0310C) = {state.get('D0310C')}."
                )
            for key, value in (frame.get("changed") or {}).items():
                changes[key] += 1
                state[key] = value
                if key == "D03102":
                    power_log.append(f"{frame['t'] / 60:.0f} min: {value}")
            if last_power == 1:
                on_seconds += frame["t"] - last_t
            last_t, last_power = frame["t"], state.get("D03102")
        if power_log:
            lines.append("Aan/uit veranderde tijdens de meting: " + ", ".join(power_log[:12]) + ("…" if len(power_log) > 12 else "") + ".")
        else:
            lines.append("Aan/uit veranderde tijdens de meting niet.")
        gaps = [b["t"] - a["t"] for a, b in zip(frames, frames[1:], strict=False)]
        if gaps:
            lines.append(
                f"Tijd tussen statusberichten: mediaan {statistics.median(gaps):.1f} s, 95% binnen {percentile(gaps, 0.95):.1f} s, langste {max(gaps):.0f} s."
            )
        if changes:
            lines.append("Welke waarden veranderden, en hoe vaak:")
            for key, count in changes.most_common(12):
                name = f" ({KEY_NAMES[key]})" if key in KEY_NAMES else ""
                lines.append(f"  {key}{name}: {count} keer, gemiddeld eens per {duration / count:.0f} s")
        repeats = sum(1 for frame in frames if frame.get("identical"))
        lines.append(f"Berichten die alleen de bekende status herhaalden: {repeats}.")

        sent: dict[str, list[float]] = {}
        for event in events:
            if event["ev"] == "tx" and str(event.get("what", "")).startswith(("register", "refresh")):
                sent.setdefault(event["what"], []).append(event["t"])
        titles = {"register": "Eerste aanvraag", "refresh-same": "Vernieuwen met hetzelfde kenmerk", "refresh-new": "Aanvraag met een nieuw kenmerk"}
        if sent:
            lines.append(f"Wat er binnen {WINDOW:g} s op een abonnementsaanvraag volgde:")
            for what, moments in sent.items():
                seen = followed(frames, moments)
                lines.append(
                    f"  {titles.get(what, what)}: {seen['moments']} keer verstuurd; {seen['any']} keer kwam er een bericht, "
                    f"{seen['repeat']} keer een bericht dat de bekende status herhaalde."
                )
            refreshes = sent.get("refresh-same", [])
            if len(refreshes) > 1:
                # The same number of moments at which nothing was sent, for comparison.
                between = [(a + b) / 2 for a, b in zip(refreshes, refreshes[1:], strict=False)]
                seen = followed(frames, between)
                lines.append(
                    f"  Ter vergelijking, {seen['moments']} momenten zonder aanvraag: {seen['any']} keer een bericht, {seen['repeat']} keer een herhaling."
                )
    for name, title in (("sync", "Sync"), ("info", "Info-aanvraag"), ("ping", "CoAP-ping")):
        probes = [e for e in events if e["ev"] == name]
        if not probes:
            continue
        ok = [e for e in probes if e.get("ok")]
        streak = longest = 0
        for probe in probes:
            streak = 0 if probe.get("ok") else streak + 1
            longest = max(longest, streak)
        latencies = [e["latency"] * 1000 for e in ok if isinstance(e.get("latency"), (int, float))]
        line = f"{title}: {len(ok)} van {len(probes)} beantwoord"
        if latencies:
            line += f", mediaan {statistics.median(latencies):.0f} ms, 95% binnen {percentile(latencies, 0.95):.0f} ms, traagste {max(latencies):.0f} ms"
        if longest:
            line += f"; langste reeks missers op rij: {longest}"
        lines.append(line + ".")
    return lines


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description="Terugkijken op een afgeronde meting, zonder iets naar het apparaat te sturen.")
    parser.add_argument("map", type=Path, help="map van de meting, bijvoorbeeld metingen/20261122-214359-liveness")
    args = parser.parse_args(argv)
    path = args.map / "events.jsonl" if args.map.is_dir() else args.map
    if not path.is_file():
        print(f"Geen events.jsonl gevonden in {args.map}.")
        return 2
    print("=== TERUGBLIK ===")
    print("\n".join(describe(load(path))))
    return 0


if __name__ == "__main__":
    sys.exit(main())

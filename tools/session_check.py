"""Probeer de verbindingslaag van de integratie tegen een echte luchtreiniger, zonder Home Assistant.

    python tools/session_check.py 192.0.2.113
    python tools/session_check.py 192.0.2.113 --duur 300 --set D03103=1 --set D03103=0

Het programma toont elke verandering van toestand en van status, voert de
gevraagde schrijfopdrachten uit en sluit af met de tellers van de sessie.
Zet eerst elke andere integratie voor dit apparaat uit: twee clients vanaf
hetzelfde adres nemen elkaars statusberichten af.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import sys
import time
from pathlib import Path
from typing import Any

_PACKAGE = Path(__file__).resolve().parents[1] / "custom_components" / "philips_pureprotect" / "airlink"
_spec = importlib.util.spec_from_file_location("airlink", _PACKAGE / "__init__.py", submodule_search_locations=[str(_PACKAGE)])
assert _spec is not None and _spec.loader is not None
airlink = importlib.util.module_from_spec(_spec)
sys.modules["airlink"] = airlink
_spec.loader.exec_module(airlink)

NOISE = {"Runtime", "rssi", "free_memory", "StatusType"}
SENSORS = {"D03221", "D03120", "D03224", "D03125"}
HIDDEN = {"DeviceId", "ProductId", "D01S03", "D01S0D"}


def assignment(text: str) -> tuple[str, int]:
    key, _, value = text.partition("=")
    try:
        return key, int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("gebruik SLEUTEL=getal, bijvoorbeeld D03103=1") from None


async def main(args: argparse.Namespace) -> int:
    start = time.monotonic()

    def say(text: str) -> None:
        print(f"{time.monotonic() - start:7.1f} s  {text}", flush=True)

    session = airlink.Session(args.host, port=args.poort)
    seen: dict[str, Any] = {}
    last_state = [session.state]
    presumed = [False]

    def changed() -> None:
        if session.state is not last_state[0]:
            say(f"toestand: {last_state[0].value} -> {session.state.value}")
            last_state[0] = session.state
        if session.presumed_standby != presumed[0]:
            presumed[0] = session.presumed_standby
            say(
                "geen status na een nieuw abonnement: het apparaat staat vermoedelijk uit (stand-by)"
                if presumed[0]
                else "status ontvangen: het vermoeden van stand-by vervalt"
            )
        status = session.status or {}
        if not seen and status:
            say(f"eerste status: {status.get('D01S05')}, firmware {status.get('D01S12')}, {len(status)} sleutels, aan={status.get('D03102')}")
            seen.update(status)
            return
        for key, value in status.items():
            if seen.get(key) == value or key in NOISE:
                continue
            old, seen[key] = seen.get(key, "(nieuw)"), value
            if key in HIDDEN or (key in SENSORS and not args.alles):
                continue
            say(f"{key}: {old} -> {value}")
        if session.identity_mismatch:
            say("LET OP: op dit adres antwoordt een ander apparaat")

    session.add_listener(changed)
    say(f"start, toestand {session.state.value}")
    await session.start()
    try:
        # A device that is on sends its status within about two seconds.
        for _ in range(50):
            if session.status_is_live:
                break
            await asyncio.sleep(0.1)
        if not session.status_is_live:
            say("nog geen status ontvangen; in stand-by is dat normaal")
        for key, value in args.set:
            say(f"schrijven: {key}={value}")
            began = time.monotonic()
            try:
                result = await session.write({key: value})
            except airlink.WriteError as err:
                say(f"  MISLUKT na {time.monotonic() - began:.1f} s: {type(err).__name__}: {err}")
                continue
            notes = [
                text
                for flag, text in (
                    (result.already_current, "de waarde gold al"),
                    (result.resent, "pas na opnieuw sturen"),
                    (result.assumed_off, "uit aangenomen zonder statusbericht"),
                    (result.superseded, "ingehaald door een nieuwere opdracht"),
                )
                if flag
            ]
            say(f"  bevestigd na {result.duration:.2f} s, {result.attempts} poging(en)" + (f" ({', '.join(notes)})" if notes else ""))
            await asyncio.sleep(2)
        remaining = args.duur - (time.monotonic() - start)
        if remaining > 0:
            say(f"meekijken, nog {remaining:.0f} s (stop eerder met Ctrl-C)")
            await asyncio.sleep(remaining)
    except asyncio.CancelledError:
        pass
    finally:
        counters = session.diagnostics().as_dict()
        await session.stop()
    print("\n=== TELLERS ===")
    for key in (
        "state", "status_is_live", "presumed_standby", "frames_received", "frames_dropped", "probes_sent", "probes_missed", "registrations_sent",
        "refreshes_sent", "working_refresh_mode", "escalations", "commands_sent", "commands_refused", "commands_unanswered",
        "commands_unconfirmed", "socket_recreations", "identity_mismatch", "seconds_since_last_frame",
    ):  # fmt: skip
        print(f"{key}: {counters[key]}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="De verbindingslaag van de integratie proberen tegen een echte luchtreiniger.")
    parser.add_argument("host", help="IP-adres van de luchtreiniger")
    parser.add_argument("--poort", type=int, default=5683)
    parser.add_argument("--duur", type=float, default=180.0, help="seconden in totaal (standaard 180)")
    parser.add_argument("--set", action="append", default=[], type=assignment, metavar="SLEUTEL=getal", help="schrijfopdracht; mag vaker")
    parser.add_argument("--alles", action="store_true", help="ook de meetwaarden tonen")
    try:
        raise SystemExit(asyncio.run(main(parser.parse_args())))
    except KeyboardInterrupt:
        raise SystemExit(130) from None

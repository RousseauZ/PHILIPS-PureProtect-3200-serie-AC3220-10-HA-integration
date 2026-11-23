"""Command line of the measurement tool: ``python -m pureprotect_probe``."""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import sys
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path

from . import __version__, scenarios
from .device import Purifier
from .endpoint import Endpoint
from .eventlog import EventLog

DESCRIPTION = """\
Meetprogramma voor het lokale protocol van Philips PureProtect-luchtreinigers.

Schakel eerst de bestaande Home Assistant-integratie voor dit apparaat uit en
sluit de Air+ app af op alle telefoons. Begin met de opdracht 'quick'.
"""


async def ask(prompt: str) -> str:
    """Read a line from the terminal without blocking the event loop."""
    loop = asyncio.get_running_loop()
    future: asyncio.Future[str] = loop.create_future()

    def deliver(text: str) -> None:
        if not future.done():
            future.set_result(text)

    def worker() -> None:
        try:
            text = input(prompt)
        except EOFError:
            text = ""
        try:
            loop.call_soon_threadsafe(deliver, text)
        except RuntimeError:
            pass  # the loop is already closed

    # A daemon thread, so that a pending question never blocks the exit.
    threading.Thread(target=worker, daemon=True).start()
    return await future


def parse_stimulus(text: str) -> scenarios.Stimulus:
    """Parse ``knop``, ``schrijf`` or ``schrijf:SLEUTEL=a,b``."""
    if text == "knop":
        return scenarios.ButtonStimulus()
    if text == "schrijf":
        return scenarios.WriteStimulus()
    if text.startswith("schrijf:"):
        try:
            key, values = text.removeprefix("schrijf:").split("=")
            first, second = (int(v) for v in values.split(","))
        except ValueError as err:
            raise argparse.ArgumentTypeError("gebruik de vorm schrijf:SLEUTEL=a,b met twee gehele getallen") from err
        if first == second:
            raise argparse.ArgumentTypeError("de twee waarden moeten verschillen")
        return scenarios.WriteStimulus(key, (first, second))
    raise argparse.ArgumentTypeError("kies knop, schrijf of schrijf:SLEUTEL=a,b")


def parse_assignment(text: str) -> tuple[str, int]:
    """Parse ``SLEUTEL=getal``."""
    key, sep, value = text.partition("=")
    try:
        if not sep or not key:
            raise ValueError
        return key, int(value)
    except ValueError as err:
        raise argparse.ArgumentTypeError(
            f"{text!r}: gebruik SLEUTEL=getal; het apparaat verwerkt alleen gehele getallen"
        ) from err


def parse_minutes(text: str) -> tuple[float, ...]:
    """Parse a comma-separated list of minutes into seconds."""
    try:
        values = tuple(float(part) * 60 for part in text.split(","))
    except ValueError as err:
        raise argparse.ArgumentTypeError("gebruik minuten gescheiden door komma's, bijvoorbeeld 3,5,10,20") from err
    if not values or list(values) != sorted(values) or values[0] <= 0:
        raise argparse.ArgumentTypeError("de minuten moeten oplopen en groter dan nul zijn")
    return values


def parse_groups(text: str) -> list[str]:
    """Parse a comma-separated list of write groups."""
    groups = [part.strip() for part in text.split(",") if part.strip()]
    unknown = [g for g in groups if g not in scenarios.WRITE_GROUPS]
    if unknown or not groups:
        raise argparse.ArgumentTypeError("kies uit: " + ", ".join(scenarios.WRITE_GROUPS))
    return groups


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--host", required=True, help="IP-adres van de luchtreiniger")
    common.add_argument("--port", type=int, default=5683, help="UDP-poort (standaard 5683)")
    common.add_argument("--lokale-poort", type=int, default=0, help="vaste lokale UDP-poort (standaard: vrij gekozen)")
    common.add_argument("--map", type=Path, default=Path("metingen"), help="map voor de resultaten (standaard: metingen)")
    common.add_argument("--time-out", type=float, default=3.0, help="wachttijd per verzoek in seconden (standaard 3)")
    common.add_argument(
        "--stimulus",
        type=parse_stimulus,
        default=scenarios.ButtonStimulus(),
        help="hoe een verandering op het apparaat wordt uitgelokt: 'knop' (je drukt zelf, standaard), "
        "'schrijf' (kinderslot aan en uit) of 'schrijf:SLEUTEL=a,b'",
    )
    common.add_argument("--toon-ids", action="store_true", help="apparaat-id, product-id en naam niet afschermen in de resultaten")

    parser = argparse.ArgumentParser(
        prog="python -m pureprotect_probe", description=DESCRIPTION, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True, metavar="opdracht")

    def add(name: str, help_text: str) -> argparse.ArgumentParser:
        return sub.add_parser(name, parents=[common], help=help_text, description=help_text)

    p = add("quick", "eerste kennismaking: identiteit, bereikbaarheid en het eerste statusbericht (ongeveer 2 minuten)")
    p.add_argument("--duur", type=float, default=60.0, help="seconden meeluisteren aan het eind (standaard 60)")

    for name, text in (("info", "de info-aanvraag herhalen"), ("sync", "de sync-handshake herhalen"), ("ping", "de lege CoAP-ping herhalen")):
        p = add(name, text)
        p.add_argument("--aantal", type=int, default=10, help="aantal verzoeken (standaard 10)")
        p.add_argument("--interval", type=float, default=1.0, help="seconden tussen verzoeken (standaard 1)")
        if name != "ping":
            p.add_argument("--con", action="store_true", help="verzoeken met ontvangstbevestiging sturen")

    p = add("discover", "zoeken via broadcast en multicast")
    p.add_argument("--rondes", type=int, default=5, help="aantal rondes (standaard 5)")
    p.add_argument("--broadcast", help="broadcast-adres van het subnet (standaard: afgeleid van --host met masker /24)")

    p = add("status", "één volledige status ophalen en tonen")
    p.add_argument("--wacht", type=float, default=120.0, help="seconden wachten op een bericht na de stimulus (standaard 120)")

    p = add("observe", "meeluisteren met de statusstroom")
    p.add_argument("--duur", type=float, default=600.0, help="seconden (standaard 600)")
    p.add_argument("--vernieuw", choices=["geen", "zelfde", "nieuw"], default="geen", help="het abonnement vernieuwen met hetzelfde of een nieuw kenmerk")
    p.add_argument("--interval", type=float, default=60.0, help="seconden tussen vernieuwingen (standaard 60)")

    p = add("watch", "elke wijziging direct tonen; om instellingen in de app aan sleutels te koppelen")
    p.add_argument("--duur", type=float, default=1800.0, help="seconden (standaard 1800); stop eerder met Ctrl-C")
    p.add_argument("--alles", action="store_true", help="ook de meetwaarden tonen (fijnstof, index, temperatuur, vochtigheid)")

    p = add("liveness", "sync, info en ping vergelijken als bereikbaarheidscontrole; draai dit met het apparaat in stand-by")
    p.add_argument("--duur", type=float, default=7200.0, help="seconden (standaard 7200)")
    p.add_argument("--interval", type=float, default=30.0, help="seconden per ronde van drie controles (standaard 30)")
    p.add_argument("--vernieuw", choices=["geen", "zelfde"], default="zelfde", help="abonnement elke 60 s vernieuwen (standaard zelfde)")

    p = add("lapse", "nagaan of een abonnement zonder vernieuwing blijft leveren")
    p.add_argument("--controlepunten", type=parse_minutes, default=(180.0, 300.0, 600.0, 1200.0), help="minuten na de aanvraag (standaard 3,5,10,20)")
    p.add_argument("--sync-interval", type=float, help="ook elke zoveel seconden een sync sturen, om te zien of die het abonnement in leven houdt")

    p = add("refresh", "nagaan of opnieuw abonneren wordt beantwoord, met hetzelfde en met een nieuw kenmerk; apparaat aan")
    p.add_argument("--rondes", type=int, default=6, help="aantal rondes van drie vensters (standaard 6)")
    p.add_argument("--venster", type=float, default=3.0, help="seconden wachten op een antwoord (standaard 3)")

    add("second-client", "twee clients vanaf deze computer: wie krijgt de berichten, en wiens teller geldt")
    add("deregister", "nagaan of het apparaat afmelden en een reset respecteert")

    p = add("set", "één schrijfopdracht, met de tijd tot de terugmelding")
    p.add_argument("waarden", nargs="+", type=parse_assignment, metavar="SLEUTEL=getal")
    p.add_argument("--wacht", type=float, default=10.0, help="seconden wachten op de terugmelding (standaard 10)")
    p.add_argument("--geen-sync", action="store_true", help="geen sync vlak voor het schrijven (hergebruikt de vorige teller)")
    p.add_argument("--con", action="store_true", help="verzoeken met ontvangstbevestiging sturen")

    p = add("write-matrix", "alle schrijfopdrachten proberen die de integratie zou gebruiken, en daarna terugzetten")
    p.add_argument("--groepen", type=parse_groups, default=list(scenarios.WRITE_GROUPS), help="kommalijst uit: " + ", ".join(scenarios.WRITE_GROUPS))
    p.add_argument("--wacht", type=float, default=8.0, help="seconden wachten op elke terugmelding (standaard 8)")
    p.add_argument("--pauze", type=float, default=2.0, help="seconden tussen opdrachten (standaard 2)")
    p.add_argument("--ja", action="store_true", help="niet om bevestiging vragen")

    add("power-cycle", "begeleide proef: stekker eruit en erin")
    add("app", "begeleide proef: storen de Air+ app en deze client elkaar")
    return parser


def select(args: argparse.Namespace) -> Callable[[scenarios.Context], Awaitable[None]]:
    """Return the scenario for the parsed arguments."""
    command = args.command
    if command == "quick":
        return lambda ctx: scenarios.quick(ctx, duration=args.duur)
    if command in ("info", "sync", "ping"):
        return lambda ctx: scenarios.probes(ctx, command, count=args.aantal, interval=args.interval, con=getattr(args, "con", False))
    if command == "discover":
        return lambda ctx: scenarios.discover(ctx, rounds=args.rondes, broadcast=args.broadcast)
    if command == "status":
        return lambda ctx: scenarios.status(ctx, wait=args.wacht)
    if command == "observe":
        return lambda ctx: scenarios.observe(ctx, duration=args.duur, refresh=args.vernieuw, interval=args.interval)
    if command == "watch":
        return lambda ctx: scenarios.watch(ctx, duration=args.duur, show_all=args.alles)
    if command == "liveness":
        return lambda ctx: scenarios.liveness(ctx, duration=args.duur, interval=args.interval, refresh=args.vernieuw)
    if command == "lapse":
        return lambda ctx: scenarios.lapse(ctx, checkpoints=args.controlepunten, sync_interval=args.sync_interval)
    if command == "refresh":
        return lambda ctx: scenarios.refresh_test(ctx, rounds=args.rondes, window=args.venster)
    if command == "second-client":
        return scenarios.second_client
    if command == "deregister":
        return scenarios.deregister_test
    if command == "set":
        return lambda ctx: scenarios.write(ctx, dict(args.waarden), wait=args.wacht, sync_first=not args.geen_sync, con=args.con)
    if command == "write-matrix":
        return lambda ctx: scenarios.write_matrix(ctx, groups=args.groepen, wait=args.wacht, pause=args.pauze, assume_yes=args.ja)
    if command == "power-cycle":
        return scenarios.power_cycle
    if command == "app":
        return scenarios.app_test
    raise SystemExit(f"onbekende opdracht {command}")


async def run(args: argparse.Namespace) -> int:
    """Run one scenario and write its results."""
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir: Path = args.map / f"{stamp}-{args.command}"
    try:
        log = EventLog(out_dir / "events.jsonl")
    except OSError as err:
        print(f"Kan de map voor de resultaten niet aanmaken ({out_dir}): {err}")
        return 2
    arguments = {k: v for k, v in vars(args).items() if k not in ("stimulus", "map")}
    log.write("start", version=__version__, python=sys.version.split()[0], platform=sys.platform, stimulus=args.stimulus.label, arguments=arguments)
    try:
        endpoint = await Endpoint.open(log, "A", local_port=args.lokale_poort, peer_ip=args.host)
    except OSError as err:
        log.close()
        print(f"Kan de lokale UDP-poort niet openen: {err}")
        return 2
    device = Purifier(endpoint, args.host, args.port, redact_ids=not args.toon_ids)
    ctx = scenarios.Context(
        log=log, ep=endpoint, dev=device, host=args.host, port=args.port, stimulus=args.stimulus, ask=ask, out_dir=out_dir, timeout=args.time_out
    )
    interrupted = False
    failure: str | None = None
    try:
        await select(args)(ctx)
    except asyncio.CancelledError:
        interrupted = True
    except OSError as err:
        failure = f"Netwerkfout: {err}"
    finally:
        if interrupted:
            ctx.summary.append("AFGEBROKEN: de meting is niet afgemaakt; de regels hierboven zijn onvolledig.")
        if failure:
            ctx.summary.append(failure)
        if ctx.doubts:
            ctx.summary.append("")
            ctx.summary.append("Redenen om deze uitkomst te wantrouwen:")
            ctx.summary.extend(f"  - {doubt}" for doubt in ctx.doubts)
        log.write("result", command=args.command, interrupted=interrupted, failure=failure, doubts=ctx.doubts, **ctx.result)
        endpoint.close()
        for extra in ctx.extra_endpoints:
            extra.close()
        header = [
            f"Meetprogramma {__version__}, opdracht '{args.command}', {dt.datetime.now().astimezone().isoformat(timespec='seconds')}",
            f"Opties: {json.dumps(arguments, default=str, ensure_ascii=False)}",
            f"Stimulus: {args.stimulus.label}",
        ]
        if device.latest:
            status = device.latest
            header.append(
                f"Apparaat: model {status.get('D01S05')}, firmware {status.get('D01S12')}, wifi-firmware {status.get('WifiVersion')}"
            )
        header.append("")
        text = "\n".join(header + ctx.summary) + "\n"
        (out_dir / "samenvatting.txt").write_text(text, encoding="utf-8")
        log.close()
        print("\n=== SAMENVATTING ===")
        print("\n".join(ctx.summary) if ctx.summary else "(geen uitkomsten)")
        print(f"\nResultaten staan in {out_dir}")
    return 1 if failure else 0


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())

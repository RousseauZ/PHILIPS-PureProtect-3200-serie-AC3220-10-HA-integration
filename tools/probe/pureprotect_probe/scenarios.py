"""Measurement scenarios. Each one answers a design question about the device.

All text shown to the person running the tool is Dutch; the event log uses
English keys so that results from different people can be compared.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import statistics
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .coap import ALL_COAP_NODES, GET, MType, build_request
from .device import INFO_PATH, Frame, Purifier, Reply
from .endpoint import Endpoint, Received
from .eventlog import EventLog, redact

# A frame that arrives this fast after a registration is an answer to it.
# Later frames are more likely ordinary change notifications.
DIRECT_SECONDS = 1.5
# A status datagram above this size does not fit one Ethernet frame.
SINGLE_PACKET_PAYLOAD = 1472


# -- stimulus: something that makes the device report ----------------------


class Stimulus:
    """Makes the purifier change a value, so that it sends a status frame."""

    label = "geen"

    async def trigger(self, ctx: Context, reason: str) -> None:
        """Cause one change on the device."""
        raise NotImplementedError


class ButtonStimulus(Stimulus):
    """Asks the person to press a button on the purifier."""

    label = "knop"

    async def trigger(self, ctx: Context, reason: str) -> None:
        ctx.log.write("stimulus", kind="button", reason=reason)
        ctx.say(f"\a>>> Druk NU één keer op de standknop van de luchtreiniger ({reason}).")


class WriteStimulus(Stimulus):
    """Writes a setting to another value and back."""

    label = "schrijf"

    def __init__(self, key: str = "D03103", values: tuple[int, int] = (1, 0)) -> None:
        self.key = key
        self.values = values

    async def trigger(self, ctx: Context, reason: str) -> None:
        first, second = self.values
        current = (ctx.dev.latest or {}).get(self.key)
        if current == first:
            first, second = second, first
        elif current is not None and current != second:
            second = current
        # Unknown current value: writing both values guarantees one change.
        one = await ctx.dev.control({self.key: first})
        await ctx.rest(1.5)
        two = await ctx.dev.control({self.key: second})
        ctx.log.write("stimulus", kind="write", reason=reason, key=self.key, sequence=[first, second], ok=[one.ok, two.ok])


class CallbackStimulus(Stimulus):
    """Calls a function; used by the tests."""

    label = "test"

    def __init__(self, callback: Callable[[], None]) -> None:
        self.callback = callback

    async def trigger(self, ctx: Context, reason: str) -> None:
        ctx.log.write("stimulus", kind="callback", reason=reason)
        self.callback()


# -- context ---------------------------------------------------------------


@dataclass
class Context:
    """Everything a scenario needs."""

    log: EventLog
    ep: Endpoint
    dev: Purifier
    host: str
    port: int
    stimulus: Stimulus
    ask: Callable[[str], Awaitable[str]]
    out_dir: Path | None = None
    timeout: float = 3.0
    pace: float = 1.0  # multiplier for fixed pauses; the tests shorten them
    direct_window: float = 10.0  # how long to wait for an answer before a stimulus
    direct_seconds: float = DIRECT_SECONDS
    stimulus_wait: float = 30.0  # how long to wait for a frame after a stimulus
    first_frame_wait: float = 60.0  # same, for the very first frame
    summary: list[str] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)
    extra_endpoints: list[Endpoint] = field(default_factory=list)

    def say(self, text: str) -> None:
        """Show progress."""
        self.log.say(text)

    async def rest(self, seconds: float) -> None:
        """Pause between steps."""
        await asyncio.sleep(seconds * self.pace)

    def conclude(self, text: str) -> None:
        """Add a line to the summary, which is printed once at the end."""
        self.summary.append(text)
        self.log.write("conclusion", text=text)

    async def confirm(self, text: str) -> bool:
        """Ask a yes/no question; Enter means yes."""
        answer = (await self.ask(f">>> {text} [J/n] ")).strip().lower()
        self.log.write("answer", question=text, answer=answer)
        return answer in ("", "j", "ja", "y", "yes")

    async def pause_until_enter(self, text: str) -> None:
        """Wait until the person presses Enter."""
        await self.ask(f"\a>>> {text} Druk daarna op Enter. ")
        self.log.write("answer", question=text, answer="enter")


# -- helpers ---------------------------------------------------------------


def _ms(seconds: float | None) -> str:
    return "geen antwoord" if seconds is None else f"{seconds * 1000:.0f} ms"


def _sec(seconds: float | None) -> str:
    return "niet" if seconds is None else f"{seconds:.1f} s"


def reply_stats(replies: list[Reply]) -> dict[str, Any]:
    """Summarise a series of replies."""
    latencies = sorted(r.latency for r in replies if r.ok and r.latency is not None)
    longest_miss = run = 0
    for reply in replies:
        run = 0 if reply.ok else run + 1
        longest_miss = max(longest_miss, run)
    stats: dict[str, Any] = {
        "sent": len(replies),
        "answered": sum(1 for r in replies if r.ok),
        "not_ok": sum(1 for r in replies if not r.ok and r.kind != "timeout"),
        "longest_miss_run": longest_miss,
    }
    if latencies:
        stats.update(
            min_ms=round(latencies[0] * 1000),
            median_ms=round(statistics.median(latencies) * 1000),
            max_ms=round(latencies[-1] * 1000),
        )
    return stats


def stats_text(name: str, stats: dict[str, Any]) -> str:
    """One Dutch summary line for a series of replies."""
    text = f"{name}: {stats['answered']} van {stats['sent']} beantwoord"
    if "median_ms" in stats:
        text += f", mediaan {stats['median_ms']} ms (min {stats['min_ms']}, max {stats['max_ms']})"
    if stats["not_ok"]:
        text += f", {stats['not_ok']} keer een afwijkend antwoord"
    if stats["longest_miss_run"] > 1:
        text += f", langste reeks zonder antwoord: {stats['longest_miss_run']}"
    return text


def frame_gaps(frames: list[Frame], start: float, end: float) -> float:
    """Return the longest silence in seconds between start, the frames and end."""
    times = [start] + [f.t for f in frames if start <= f.t <= end] + [end]
    return max(b - a for a, b in zip(times, times[1:], strict=False))


async def wait_any_frame(devs: list[Purifier], starts: list[int], timeout: float) -> bool:
    """Wait until any of the devices has a frame beyond its start index."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if any(len(dev.frames) > start for dev, start in zip(devs, starts, strict=True)):
            return True
        await asyncio.sleep(0.05)
    return False


async def stimulate(
    ctx: Context, reason: str, *, devs: list[Purifier] | None = None, wait: float | None = None, settle: float = 2.0
) -> list[list[Frame]]:
    """Trigger a change and return the frames each device object received."""
    devices = devs or [ctx.dev]
    starts = [len(dev.frames) for dev in devices]
    await ctx.stimulus.trigger(ctx, reason)
    if await wait_any_frame(devices, starts, ctx.stimulus_wait if wait is None else wait):
        await ctx.rest(settle)
    return [dev.frames[start:] for dev, start in zip(devices, starts, strict=True)]


async def ensure_alive(
    ctx: Context,
    dev: Purifier,
    token: bytes,
    *,
    register: bool = True,
    direct_window: float | None = None,
    stimulus_wait: float | None = None,
    reason: str = "eerste statusbericht",
) -> dict[str, Any]:
    """Register (optionally) and make sure a frame arrives on the token."""
    start = len(dev.frames)
    sent = ctx.log.now()
    if register:
        dev.register(token)

    def on_token(frame: Frame) -> bool:
        return frame.token == token

    window = ctx.direct_window if direct_window is None else direct_window
    frame = await dev.wait_frame(since=start, timeout=window, predicate=on_token)
    used_stimulus = False
    if frame is None:
        used_stimulus = True
        await ctx.stimulus.trigger(ctx, reason)
        patience = ctx.first_frame_wait if stimulus_wait is None else stimulus_wait
        frame = await dev.wait_frame(since=start, timeout=patience, predicate=on_token)
    latency = None if frame is None else round(frame.t - sent, 3)
    return {
        "frame": frame,
        "latency": latency,
        "direct": latency is not None and latency <= ctx.direct_seconds and not used_stimulus,
        "needed_stimulus": used_stimulus,
    }


def describe_first(alive: dict[str, Any]) -> str:
    """Dutch description of how the first frame arrived."""
    if alive["frame"] is None:
        return "geen statusbericht ontvangen"
    if alive["direct"]:
        return f"eerste statusbericht na {_sec(alive['latency'])} (direct antwoord op de aanvraag)"
    if alive["needed_stimulus"]:
        return f"eerste statusbericht pas na een verandering op het apparaat ({_sec(alive['latency'])} na de aanvraag)"
    return f"eerste statusbericht na {_sec(alive['latency'])} (waarschijnlijk een gewone melding, geen direct antwoord)"


def describe_frame(frame: Frame) -> str:
    """Dutch description of the transport properties of a frame."""
    size = "past in één pakket" if frame.size <= SINGLE_PACKET_PAYLOAD else "groter dan één pakket, komt gefragmenteerd aan"
    kind = "met ontvangstbevestiging (CON)" if frame.mtype == MType.CON else "zonder ontvangstbevestiging (NON)"
    return f"Statusbericht: {frame.size} bytes ({size}), {kind}, Max-Age {frame.max_age}, volgnummer {frame.observe}"


def save_status(ctx: Context, reported: dict[str, Any]) -> None:
    """Write the status as JSON next to the event log."""
    if ctx.out_dir is None:
        return
    path = ctx.out_dir / "status.json"
    path.write_text(json.dumps(redact(reported, ctx.dev.redact_ids), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


async def probe_series(call: Callable[[], Awaitable[Reply]], count: int, interval: float) -> list[Reply]:
    """Run one kind of request several times."""
    replies = []
    for index in range(count):
        replies.append(await call())
        if index + 1 < count:
            await asyncio.sleep(interval)
    return replies


# -- scenarios -------------------------------------------------------------


async def quick(ctx: Context, *, duration: float = 60.0, count: int = 3) -> None:
    """First contact: identity, the three probes, and how the first status arrives."""
    dev = ctx.dev
    ctx.say("Stap 1 van 5: info-aanvraag, sync en CoAP-ping.")
    info = await probe_series(lambda: dev.info(timeout=ctx.timeout), count, 1.0)
    info_con = await dev.info(con=True, timeout=ctx.timeout)
    sync = await probe_series(lambda: dev.sync(timeout=ctx.timeout), count, 1.0)
    sync_con = await dev.sync(con=True, timeout=ctx.timeout)
    ping = await probe_series(lambda: dev.ping(timeout=ctx.timeout), count, 1.0)
    info_data = next((r.data for r in [*info, info_con] if isinstance(r.data, dict)), None)

    ctx.say("Stap 2 van 5: abonnement op de status.")
    token = ctx.ep.new_token()
    alive = await ensure_alive(ctx, dev, token)
    frame: Frame | None = alive["frame"]

    ctx.say("Stap 3 van 5: twee keer vernieuwen met hetzelfde kenmerk.")
    refresh_direct = 0
    for _ in range(2):
        await ctx.rest(5.0)
        start, sent = len(dev.frames), ctx.log.now()
        dev.register(token, what="refresh-same")
        answer = await dev.wait_frame(since=start, timeout=ctx.direct_seconds)
        ctx.log.write("refresh", mode="same", answered=answer is not None, latency=None if answer is None else round(answer.t - sent, 3), identical=None if answer is None else answer.identical)
        refresh_direct += answer is not None

    ctx.say("Stap 4 van 5: statusaanvraag zonder abonnement.")
    plain_token = ctx.ep.new_token()
    start = len(dev.frames)
    dev.plain_status_get(plain_token)
    plain = await dev.wait_frame(since=start, timeout=5.0 * ctx.pace, predicate=lambda f: f.token == plain_token)

    ctx.say(f"Stap 5 van 5: {duration:.0f} seconden meeluisteren.")
    listen_start, frames_before = ctx.log.now(), len(dev.frames)
    await asyncio.sleep(duration)
    listened = dev.frames[frames_before:]

    stats = {"info": reply_stats(info), "sync": reply_stats(sync), "ping": reply_stats(ping)}
    ctx.conclude(stats_text("Info-aanvraag", stats["info"]))
    ctx.conclude(stats_text("Sync", stats["sync"]))
    ctx.conclude(stats_text("CoAP-ping", stats["ping"]))
    ctx.conclude(
        "Verzoeken met ontvangstbevestiging (CON): info "
        + ("beantwoord" if info_con.ok else "niet beantwoord")
        + ", sync "
        + ("beantwoord" if sync_con.ok else "niet beantwoord")
        + "."
    )
    ctx.conclude("Abonnement: " + describe_first(alive) + ".")
    ctx.conclude(f"Vernieuwen met hetzelfde kenmerk: {refresh_direct} van 2 direct beantwoord.")
    ctx.conclude("Statusaanvraag zonder abonnement: " + ("beantwoord." if plain is not None else "niet beantwoord binnen 5 s."))
    same_id: bool | None = None
    if frame is not None and frame.reported is not None:
        reported = frame.reported
        save_status(ctx, dev.latest or reported)
        ctx.conclude(
            f"Apparaat: model {reported.get('D01S05')}, platform {reported.get('D01S04')}, "
            f"firmware {reported.get('D01S12')}, wifi-firmware {reported.get('WifiVersion')}."
        )
        ctx.conclude(describe_frame(frame) + ".")
        ctx.conclude(f"Sleutels in de status ({len(reported)}): " + " ".join(sorted(reported)))
        if info_data is not None:
            same_id = str(info_data.get("device_id")) == str(reported.get("DeviceId"))
            ctx.conclude(
                "Het device_id uit de info-aanvraag is "
                + ("gelijk aan" if same_id else "ANDERS dan")
                + " het DeviceId in de status."
            )
    if info_data is not None:
        ctx.conclude(
            f"Info-antwoord: modelid {info_data.get('modelid')}, type {info_data.get('type')}, "
            f"swversion {info_data.get('swversion')}, option {info_data.get('option')}."
        )
    ctx.conclude(
        f"Meeluisteren: {len(listened)} statusberichten in {duration:.0f} s, "
        f"langste stilte {frame_gaps(listened, listen_start, ctx.log.now()):.0f} s."
    )
    bad = [f for f in dev.frames if f.decode.startswith("err")]
    if bad:
        ctx.conclude(f"Let op: {len(bad)} bericht(en) niet te ontcijferen ({bad[0].decode}).")
    ctx.result.update(
        stats=stats,
        info_con=info_con.ok,
        sync_con=sync_con.ok,
        first_frame={k: v for k, v in alive.items() if k != "frame"},
        refresh_same_direct=refresh_direct,
        plain_get_answered=plain is not None,
        device_id_matches=same_id,
        frames_while_listening=len(listened),
    )


async def probes(ctx: Context, kind: str, *, count: int = 10, interval: float = 1.0, con: bool = False) -> None:
    """Repeat one request type: info, sync or ping."""
    dev = ctx.dev
    calls: dict[str, Callable[[], Awaitable[Reply]]] = {
        "info": lambda: dev.info(con=con, timeout=ctx.timeout),
        "sync": lambda: dev.sync(con=con, timeout=ctx.timeout),
        "ping": lambda: dev.ping(timeout=ctx.timeout),
    }
    replies = await probe_series(calls[kind], count, interval)
    stats = reply_stats(replies)
    names = {"info": "Info-aanvraag", "sync": "Sync", "ping": "CoAP-ping"}
    ctx.conclude(stats_text(names[kind] + (" (CON)" if con and kind != "ping" else ""), stats))
    if kind == "info":
        data = next((r.data for r in replies if isinstance(r.data, dict)), None)
        if data is not None:
            ctx.conclude("Antwoord: " + json.dumps(redact(data, dev.redact_ids), ensure_ascii=False))
    if kind == "sync":
        counters = [r.data for r in replies if r.ok]
        ctx.conclude("Tellers: " + " ".join(counters))
    ctx.result.update(kind=kind, con=con, stats=stats)


async def discover(ctx: Context, *, rounds: int = 5, broadcast: str | None = None, listen: float = 3.0) -> None:
    """Send the info request to broadcast and multicast addresses and count replies."""
    targets: dict[str, str] = {"beperkte broadcast": "255.255.255.255"}
    if broadcast is None:
        try:
            network = ipaddress.ip_network(f"{ctx.host}/24", strict=False)
            broadcast = str(network.broadcast_address)
        except ValueError:
            broadcast = None
    if broadcast:
        targets[f"subnet-broadcast {broadcast}"] = broadcast
    targets[f"multicast {ALL_COAP_NODES}"] = ALL_COAP_NODES
    targets[f"rechtstreeks {ctx.host}"] = ctx.host

    ctx.ep.peer_ip = None  # replies may come from any device
    ctx.ep.unknown_policy = "ignore"
    tokens = {name: ctx.ep.new_token() for name in targets}
    by_token = {token: name for name, token in tokens.items()}
    replies: dict[str, dict[str, int]] = {name: {} for name in targets}
    details: dict[str, dict[str, Any]] = {}

    def collect(received: Received) -> None:
        name = by_token.get(received.msg.token)
        if name is None:
            return
        sender = received.addr[0]
        replies[name][sender] = replies[name].get(sender, 0) + 1
        try:
            details[sender] = json.loads(received.msg.payload.decode("utf-8", "replace"))
        except ValueError:
            details.setdefault(sender, {})

    ctx.ep.add_listener(collect)
    for _ in range(rounds):
        for name, address in targets.items():
            msg = build_request(MType.NON, GET, ctx.ep.next_mid(), tokens[name], INFO_PATH)
            try:
                ctx.ep.send(msg, (address, ctx.port), what="discover")
            except OSError as err:
                ctx.log.write("send_error", target=address, error=repr(err))
        await ctx.rest(1.0)
    await ctx.rest(listen)

    for name in targets:
        seen = replies[name]
        from_device = seen.get(ctx.host, 0)
        others = sorted(set(seen) - {ctx.host})
        text = f"{name}: {from_device} van {rounds} beantwoord door de luchtreiniger"
        if others:
            text += f"; ook antwoord van {', '.join(others)}"
        ctx.conclude(text + ".")
    for sender, data in details.items():
        shown = redact(data, ctx.dev.redact_ids)
        ctx.conclude(f"{sender}: modelid {shown.get('modelid')}, type {shown.get('type')}, device_id {shown.get('device_id')}")
    ctx.result.update(replies=replies, rounds=rounds)


async def status(ctx: Context, *, wait: float = 120.0) -> None:
    """Fetch one full status and save it."""
    alive = await ensure_alive(ctx, ctx.dev, ctx.ep.new_token(), stimulus_wait=wait)
    ctx.conclude("Abonnement: " + describe_first(alive) + ".")
    frame: Frame | None = alive["frame"]
    if frame is None or frame.reported is None:
        if frame is not None:
            ctx.conclude(f"Het bericht was niet te ontcijferen: {frame.decode}.")
        return
    save_status(ctx, frame.reported)
    ctx.conclude(describe_frame(frame) + ".")
    print(json.dumps(redact(frame.reported, ctx.dev.redact_ids), indent=2, ensure_ascii=False))
    ctx.result.update(first_frame={k: v for k, v in alive.items() if k != "frame"}, keys=sorted(frame.reported))


async def observe(ctx: Context, *, duration: float = 600.0, refresh: str = "geen", interval: float = 60.0) -> None:
    """Listen to the status stream, with an optional refresh strategy."""
    dev = ctx.dev
    token = ctx.ep.new_token()
    tokens = [token]
    start_time = ctx.log.now()
    dev.register(token)
    refreshes: list[dict[str, Any]] = []
    loop = asyncio.get_running_loop()
    end = loop.time() + duration
    next_refresh = loop.time() + interval
    while loop.time() < end:
        await asyncio.sleep(min(1.0, max(0.0, end - loop.time())))
        if refresh != "geen" and loop.time() >= next_refresh:
            next_refresh += interval
            if refresh == "nieuw":
                token = ctx.ep.new_token()
                tokens.append(token)
            start, sent = len(dev.frames), ctx.log.now()
            dev.register(token, what=f"refresh-{refresh}")
            current = token
            answer = await dev.wait_frame(since=start, timeout=ctx.direct_seconds, predicate=lambda f, t=current: f.token == t)
            entry = {"t": round(sent, 2), "answered": answer is not None, "identical": None if answer is None else answer.identical}
            refreshes.append(entry)
            ctx.log.write("refresh", mode=refresh, token=token.hex(), **entry)
    frames = dev.frames
    per_token = {t.hex(): sum(1 for f in frames if f.token == t) for t in tokens}
    bad = [f for f in frames if f.decode.startswith("err")]
    kinds = sorted({f.mtype.name for f in frames})
    ctx.conclude(f"{len(frames)} statusberichten in {duration:.0f} s; langste stilte {frame_gaps(frames, start_time, ctx.log.now()):.0f} s.")
    if frames:
        ctx.conclude(f"Eerste bericht {frames[0].t - start_time:.1f} s na de aanvraag; laatste {ctx.log.now() - frames[-1].t:.0f} s voor het einde.")
        ctx.conclude(f"Berichttype: {', '.join(kinds)}; Max-Age {sorted({f.max_age for f in frames if f.max_age is not None})}.")
    if refresh != "geen":
        answered = sum(1 for r in refreshes if r["answered"])
        ctx.conclude(f"Vernieuwen ({refresh} kenmerk, elke {interval:.0f} s): {answered} van {len(refreshes)} direct beantwoord.")
        if refresh == "nieuw":
            ctx.conclude("Berichten per kenmerk: " + ", ".join(f"{k}: {v}" for k, v in per_token.items()))
    if bad:
        ctx.conclude(f"Niet te ontcijferen: {len(bad)} ({', '.join(sorted({f.decode for f in bad}))}).")
    observe_values = [f.observe for f in frames if f.observe is not None]
    if len(observe_values) > 1:
        rising = all(b > a for a, b in zip(observe_values, observe_values[1:], strict=False))
        ctx.conclude("Volgnummers lopen " + ("steeds op." if rising else "NIET steeds op."))
    if dev.latest:
        save_status(ctx, dev.latest)
    ctx.result.update(frames=len(frames), per_token=per_token, refreshes=refreshes, undecodable=len(bad), frame_types=kinds)


async def liveness(ctx: Context, *, duration: float = 7200.0, interval: float = 30.0, refresh: str = "zelfde") -> None:
    """Compare sync, info and ping as reachability probes during silence."""
    dev = ctx.dev
    token = ctx.ep.new_token()
    start_time = ctx.log.now()
    dev.register(token)
    series: dict[str, list[Reply]] = {"sync": [], "info": [], "ping": []}
    during_silence: dict[str, list[Reply]] = {"sync": [], "info": [], "ping": []}
    loop = asyncio.get_running_loop()
    end = loop.time() + duration
    step = interval / 3
    last_refresh = loop.time()
    calls: list[tuple[str, Callable[[], Awaitable[Reply]]]] = [
        ("sync", lambda: dev.sync(timeout=ctx.timeout)),
        ("info", lambda: dev.info(timeout=ctx.timeout)),
        ("ping", lambda: dev.ping(timeout=ctx.timeout)),
    ]
    cycle = 0
    while loop.time() < end:
        for name, call in calls:
            began = loop.time()
            reply = await call()
            series[name].append(reply)
            silent_for = ctx.log.now() - (dev.frames[-1].t if dev.frames else start_time)
            if silent_for > 120:
                during_silence[name].append(reply)
            await asyncio.sleep(max(0.0, step - (loop.time() - began)))
            if loop.time() >= end:
                break
        cycle += 1
        if refresh == "zelfde" and loop.time() - last_refresh >= 60:
            last_refresh = loop.time()
            dev.register(token, what="refresh-same")
        if cycle % 20 == 0:
            ctx.say(f"{cycle} rondes, {len(dev.frames)} statusberichten tot nu toe.")
    names = {"sync": "Sync", "info": "Info-aanvraag", "ping": "CoAP-ping"}
    stats = {name: reply_stats(replies) for name, replies in series.items()}
    silence_stats = {name: reply_stats(replies) for name, replies in during_silence.items()}
    for name in series:
        ctx.conclude(stats_text(names[name], stats[name]))
    longest = frame_gaps(dev.frames, start_time, ctx.log.now())
    ctx.conclude(f"{len(dev.frames)} statusberichten; langste stilte {longest:.0f} s.")
    if any(during_silence.values()):
        ctx.conclude("Tijdens stiltes van meer dan 2 minuten:")
        for name in series:
            if during_silence[name]:
                ctx.conclude("  " + stats_text(names[name], silence_stats[name]))
    else:
        ctx.conclude("Er was geen stilte van meer dan 2 minuten; herhaal de meting met het apparaat in stand-by.")
    counters = [int(r.data, 16) for r in series["sync"] if r.ok]
    if len(counters) > 2:
        steps = {(b - a) % 0x1_0000_0000 for a, b in zip(counters, counters[1:], strict=False)}
        ctx.conclude("Sync-tellers: " + ("lopen telkens met 1 op." if steps == {1} else f"{len(steps)} verschillende stapgroottes (niet oplopend met 1)."))
    ctx.result.update(stats=stats, during_silence=silence_stats, frames=len(dev.frames), longest_silence=round(longest))


async def lapse(
    ctx: Context,
    *,
    checkpoints: tuple[float, ...] = (180.0, 300.0, 600.0, 1200.0),
    sync_interval: float | None = None,
    recent: float = 20.0,
) -> None:
    """Does a single registration keep delivering, or does it lapse?"""
    dev = ctx.dev
    token = ctx.ep.new_token()
    alive = await ensure_alive(ctx, dev, token)
    ctx.conclude("Abonnement: " + describe_first(alive) + ".")
    if alive["frame"] is None:
        ctx.conclude("Zonder eerste statusbericht is deze meting niet uit te voeren.")
        return
    registered = alive["frame"].t - alive["latency"]
    loop = asyncio.get_running_loop()
    origin = loop.time() - (ctx.log.now() - registered)
    last_sync = loop.time()
    outcomes: list[dict[str, Any]] = []
    dead_at: float | None = None
    for checkpoint in checkpoints:
        while loop.time() < origin + checkpoint:
            await asyncio.sleep(min(1.0, max(0.0, origin + checkpoint - loop.time())))
            if sync_interval and loop.time() - last_sync >= sync_interval:
                last_sync = loop.time()
                await dev.sync(timeout=ctx.timeout)
        spontaneous = bool(dev.frames) and ctx.log.now() - dev.frames[-1].t <= recent
        got = spontaneous
        if not spontaneous:
            got = bool((await stimulate(ctx, f"controle na {checkpoint / 60:.0f} min"))[0])
        outcomes.append({"after_s": checkpoint, "alive": got, "spontaneous": spontaneous})
        ctx.say(f"Na {checkpoint / 60:.0f} min: abonnement {'levert nog' if got else 'levert NIET meer'}.")
        if not got:
            dead_at = checkpoint
            break
    recovery: dict[str, Any] = {}
    if dead_at is None:
        ctx.conclude(f"Het abonnement leverde nog na {checkpoints[-1] / 60:.0f} minuten zonder vernieuwing.")
    else:
        previous = [o["after_s"] for o in outcomes if o["alive"]]
        since = f"{previous[-1] / 60:.0f} min" if previous else "het begin"
        last_frame = dev.frames[-1].t - registered
        ctx.conclude(f"Het abonnement leverde niet meer bij {dead_at / 60:.0f} min (wel nog bij {since}); laatste bericht {last_frame:.0f} s na de aanvraag.")
        reachable = await dev.sync(timeout=ctx.timeout)
        ctx.conclude("Sync op dat moment: " + ("beantwoord, het apparaat is dus bereikbaar." if reachable.ok else "NIET beantwoord; het apparaat is mogelijk onbereikbaar en de uitkomst is onzeker."))
        same = await ensure_alive(ctx, dev, token, reason="herstel met hetzelfde kenmerk", stimulus_wait=ctx.stimulus_wait)
        recovery["same_token"] = same["frame"] is not None
        ctx.conclude("Opnieuw abonneren met hetzelfde kenmerk: " + ("levert weer." if recovery["same_token"] else "levert NIET."))
        if not recovery["same_token"]:
            fresh = await ensure_alive(ctx, dev, ctx.ep.new_token(), reason="herstel met een nieuw kenmerk", stimulus_wait=ctx.stimulus_wait)
            recovery["new_token"] = fresh["frame"] is not None
            ctx.conclude("Opnieuw abonneren met een nieuw kenmerk: " + ("levert weer." if recovery["new_token"] else "levert NIET."))
    if sync_interval:
        ctx.conclude(f"Tijdens deze meting is elke {sync_interval:.0f} s een sync gestuurd.")
    ctx.result.update(checkpoints=outcomes, dead_at=dead_at, recovery=recovery, with_sync=sync_interval)


async def refresh_test(ctx: Context, *, pause: float = 20.0, repeats: int = 3) -> None:
    """Is a re-registration answered directly, and which token delivers afterwards?"""
    dev = ctx.dev
    token = ctx.ep.new_token()
    alive = await ensure_alive(ctx, dev, token)
    ctx.conclude("Abonnement: " + describe_first(alive) + ".")
    if alive["frame"] is None:
        ctx.conclude("Zonder eerste statusbericht is deze meting niet uit te voeren.")
        return
    same: list[dict[str, Any]] = []
    for _ in range(repeats):
        await asyncio.sleep(pause)
        quiet_for = ctx.log.now() - dev.frames[-1].t
        start, sent = len(dev.frames), ctx.log.now()
        dev.register(token, what="refresh-same")
        answer = await dev.wait_frame(since=start, timeout=ctx.direct_seconds)
        entry = {"answered": answer is not None, "identical": None if answer is None else answer.identical, "quiet_before_s": round(quiet_for, 1)}
        same.append(entry)
        ctx.log.write("refresh", mode="same", latency=None if answer is None else round(answer.t - sent, 3), **entry)
    answered = sum(1 for r in same if r["answered"])
    ctx.conclude(f"Vernieuwen met hetzelfde kenmerk: {answered} van {repeats} direct beantwoord.")
    after_same = (await stimulate(ctx, "na vernieuwen met hetzelfde kenmerk"))[0]
    duplicates = len(after_same) - len({f.observe for f in after_same})
    ctx.conclude(
        "Na een verandering: "
        + (f"{len(after_same)} bericht(en) ontvangen" if after_same else "GEEN bericht ontvangen")
        + (f", waarvan {duplicates} dubbel" if duplicates > 0 else "")
        + "."
    )
    new_token = ctx.ep.new_token()
    start, sent = len(dev.frames), ctx.log.now()
    dev.register(new_token, what="refresh-new")
    direct_new = await dev.wait_frame(since=start, timeout=ctx.direct_seconds, predicate=lambda f: f.token == new_token)
    ctx.conclude("Abonneren met een nieuw kenmerk: " + ("direct beantwoord." if direct_new is not None else "niet direct beantwoord."))
    await ctx.rest(3.0)
    after_new = (await stimulate(ctx, "na abonneren met een nieuw kenmerk"))[0]
    on_old = sum(1 for f in after_new if f.token == token)
    on_new = sum(1 for f in after_new if f.token == new_token)
    ctx.conclude(f"Na een verandering: {on_old} bericht(en) op het oude kenmerk, {on_new} op het nieuwe.")
    if on_old and on_new:
        ctx.conclude("Het apparaat bedient beide abonnementen; een oud kenmerk moet dus worden afgemeld.")
    elif on_new:
        ctx.conclude("Het nieuwe kenmerk heeft het oude vervangen.")
    elif on_old:
        ctx.conclude("Alleen het oude kenmerk levert; het nieuwe abonnement is niet aangenomen.")
    ctx.result.update(same=same, after_same=len(after_same), duplicates=duplicates, new_direct=direct_new is not None, after_new={"old": on_old, "new": on_new})


async def second_client(ctx: Context) -> None:
    """Two clients from this computer: who gets the frames, and whose counter counts?"""
    dev_a = ctx.dev
    ep_b = await Endpoint.open(ctx.log, "B", peer_ip=ctx.ep.peer_ip)
    ctx.extra_endpoints.append(ep_b)
    dev_b = Purifier(ep_b, ctx.host, ctx.port, redact_ids=dev_a.redact_ids)
    token_a, token_b = ctx.ep.new_token(), ep_b.new_token()
    alive = await ensure_alive(ctx, dev_a, token_a)
    ctx.conclude("Client A: " + describe_first(alive) + ".")
    if alive["frame"] is None:
        ctx.conclude("Zonder eerste statusbericht is deze meting niet uit te voeren.")
        return
    start_b = len(dev_b.frames)
    dev_b.register(token_b)
    direct_b = await dev_b.wait_frame(since=start_b, timeout=ctx.direct_seconds)
    ctx.conclude(f"Client B (lokale poort {ep_b.local_port}) abonneert: " + ("direct beantwoord." if direct_b else "niet direct beantwoord."))
    await ctx.rest(3.0)
    frames_a, frames_b = await stimulate(ctx, "beide clients geabonneerd", devs=[dev_a, dev_b])
    ctx.conclude(f"Na een verandering: A ontvangt {len(frames_a)} bericht(en), B ontvangt {len(frames_b)}.")
    if frames_a and frames_b:
        ctx.conclude("Het apparaat bedient twee abonnees vanaf hetzelfde IP-adres.")
    elif frames_b:
        ctx.conclude("De nieuwste abonnee heeft de oudste verdrongen: één abonnee per IP-adres.")
    elif frames_a:
        ctx.conclude("De tweede abonnee is niet aangenomen; de eerste blijft leveren.")
    sync_b = await dev_b.sync(timeout=ctx.timeout)
    frames_after_sync, _ = await stimulate(ctx, "na een sync van client B", devs=[dev_a, dev_b])
    ctx.conclude(
        "Na een sync van B "
        + ("(beantwoord)" if sync_b.ok else "(niet beantwoord)")
        + f" ontvangt A {len(frames_after_sync)} bericht(en) bij een verandering."
    )
    counter_result: dict[str, Any] = {}
    key = "D03103"
    current = (dev_a.latest or {}).get(key)
    if isinstance(current, int):
        sync_a = await dev_a.sync(timeout=ctx.timeout)
        sync_b2 = await dev_b.sync(timeout=ctx.timeout)
        if sync_a.ok and sync_b2.ok:
            write_a = await dev_a.control({key: current}, sync_first=False, timeout=ctx.timeout)
            write_b = await dev_b.control({key: current}, sync_first=False, timeout=ctx.timeout)
            counter_result = {"a_after_b_synced": write_a.data, "b_own_counter": write_b.data}
            ctx.conclude(
                f"Tellerproef (A synct, B synct, daarna schrijft A en dan B, elk met de eigen teller): A {write_a.data or 'geen antwoord'}, B {write_b.data or 'geen antwoord'}."
            )
            if write_a.ok and write_b.ok:
                ctx.conclude("Elke client heeft een eigen teller; een sync van een ander stoort niet.")
            elif write_b.ok and not write_a.ok:
                ctx.conclude("Er is één gedeelde teller: de sync van B maakte de teller van A ongeldig. Sync dus direct vóór elk commando.")
    else:
        ctx.conclude(f"Tellerproef overgeslagen: sleutel {key} staat niet in de status.")
    ctx.result.update(b_direct=direct_b is not None, frames={"a": len(frames_a), "b": len(frames_b)}, a_after_b_sync=len(frames_after_sync), counter=counter_result)


async def deregister_test(ctx: Context) -> None:
    """Does the device honour a deregistration, and a Reset?"""
    dev = ctx.dev
    token = ctx.ep.new_token()
    alive = await ensure_alive(ctx, dev, token)
    ctx.conclude("Abonnement: " + describe_first(alive) + ".")
    if alive["frame"] is None:
        ctx.conclude("Zonder eerste statusbericht is deze meting niet uit te voeren.")
        return
    dev.deregister(token)
    await ctx.rest(3.0)
    after = (await stimulate(ctx, "na afmelden"))[0]
    honoured = not after
    ctx.conclude("Afmelden (Observe 1): " + ("gerespecteerd, er komt geen bericht meer." if honoured else f"NIET gerespecteerd, er kwamen nog {len(after)} bericht(en)."))
    again = await ensure_alive(ctx, dev, token, reason="opnieuw abonneren")
    reset_honoured: bool | None = None
    if again["frame"] is None:
        ctx.conclude("Opnieuw abonneren leverde geen bericht; de proef met een reset is overgeslagen.")
    else:
        await ctx.rest(3.0)
        ctx.ep.reject_next(token)
        rejected = (await stimulate(ctx, "bericht dat met een reset wordt beantwoord"))[0]
        if not rejected:
            ctx.conclude("Er kwam geen bericht om met een reset te beantwoorden.")
        else:
            await ctx.rest(3.0)
            later = (await stimulate(ctx, "na de reset"))[0]
            reset_honoured = not later
            ctx.conclude("Reset op een statusbericht: " + ("gerespecteerd, het abonnement is beëindigd." if reset_honoured else f"NIET gerespecteerd, er kwamen nog {len(later)} bericht(en)."))
    ctx.result.update(deregister_honoured=honoured, reset_honoured=reset_honoured)


def accepted_readback(key: str, value: int) -> set[int]:
    """Values the device may report after a successful write."""
    if key == "D03130":
        return {100} if value else {0}
    return {value}


async def write_once(ctx: Context, values: dict[str, int], *, wait: float, sync_first: bool = True, con: bool = False) -> dict[str, Any]:
    """Write values and wait for the status to show them."""
    dev = ctx.dev
    before = {key: (dev.latest or {}).get(key) for key in values}
    start, sent = len(dev.frames), ctx.log.now()
    reply = await dev.control(values, sync_first=sync_first, con=con, timeout=ctx.timeout)

    def shows(frame: Frame) -> bool:
        return frame.reported is not None and all(frame.reported.get(k) in accepted_readback(k, v) for k, v in values.items())

    echo = await dev.wait_frame(since=start, timeout=wait, predicate=shows) if reply.kind == "response" else None
    any_frame = dev.frames[start] if len(dev.frames) > start else None
    latest = dev.latest or {}
    outcome = {
        "values": values,
        "before": before,
        "reply": reply.data if reply.kind == "response" else reply.kind,
        "reply_ms": None if reply.latency is None else round(reply.latency * 1000),
        "echo_s": None if echo is None else round(echo.t - sent, 2),
        "any_frame_s": None if any_frame is None else round(any_frame.t - sent, 2),
        "status_type": None if echo is None or echo.reported is None else echo.reported.get("StatusType"),
        "readback": {key: latest.get(key) for key in values},
        "fan_level": latest.get("D0310D"),
        "same_value": all(before[k] in accepted_readback(k, v) for k, v in values.items()),
    }
    ctx.log.write("write_result", **outcome)
    return outcome


def describe_write(outcome: dict[str, Any]) -> str:
    """One Dutch line for a write outcome."""
    values = " ".join(f"{k}={v}" for k, v in outcome["values"].items())
    reply = outcome["reply"]
    text = f"{values}: antwoord {reply}"
    if outcome["reply_ms"] is not None:
        text += f" na {outcome['reply_ms']} ms"
    if outcome["same_value"]:
        frame = outcome["any_frame_s"]
        text += "; waarde gold al, " + (f"toch een statusbericht na {frame} s" if frame is not None else "geen statusbericht")
    elif outcome["echo_s"] is not None:
        text += f"; teruggemeld na {outcome['echo_s']} s"
        if outcome["status_type"]:
            text += f" (StatusType {outcome['status_type']})"
    else:
        readback = " ".join(f"{k}={v}" for k, v in outcome["readback"].items())
        text += f"; NIET teruggemeld, status toont {readback}"
    if "D0310C" in outcome["values"]:
        text += f"; toerental D0310D={outcome['fan_level']}"
    return text + "."


async def write(ctx: Context, values: dict[str, int], *, wait: float = 10.0, sync_first: bool = True, con: bool = False) -> None:
    """One write, with the time until the device reports it."""
    dev = ctx.dev
    dev.register(ctx.ep.new_token())
    if await dev.wait_frame(since=0, timeout=5.0 * ctx.pace) is None:
        ctx.say("Nog geen statusbericht ontvangen; de waarde vooraf is onbekend.")
    outcome = await write_once(ctx, values, wait=wait, sync_first=sync_first, con=con)
    ctx.conclude(describe_write(outcome))
    ctx.result.update(outcome)


WRITE_GROUPS: dict[str, list[tuple[str, int]]] = {
    "aanuit": [("D03102", 0), ("D03102", 1)],
    "standen": [("D0310C", 17), ("D0310C", 19), ("D0310C", 18), ("D0310C", 0)],
    "snelheden": [("D0310C", 1), ("D0310C", 2), ("D0310C", 3), ("D0310C", 4), ("D0310C", 5)],
    "lamp": [("D03135", 0), ("D03135", 2), ("D03135", 1)],
    "schakelaars": [
        ("D03103", 1), ("D03103", 0), ("D03130", 0), ("D03130", 100), ("D03180", 1), ("D03180", 0),
        ("D03115", 1), ("D03115", 0), ("D03134", 0), ("D03134", 1),
    ],
    "instellingen": [("D0312A", 0), ("D0312A", 1), ("D03110", 2), ("D03110", 0), ("D0312C", 7), ("D0312C", 4)],
    "display": [
        ("D03105", 0), ("D03105", 115), ("D03105", 123), ("D03105", 101),
        ("D03137", 2), ("D03137", 1), ("D03112", 1), ("D03112", 0),
    ],
}  # fmt: skip
GROUP_TITLES = {
    "aanuit": "Aan en uit",
    "standen": "Standen (slaap 17, medium 19, turbo 18, auto 0)",
    "snelheden": "Handmatige snelheden 1 tot 5",
    "lamp": "Lampfunctie (uit 0, sfeerlicht 2, luchtkwaliteit 1)",
    "schakelaars": "Kinderslot, pieptoon, Auto+, Allergie-slaap, sensoren in stand-by",
    "instellingen": "Weergegeven index, timer, drempel voor meldingen",
    "display": "Displayhelderheid, lichtscène, displayschakelaar",
}


async def write_matrix(ctx: Context, *, groups: list[str], wait: float = 8.0, pause: float = 2.0, assume_yes: bool = False) -> None:
    """Try every write the integration would use, and restore the settings."""
    dev = ctx.dev
    alive = await ensure_alive(ctx, dev, ctx.ep.new_token())
    if alive["frame"] is None or dev.latest is None:
        ctx.conclude("Geen statusbericht ontvangen; zonder beginwaarden wordt er niets geschreven.")
        return
    original = dict(dev.latest)
    ctx.say("Deze meting verandert instellingen van het apparaat en zet ze daarna terug. Het apparaat kan piepen, en de ventilator en het licht veranderen.")
    for group in groups:
        ctx.say(f"  {group}: {GROUP_TITLES[group]}")
    if not assume_yes and not await ctx.confirm("Doorgaan?"):
        ctx.conclude("Afgebroken; er is niets geschreven.")
        return
    outcomes: list[dict[str, Any]] = []
    touched: list[str] = []
    try:
        for group in groups:
            ctx.conclude(f"{GROUP_TITLES[group]}:")
            ctx.say(f"Groep: {GROUP_TITLES[group]}")
            if group != "aanuit" and (dev.latest or {}).get("D03102") == 0:
                ctx.say("Het apparaat staat uit; het wordt eerst aangezet.")
                await write_once(ctx, {"D03102": 1}, wait=wait)
                if "D03102" not in touched:
                    touched.append("D03102")
                await asyncio.sleep(pause)
            for key, value in WRITE_GROUPS[group]:
                if key not in (dev.latest or {}):
                    ctx.conclude(f"  {key}={value}: sleutel staat niet in de status, overgeslagen.")
                    outcomes.append({"values": {key: value}, "skipped": "missing_key", "group": group})
                    continue
                outcome = await write_once(ctx, {key: value}, wait=wait)
                outcome["group"] = group
                outcomes.append(outcome)
                if key not in touched:
                    touched.append(key)
                ctx.conclude("  " + describe_write(outcome))
                ctx.say(describe_write(outcome))
                await asyncio.sleep(pause)
    finally:
        ctx.say("Instellingen terugzetten.")
        not_restored: list[str] = []
        ordered = [k for k in touched if k not in ("D0310C", "D03102")] + [k for k in ("D0310C", "D03102") if k in touched]
        for key in ordered:
            target = original.get(key)
            current = (dev.latest or {}).get(key)
            if not isinstance(target, int) or current == target:
                continue
            if key == "D0310C" and target < 0:
                continue  # the mode reads negative while the device is off
            if key == "D0310C" and (dev.latest or {}).get("D03102") == 0:
                continue
            outcome = await write_once(ctx, {key: target}, wait=wait)
            if (dev.latest or {}).get(key) != target:
                not_restored.append(f"{key} (was {target}, is nu {(dev.latest or {}).get(key)})")
            await asyncio.sleep(pause)
        if not_restored:
            ctx.conclude("LET OP, niet teruggezet: " + ", ".join(not_restored) + ". Zet dit zo nodig in de app terug.")
        else:
            ctx.conclude("Alle gewijzigde instellingen zijn teruggezet.")
    ctx.result.update(writes=outcomes, not_restored=not_restored)


async def power_cycle(ctx: Context, *, off_timeout: float = 60.0, on_timeout: float = 300.0, old_wait: float = 60.0) -> None:
    """What survives a power cut, and how long does the device take to come back?"""
    dev = ctx.dev
    token = ctx.ep.new_token()
    alive = await ensure_alive(ctx, dev, token)
    ctx.conclude("Vooraf: " + describe_first(alive) + ".")
    before_sync = await dev.sync(timeout=ctx.timeout)
    runtime_before = (dev.latest or {}).get("Runtime")
    await ctx.pause_until_enter("Trek de stekker van de luchtreiniger uit het stopcontact.")
    loop = asyncio.get_running_loop()

    async def round_of_probes() -> dict[str, bool]:
        limit = min(1.0, ctx.timeout)
        return {
            "sync": (await dev.sync(timeout=limit)).ok,
            "info": (await dev.info(timeout=limit)).ok,
            "ping": (await dev.ping(timeout=limit)).ok,
        }

    misses, deadline = 0, loop.time() + off_timeout
    while misses < 3 and loop.time() < deadline:
        misses = 0 if any((await round_of_probes()).values()) else misses + 1
        await ctx.rest(1.0)
    if misses < 3:
        ctx.conclude("Het apparaat bleef antwoorden; de stekker is er kennelijk niet uit. Meting gestopt.")
        return
    ctx.say("Het apparaat antwoordt niet meer.")
    frames_at_off = len(dev.frames)
    await ctx.pause_until_enter("Steek de stekker er weer in. Zet het apparaat NIET zelf aan en druk nog nergens op.")
    powered = loop.time()
    first: dict[str, float | None] = {"sync": None, "info": None, "ping": None}
    deadline = powered + on_timeout
    while loop.time() < deadline and first["sync"] is None:
        results = await round_of_probes()
        for name, ok in results.items():
            if ok and first[name] is None:
                first[name] = round(loop.time() - powered, 1)
        await ctx.rest(1.0)
    for name, title in (("ping", "CoAP-ping"), ("info", "Info-aanvraag"), ("sync", "Sync")):
        ctx.conclude(f"{title} antwoordt weer na {_sec(first[name])} (gerekend vanaf Enter).")
    if first["sync"] is None:
        ctx.conclude(f"Geen sync-antwoord binnen {on_timeout:.0f} s; meting gestopt.")
        return
    after_sync = await dev.sync(timeout=ctx.timeout)
    ctx.conclude(f"Teller vóór {before_sync.data}, na {after_sync.data}.")
    spontaneous = await dev.wait_frame(since=frames_at_off, timeout=20.0 * ctx.pace)
    old_frames = [spontaneous] if spontaneous else (await stimulate(ctx, "oude abonnement na stroomonderbreking", wait=old_wait))[0]
    survived = bool(old_frames)
    ctx.conclude("Het oude abonnement " + ("levert nog na de stroomonderbreking." if survived else "is verdwenen; opnieuw abonneren is nodig."))
    again = await ensure_alive(ctx, dev, token, reason="opnieuw abonneren na stroomonderbreking")
    ctx.conclude("Opnieuw abonneren: " + describe_first(again) + ".")
    runtime_after = (dev.latest or {}).get("Runtime")
    ctx.conclude(f"Looptijd (Runtime) vóór {runtime_before} ms, na {runtime_after} ms.")
    ctx.result.update(first_answers=first, counter_before=before_sync.data, counter_after=after_sync.data, old_observation_survived=survived, runtime_before=runtime_before, runtime_after=runtime_after)


async def app_test(ctx: Context, *, baseline: float = 30.0, watch: float = 90.0, sync_interval: float = 10.0) -> None:
    """Do the Air+ app and this client disturb each other?"""
    dev = ctx.dev
    token = ctx.ep.new_token()
    alive = await ensure_alive(ctx, dev, token)
    ctx.conclude("Abonnement: " + describe_first(alive) + ".")
    syncs: list[Reply] = []

    async def watch_for(seconds: float) -> list[Frame]:
        start = len(dev.frames)
        loop = asyncio.get_running_loop()
        end = loop.time() + seconds
        while loop.time() < end:
            syncs.append(await dev.sync(timeout=ctx.timeout))
            await asyncio.sleep(min(sync_interval, max(0.0, end - loop.time())))
        return dev.frames[start:]

    ctx.say(f"Laat de app nog {baseline:.0f} seconden dicht.")
    base = await watch_for(baseline)
    await ctx.pause_until_enter("Open nu de Air+ app op een telefoon in hetzelfde wifi-netwerk en wacht tot het apparaat in beeld is.")
    opened = await watch_for(20.0 * ctx.pace)
    ctx.conclude(f"Zonder app: {len(base)} bericht(en) in {baseline:.0f} s. Na het openen van de app: {len(opened)} bericht(en) in 20 s.")
    ctx.say(f"Bedien het apparaat nu {watch:.0f} seconden via de app: zet het uit en aan en wissel van stand. Ondertussen gaat hier elke {sync_interval:.0f} s een sync uit.")
    used = await watch_for(watch)
    types = sorted({str(f.reported.get("StatusType")) for f in used if f.reported})
    ctx.conclude(f"Tijdens bediening via de app: {len(used)} bericht(en); StatusType {', '.join(types) or 'onbekend'}.")
    app_ok = await ctx.confirm("Reageerde het apparaat normaal op de app?")
    ctx.conclude("Bediening via de app tijdens onze syncs: " + ("normaal." if app_ok else "NIET normaal."))
    ctx.conclude(stats_text("Sync tijdens de proef", reply_stats(syncs)))
    await ctx.pause_until_enter("Sluit de app helemaal af.")
    after = (await stimulate(ctx, "na het sluiten van de app"))[0]
    ctx.conclude("Na het sluiten van de app levert ons abonnement " + ("nog steeds." if after else "NIET meer."))
    ctx.result.update(baseline_frames=len(base), on_open_frames=len(opened), during_use_frames=len(used), status_types=types, app_ok=app_ok, alive_after=bool(after), sync=reply_stats(syncs))

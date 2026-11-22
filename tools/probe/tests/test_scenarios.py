"""Every scenario against the simulated purifier, with its quirks switched on and off."""

import asyncio
import itertools
from collections.abc import Awaitable, Callable
from typing import Any

from fake_purifier import FakePurifier
from pureprotect_probe import scenarios
from pureprotect_probe.device import Purifier
from pureprotect_probe.endpoint import Endpoint
from pureprotect_probe.eventlog import EventLog

Body = Callable[[FakePurifier, scenarios.Context], Awaitable[None]]


def run(body: Body, *, answers: list[Any] | None = None, write_stimulus: bool = False, **quirks: Any) -> scenarios.Context:
    """Run a scenario body against a fresh simulated device and return the context."""
    holder: dict[str, scenarios.Context] = {}

    async def main() -> None:
        fake = await FakePurifier.start()
        for name, value in quirks.items():
            setattr(fake, name, value)
        log = EventLog(None, quiet=True)
        endpoint = await Endpoint.open(log, "A", peer_ip="127.0.0.1", bind_host="127.0.0.1")
        device = Purifier(endpoint, "127.0.0.1", fake.port)
        values = itertools.count(10)
        pending = list(answers or [])

        async def ask(prompt: str) -> str:
            answer = pending.pop(0) if pending else ""
            if callable(answer):
                answer = answer(fake) or ""
            return answer

        stimulus: scenarios.Stimulus = scenarios.CallbackStimulus(lambda: fake.change("D03221", next(values)))
        if write_stimulus:
            stimulus = scenarios.WriteStimulus()
        ctx = scenarios.Context(
            log=log, ep=endpoint, dev=device, host="127.0.0.1", port=fake.port, stimulus=stimulus, ask=ask,
            timeout=0.3, pace=0.01, direct_window=0.3, direct_seconds=0.25, stimulus_wait=0.4, first_frame_wait=1.0, quiet_needed=0.03,
        )  # fmt: skip
        holder["ctx"] = ctx
        try:
            await asyncio.wait_for(body(fake, ctx), 40)
        finally:
            endpoint.close()
            for extra in ctx.extra_endpoints:
                extra.close()
            fake.close()

    asyncio.run(main())
    return holder["ctx"]


def text(ctx: scenarios.Context) -> str:
    return "\n".join(ctx.summary)


def test_quick_on_a_device_that_answers_directly() -> None:
    ctx = run(lambda fake, ctx: scenarios.quick(ctx, duration=0.2, count=2))
    assert ctx.result["first_frame"]["direct"] is True
    assert ctx.result["refresh_same_direct"] == 2
    assert ctx.result["plain_get_answered"] is False
    assert ctx.result["device_id_matches"] is True
    assert ctx.result["info_con"] and ctx.result["sync_con"]
    assert "model AC3220/10" in text(ctx) and "firmware 0.2.3" in text(ctx)
    assert "gefragmenteerd" not in text(ctx)
    assert "Testkamer" not in text(ctx)


def test_quick_on_push_on_change_firmware() -> None:
    ctx = run(lambda fake, ctx: scenarios.quick(ctx, duration=0.2, count=2), answer_registration="on_change")
    assert ctx.result["first_frame"] == {"latency": ctx.result["first_frame"]["latency"], "direct": False, "needed_stimulus": True}
    assert ctx.result["refresh_same_direct"] == 0
    assert "pas na een verandering" in text(ctx)


def test_quick_when_nothing_answers() -> None:
    ctx = run(lambda fake, ctx: scenarios.quick(ctx, duration=0.1, count=2), silent=True)
    assert ctx.result["stats"]["sync"]["answered"] == 0
    assert "geen statusbericht ontvangen" in text(ctx)


def test_probe_series() -> None:
    ctx = run(lambda fake, ctx: scenarios.probes(ctx, "sync", count=4, interval=0.01))
    assert ctx.result["stats"] == {**ctx.result["stats"], "sent": 4, "answered": 4}
    ctx = run(lambda fake, ctx: scenarios.probes(ctx, "info", count=3, interval=0.01), info_enabled=False)
    assert ctx.result["stats"]["answered"] == 0 and ctx.result["stats"]["longest_miss_run"] == 3


def test_discover_counts_direct_replies() -> None:
    ctx = run(lambda fake, ctx: scenarios.discover(ctx, rounds=2, broadcast="127.255.255.255", listen=5.0))
    direct = next(v for k, v in ctx.result["replies"].items() if k.startswith("rechtstreeks"))
    assert direct == {"127.0.0.1": 2}


def test_observe_with_new_token_refresh() -> None:
    async def body(fake: FakePurifier, ctx: scenarios.Context) -> None:
        async def changes() -> None:
            for value in range(20, 26):
                await asyncio.sleep(0.25)
                fake.change("D03221", value)

        task = asyncio.create_task(changes())
        await scenarios.observe(ctx, duration=2.0, refresh="nieuw", interval=0.6)
        await task

    ctx = run(body)
    assert ctx.result["frames"] >= 6
    assert len(ctx.result["per_token"]) >= 2
    assert all(r["answered"] for r in ctx.result["refreshes"])
    assert "Volgnummers lopen steeds op." in text(ctx)


def test_liveness_compares_probes() -> None:
    ctx = run(lambda fake, ctx: scenarios.liveness(ctx, duration=1.0, interval=0.3), ping_enabled=False)
    stats = ctx.result["stats"]
    assert stats["sync"]["answered"] == stats["sync"]["sent"] > 0
    assert stats["ping"]["answered"] == 0
    assert "geen periode van meer dan 2 minuten zonder wijziging" in text(ctx)


def test_lapse_detected_and_recovered_with_same_token() -> None:
    ctx = run(lambda fake, ctx: scenarios.lapse(ctx, checkpoints=(0.3, 0.9, 1.5), recent=0.05), lapse_after=0.6)
    assert ctx.result["dead_at"] == 0.9
    assert ctx.result["recovery"] == {"same_token": True}
    assert "leverde niet meer" in text(ctx)


def test_no_lapse() -> None:
    ctx = run(lambda fake, ctx: scenarios.lapse(ctx, checkpoints=(0.2, 0.5), recent=0.05))
    assert ctx.result["dead_at"] is None
    assert [c["alive"] for c in ctx.result["checkpoints"]] == [True, True]


def test_refresh_on_a_device_that_keeps_both_tokens() -> None:
    ctx = run(lambda fake, ctx: scenarios.refresh_test(ctx, pause=0.05, repeats=2))
    assert [r["answered"] for r in ctx.result["same"]] == [True, True]
    assert ctx.result["after_new"] == {"old": 1, "new": 1}
    assert "bedient beide abonnementen" in text(ctx)


def test_refresh_on_a_device_with_one_observer_per_ip() -> None:
    ctx = run(lambda fake, ctx: scenarios.refresh_test(ctx, pause=0.05, repeats=1), single_observer_per_ip=True, answer_registration="on_change")
    assert [r["answered"] for r in ctx.result["same"]] == [False]
    assert ctx.result["after_same"] == 1
    assert ctx.result["after_new"] == {"old": 0, "new": 1}
    assert "heeft het oude vervangen" in text(ctx)


def test_second_client_with_shared_counter_and_two_observers() -> None:
    ctx = run(lambda fake, ctx: scenarios.second_client(ctx))
    assert ctx.result["frames"] == {"a": 1, "b": 1}
    assert ctx.result["counter"] == {"bogus_counter": "failed", "a_after_b_synced": "failed", "b_own_counter": "success"}
    assert "delen één teller" in text(ctx)


def test_second_client_evicts_first_and_has_own_counter() -> None:
    ctx = run(lambda fake, ctx: scenarios.second_client(ctx), single_observer_per_ip=True, global_counter=False)
    assert ctx.result["frames"] == {"a": 0, "b": 1}
    assert ctx.result["counter"] == {"bogus_counter": "failed", "a_after_b_synced": "success", "b_own_counter": "success"}
    assert "één abonnee per IP-adres" in text(ctx) and "eigen teller" in text(ctx)


def test_second_client_when_the_counter_is_not_checked() -> None:
    ctx = run(lambda fake, ctx: scenarios.second_client(ctx), strict_counter=False)
    assert ctx.result["counter"]["bogus_counter"] == "success"
    assert "niet streng gecontroleerd" in text(ctx)


def test_deregister_and_reset_honoured() -> None:
    ctx = run(lambda fake, ctx: scenarios.deregister_test(ctx))
    assert ctx.result == {"deregister_honoured": True, "reset_honoured": True}


def test_deregister_and_reset_ignored() -> None:
    ctx = run(lambda fake, ctx: scenarios.deregister_test(ctx), honour_deregister=False, honour_rst=False)
    assert ctx.result == {"deregister_honoured": False, "reset_honoured": False}


def test_single_write_is_echoed() -> None:
    ctx = run(lambda fake, ctx: scenarios.write(ctx, {"D0310C": 5}, wait=1.0))
    assert ctx.result["reply"] == "success" and ctx.result["echo_s"] is not None
    assert ctx.result["status_type"] == "control" and ctx.result["fan_level"] == 18


def test_single_write_to_a_readonly_key() -> None:
    # The simulator answers the follow-up registration, so the old value is seen again.
    ctx = run(lambda fake, ctx: scenarios.write(ctx, {"D03105": 0}, wait=0.3))
    assert ctx.result["reply"] == "success" and ctx.result["verdict"] == "ignored"
    assert "GENEGEERD: een latere status toont D03105=101" in text(ctx)


def test_single_write_without_any_status_is_unknown_not_ignored() -> None:
    async def body(fake: FakePurifier, ctx: scenarios.Context) -> None:
        await scenarios.ensure_alive(ctx, ctx.dev, ctx.ep.new_token())
        ctx.result.update(await scenarios.write_once(ctx, {"D03105": 0}, wait=0.3))

    ctx = run(body, answer_registration="on_change")
    assert ctx.result["verdict"] == "unknown"
    assert "onbekend of de opdracht is uitgevoerd" in scenarios.describe_write(ctx.result)


def test_lost_notification_is_recovered_by_a_fresh_registration() -> None:
    async def body(fake: FakePurifier, ctx: scenarios.Context) -> None:
        await scenarios.ensure_alive(ctx, ctx.dev, ctx.ep.new_token())
        fake.drop_next_notifications = 1
        ctx.result.update(await scenarios.write_once(ctx, {"D03135": 0}, wait=0.3))

    ctx = run(body)
    assert ctx.result["verdict"] == "confirmed" and ctx.result["echo_after_refresh"] is True


def test_refused_write() -> None:
    async def body(fake: FakePurifier, ctx: scenarios.Context) -> None:
        await scenarios.ensure_alive(ctx, ctx.dev, ctx.ep.new_token())
        await ctx.dev.sync()
        ctx.dev.counter = "00000000"
        ctx.result.update(await scenarios.write_once(ctx, {"D03135": 0}, wait=0.3, sync_first=False))

    ctx = run(body)
    assert ctx.result["verdict"] == "refused" and "geweigerd (antwoord 'failed')" in scenarios.describe_write(ctx.result)


def test_write_matrix_restores_everything() -> None:
    before: dict[str, Any] = {}

    async def body(fake: FakePurifier, ctx: scenarios.Context) -> None:
        fake.state["D0310C"] = 19
        fake.state["D03135"] = 2
        before.update(fake.state)
        await scenarios.write_matrix(ctx, groups=list(scenarios.WRITE_GROUPS), wait=0.3, pause=0.0, assume_yes=True)
        after = {k: v for k, v in fake.state.items() if k not in ("D0310D",)}
        assert after == {k: v for k, v in before.items() if k not in ("D0310D",)}

    ctx = run(body)
    writes = {(tuple(w["values"].items())[0]): w for w in ctx.result["writes"] if "skipped" not in w}
    assert writes[("D0310C", 5)]["fan_level"] == 18 and writes[("D0310C", 5)]["echo_s"] is not None
    assert writes[("D03105", 0)]["verdict"] == "ignored"  # read-only in the simulator
    assert writes[("D03130", 100)]["reply"] == "success"
    assert ctx.result["writes"][0]["group"] == "zelfde" and ctx.result["writes"][0]["verdict"] == "same"
    assert ctx.result["not_restored"] == [] and ctx.result["restore_unconfirmed"] == []
    assert "Alle gewijzigde instellingen zijn teruggezet en bevestigd." in text(ctx)
    assert any(w.get("skipped") == "missing_key" for w in ctx.result["writes"])  # D03112 is absent


def test_write_matrix_restores_when_the_last_notification_was_lost() -> None:
    # On push-on-change firmware the tool never sees that the lamp write worked.
    async def body(fake: FakePurifier, ctx: scenarios.Context) -> None:
        await scenarios.ensure_alive(ctx, ctx.dev, ctx.ep.new_token())
        fake.answer_registration = "on_change"
        original = scenarios.write_once

        async def lossy(ctx2: scenarios.Context, values: dict[str, int], **kwargs: Any) -> dict[str, Any]:
            if values == {"D03135": 0}:
                fake.drop_next_notifications = 1
            return await original(ctx2, values, **kwargs)

        scenarios.write_once = lossy  # type: ignore[assignment]
        try:
            await scenarios.write_matrix(ctx, groups=["lamp"], wait=0.3, pause=0.0, assume_yes=True)
        finally:
            scenarios.write_once = original  # type: ignore[assignment]
        assert fake.state["D03135"] == 1

    ctx = run(body)
    assert ctx.result["writes"][0]["verdict"] == "unknown"
    assert ctx.result["not_restored"] == []


def test_write_matrix_restores_after_ctrl_c() -> None:
    async def body(fake: FakePurifier, ctx: scenarios.Context) -> None:
        task = asyncio.create_task(scenarios.write_matrix(ctx, groups=["snelheden", "lamp"], wait=0.3, pause=0.2, assume_yes=True))
        while fake.state["D0310C"] != 2:
            await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert fake.state["D0310C"] == 0 and fake.state["D03135"] == 1

    ctx = run(body)
    assert "teruggezet en bevestigd" in text(ctx)


def test_restore_order() -> None:
    touched = ["D03102", "D0310C", "D03135"]
    assert scenarios.restore_order(touched, {"D03102": 1, "D0310C": 19}) == ["D03102", "D03135", "D0310C"]
    assert scenarios.restore_order(touched, {"D03102": 0, "D0310C": -16}) == ["D03135", "D03102"]


def test_missed_button_press_is_asked_about_and_retried() -> None:
    presses = {"count": 0}

    class Forgetful(scenarios.ButtonStimulus):
        async def trigger(self, ctx: scenarios.Context, reason: str) -> bool:
            presses["count"] += 1
            if presses["count"] >= 2:
                ctx.fake.change("D03221", 50)  # type: ignore[attr-defined]
            return True

    async def body(fake: FakePurifier, ctx: scenarios.Context) -> None:
        await scenarios.ensure_alive(ctx, ctx.dev, ctx.ep.new_token())
        ctx.fake = fake  # type: ignore[attr-defined]
        ctx.stimulus = Forgetful()
        frames = (await scenarios.stimulate(ctx, "proef"))[0]
        assert len(frames) == 1 and presses["count"] == 2

    run(body, answers=["n"])


def test_blockwise_frames_are_named_as_such() -> None:
    from pureprotect_probe.coap import CONTENT, OPT_BLOCK2, Message, MType
    from pureprotect_probe.endpoint import Received

    async def body(fake: FakePurifier, ctx: scenarios.Context) -> None:
        token = ctx.ep.new_token()
        ctx.dev.register(token)
        await ctx.dev.wait_frame(since=0, timeout=1)
        block = Message(MType.NON, CONTENT, 9, token, [(OPT_BLOCK2, b"\x0e")], b"A" * 1024)
        ctx.dev._frame_received(Received(ctx.log.now(), ("127.0.0.1", fake.port), block, 1040))
        assert ctx.dev.frames[-1].decode == "err:blockwise"
        scenarios.warn_blockwise(ctx, ctx.dev)

    ctx = run(body)
    assert "Block2" in text(ctx)


def test_write_matrix_needs_confirmation() -> None:
    ctx = run(lambda fake, ctx: scenarios.write_matrix(ctx, groups=["aanuit"], wait=0.3, pause=0.0), answers=["n"])
    assert "er is niets geschreven" in text(ctx)
    assert "writes" not in ctx.result


def test_write_matrix_turns_the_device_on_first_and_off_again() -> None:
    async def body(fake: FakePurifier, ctx: scenarios.Context) -> None:
        fake.state["D03102"] = 0
        fake.state["D0310C"] = -16
        await scenarios.write_matrix(ctx, groups=["snelheden"], wait=0.3, pause=0.0, assume_yes=True)
        assert fake.state["D03102"] == 0

    run(body)


def test_power_cycle() -> None:
    def unplug(fake: FakePurifier) -> None:
        fake.silent = True

    def plug_in(fake: FakePurifier) -> None:
        fake.reboot()
        fake.silent = False

    ctx = run(lambda fake, ctx: scenarios.power_cycle(ctx, off_timeout=5.0, on_timeout=5.0, old_wait=0.4), answers=[unplug, plug_in])
    assert ctx.result["old_observation_survived"] is False
    assert ctx.result["first_answers"]["sync"] is not None
    assert ctx.result["counter_before"] != ctx.result["counter_after"]
    assert ctx.result["runtime_after"] < ctx.result["runtime_before"] + 5000
    assert "is verdwenen" in text(ctx)


def test_power_cycle_when_the_plug_stays_in() -> None:
    ctx = run(lambda fake, ctx: scenarios.power_cycle(ctx, off_timeout=0.5, on_timeout=1.0))
    assert "bleef antwoorden" in text(ctx)


def test_app_scenario() -> None:
    def use_app(fake: FakePurifier) -> None:
        fake.change("D03102", 0, status_type="control")

    ctx = run(lambda fake, ctx: scenarios.app_test(ctx, baseline=0.2, watch=0.3, sync_interval=0.1), answers=[use_app, "j", ""])
    assert ctx.result["on_open_frames"] == 1 and ctx.result["app_ok"] is True and ctx.result["alive_after"] is True
    assert ctx.result["sync"]["answered"] == ctx.result["sync"]["sent"]


def test_write_stimulus_changes_and_restores() -> None:
    async def body(fake: FakePurifier, ctx: scenarios.Context) -> None:
        alive = await scenarios.ensure_alive(ctx, ctx.dev, ctx.ep.new_token())
        assert alive["needed_stimulus"] and alive["frame"] is not None
        await asyncio.sleep(0.2)
        assert fake.state["D03103"] == 0

    run(body, write_stimulus=True, answer_registration="on_change")

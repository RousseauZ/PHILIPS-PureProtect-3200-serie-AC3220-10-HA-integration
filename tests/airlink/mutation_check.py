"""Check that the airlink tests notice when a design rule is broken.

Each mutant below breaks one rule in a copy of the package; the suite must
fail on every one of them. A mutant that survives names a rule that the code
may follow today and that no test would miss tomorrow. Not collected by
pytest (it takes minutes); run it by hand after changing the session:

    python3 tests/airlink/mutation_check.py            # all mutants
    python3 tests/airlink/mutation_check.py offline    # those with "offline" in the name

Nothing in the repository is changed: the mutants live in a temporary
directory. When the code changes under a mutant, the script says so instead
of silently testing nothing.
"""

from __future__ import annotations

import concurrent.futures
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PACKAGE = "custom_components/philips_pureprotect/airlink"
SESSION = f"{PACKAGE}/session.py"
TRANSPORT = f"{PACKAGE}/transport.py"

# name: (file, rule, text to replace, replacement)
MUTANTS: dict[str, tuple[str, str, str, str]] = {
    # -- liveness and recovery ------------------------------------------------
    "suspect_retries_at_the_idle_interval": (
        SESSION,
        "rule 2",
        "            due = self._last_probe + opts.probe_retry\n",
        "            due = self._last_probe + opts.probe_idle\n",
    ),
    "offline_backoff_starts_over": (
        SESSION,
        "rule 3",
        "backoff[min(self._offline_attempt, len(backoff) - 1)]",
        "backoff[self._offline_attempt % len(backoff)]",
    ),
    "no_refresh_or_identity_check_after_suspect": (
        SESSION,
        "rules 3 and 4",
        (
            "        if not self._started or self._state not in (SessionState.OFFLINE, SessionState.SUSPECT):\n"
            "            return\n"
        ),
        (
            "        if not self._started or self._state not in (SessionState.OFFLINE, SessionState.SUSPECT):\n"
            "            return\n"
            "        if self._state is SessionState.SUSPECT:\n"
            "            self._set_state(SessionState.LIVE if self._status_is_live else SessionState.REACHABLE)\n"
            "            return\n"
        ),
    ),
    "contact_after_a_miss_keeps_its_token": (
        SESSION,
        "rule 4, measurement 8",
        "        self._request_refresh(force=after_misses, afresh=after_misses)\n",
        "        self._request_refresh(force=after_misses)\n",
    ),
    "name_not_looked_up_again_while_offline": (
        SESSION,
        "rule 3",
        "        if was_offline and self._offline_attempt:\n",
        "        if False:\n",
    ),
    "resolver_error_reaches_the_caller": (
        TRANSPORT,
        "rule 7",
        "        except UnicodeError as err:\n",
        "        except KeyError as err:\n",
    ),
    "start_supervises_a_stopped_session": (
        SESSION,
        "rule 7",
        "        if self._stopped:\n            return  # stop() ran while no socket could be opened",
        "        if False:\n            return  # stop() ran while no socket could be opened",
    ),
    # -- observation and frames -----------------------------------------------
    "no_refresh_after_runtime_fall": (
        SESSION,
        "rule 4",
        "            self._counters.device_restarts += 1\n            self._request_refresh()\n",
        "            self._counters.device_restarts += 1\n",
    ),
    "missed_change_keeps_its_token": (
        SESSION,
        "rules 4 and 5, measurement 8",
        "                self._request_refresh(afresh=True)\n",
        "                self._request_refresh()\n",
    ),
    "frames_filtered_on_message_id": (
        SESSION,
        "rule 5",
        (
            "    def _handle_stream(self, observation: _Observation, msg: Message) -> None:\n"
            "        if self._stopped:\n            return\n"
        ),
        (
            "    def _handle_stream(self, observation: _Observation, msg: Message) -> None:\n"
            "        if self._stopped:\n            return\n"
            "        if getattr(self, '_seen_mid', -1) >= msg.mid:\n            return\n"
            "        self._seen_mid = msg.mid\n"
        ),
    ),
    "block_wise_frame_accepted": (
        SESSION,
        "rule 5",
        "    if block is not None and (block[0] > 0 or block[1]):\n",
        "    if block is not None and False:\n",
    ),
    "lower_runtime_is_stale_however_late": (
        SESSION,
        "rule 5",
        "            and (time.monotonic() - self._last_runtime_mono) * 1000 < window\n",
        "",
    ),
    "info_answer_without_ids_accepted": (
        SESSION,
        "report 6.5",
        (
            "    if not isinstance(device_id, str) or not device_id or not isinstance(product_id, str) or not product_id:\n"
            "        raise _OtherDeviceError\n"
        ),
        (
            "    if not isinstance(device_id, str) or not isinstance(product_id, str):\n"
            "        device_id = product_id = 'unknown'\n"
        ),
    ),
    "info_answer_without_ids_not_flagged": (
        SESSION,
        "report 6.5, measurement 11",
        "                self._identity = None\n                self._judge_device_id(None)\n",
        "                self._identity = None\n",
    ),
    # -- commands ---------------------------------------------------------------
    "write_budget_excludes_the_lock_wait": (
        SESSION,
        "rule 6",
        "            async with asyncio.timeout_at(deadline), self._exchange_lock:\n                for _ in",
        "            async with self._exchange_lock, asyncio.timeout(opts.write_budget):\n                for _ in",
    ),
    "sync_probe_without_the_exchange_lock": (
        SESSION,
        "rule 6",
        "                async with asyncio.timeout(opts.probe_timeout), self._exchange_lock:\n",
        "                async with asyncio.timeout(opts.probe_timeout):\n",
    ),
    "already_current_on_a_restored_status": (
        SESSION,
        "rule 6",
        "        if shown and (self._status_is_live or write.switches_off):\n",
        "        if shown:\n",
    ),
    "off_refused_before_looking_at_what_holds": (
        SESSION,
        "report 6.4 item 3",
        (
            "        if shown and (self._status_is_live or write.switches_off):\n"
            "            return True\n"
            "        if status.get(POWER_KEY) == 0 and desired.get(POWER_KEY) != 1:\n"
            '            raise DeviceOffError("the device is off and would discard this", write.asked)\n'
            "        return False\n"
        ),
        (
            "        if status.get(POWER_KEY) == 0 and desired.get(POWER_KEY) != 1:\n"
            '            raise DeviceOffError("the device is off and would discard this", write.asked)\n'
            "        return shown and (self._status_is_live or write.switches_off)\n"
        ),
    ),
    "older_write_does_not_yield_to_a_newer_one": (
        SESSION,
        "report 6.4 item 6",
        "        if not taken:\n            return\n        for key in taken:\n",
        "        if True:\n            return\n        for key in taken:\n",
    ),
    "setting_not_held_for_a_power_change": (
        SESSION,
        "report 6.4 item 6, measurement 5",
        "                while write.desired and self._power_in_transition(write):\n",
        "                while False:\n",
    ),
    "frame_does_not_end_the_attempts": (
        SESSION,
        "rule 6",
        "                    if write.attempts and waiter.matched:\n",
        "                    if False:\n",
    ),
    "silent_switch_off_is_not_confirmed": (
        SESSION,
        "measurement 5",
        "                if write.switches_off and not waiter.mismatched:\n",
        "                if False:\n",
    ),
    "switch_off_assumed_against_a_frame": (
        SESSION,
        "measurement 5",
        "                    if not waiter.settled and not waiter.mismatched:\n",
        "                    if not waiter.settled:\n",
    ),
}


def run(name: str, base: Path) -> tuple[str, bool, str]:
    target, rule, old, new = MUTANTS[name]
    copy = base / name
    for sub in (PACKAGE, "tests/airlink", "tools/probe/pureprotect_probe"):
        shutil.copytree(ROOT / sub, copy / sub, ignore=shutil.ignore_patterns("__pycache__"))
    source = copy / target
    text = source.read_text()
    if text.count(old) != 1:
        return f"{name} ({rule})", False, "the code changed under this mutant: it no longer applies"
    source.write_text(text.replace(old, new))
    done = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", "tests/airlink"],
        cwd=copy,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    lines = done.stdout.strip().splitlines()
    failed = [line for line in lines if line.startswith("FAILED")]
    return f"{name} ({rule})", done.returncode != 0, failed[0][:150] if failed else (lines[-1] if lines else "")


def main() -> int:
    wanted = [name for name in MUTANTS if all(word in name for word in sys.argv[1:])]
    survivors = 0
    with tempfile.TemporaryDirectory() as tmp, concurrent.futures.ThreadPoolExecutor(4) as pool:
        for label, killed, detail in pool.map(lambda name: run(name, Path(tmp)), wanted):
            survivors += not killed
            print(f"{'killed  ' if killed else 'SURVIVED'} {label}: {detail}", flush=True)
    print(f"{survivors} of {len(wanted)} mutants survived")
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())

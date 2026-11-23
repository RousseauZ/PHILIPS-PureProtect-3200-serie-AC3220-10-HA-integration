# 03 - Critical review: tinkerologie/ha-philips-airpurifier + philips-airctrl

Research date: 2026-11-22. Angle: is the newer integration a solution for an AC3220/10 owner, and what
should a new integration reuse or avoid?

Code paths are relative to `scratchpad/src/`. Short names used below:

- **INT** = `tinkerologie_ha-philips-airpurifier/custom_components/philips_airpurifier/`
- **LIB** = `tinkerologie_philips-airctrl/src/philips_airctrl/`
- **K09** = `kongo09_philips-airpurifier-coap/custom_components/philips_airpurifier_coap/`
- **AIOCOAP** = aiocoap 0.4.17 sdist, downloaded for reading only to `scratchpad/web03/aiocoap_src/`

Evidence labels: **[V-code]** read in source, **[V-web]** read on a primary web page (GitHub issue, HA
docs, PyPI) through WebFetch (a small model summarises the page, so numbers were cross-checked with a
second fetch where they matter), **[hearsay]** claims by issue reporters, **[inference]** my reasoning.

---

## 0. Bottom line

1. The integration is a 2025 copy of kongo09's integration, heavily refactored in 2026. It is very
   actively maintained, but it is **not** in the HACS default list and it does not solve the
   reliability problem for the AC22xx/AC32xx firmware family. On that family the current release
   (v2026.11.1, 2026-11-13) is reported to be clearly **worse** than kongo09's.
2. The cause is a design decision that is visible in code: the library renews the CoAP Observe
   registration every 60 s and treats one unanswered renewal (10 s) as a dead device; the coordinator
   then tears the session down and requires a fresh status read (30 s) to succeed before it calls the
   device available. Reporters with AC2210 and AC2220 (same model family as the AC3220) show that this
   firmware often does not answer a new Observe registration while it is idle.
3. The AC3220 model definition was inherited from kongo09 with a wrong key for the preferred-index
   select, and both integration actions are no-ops on Gen3 devices.
4. Recommendation: (d) write a small focused integration with its own session layer, reuse only the
   protocol primitives, and upstream the small fixes (b). Use the tinkerologie integration first as a
   measuring instrument, because its connection logging and diagnostics are the best available.

---

## 1. Project status

### 1.1 Identity of the two clones

`tinkerologie_ha-philips-airpurifier` and `ruaan-deysel_ha-philips-airpurifier` are the same
repository: both have HEAD `550c88adc5cb54e9a43a02f5aea9edd0f257e4eb` (2026-11-19, "chore(deps): bump
philips-airctrl from 1.5.0 to 1.5.1 (#216)"). The `ruaan-deysel/...` URL is the old name of the same
repo. [V-code, `git log` in both clones]

I cloned the full history separately to `tinkerologie_ha-philips-airpurifier_full` (337 commits).

### 1.2 Facts

| Item | Value | Evidence |
|---|---|---|
| Domain | `philips_airpurifier` (kongo09: `philips_airpurifier_coap`) | INT `manifest.json` |
| Maintainer | Ruaan Deysel (`@ruaan-deysel`, sole code owner), org `tinkerologie` | `manifest.json` codeowners; `git shortlog`: 202 of 337 commits, dependabot 97, then Martin 7, "Claude" 7, Brian Ramsey 5, copilot-swe-agent 5 |
| Origin | Not a GitHub fork, but the first commit `d61bb1b` (2025-06-06) is a copy of kongo09's integration: directory `custom_components/philips_airpurifier_coap/`, README with kongo09 release badges and kongo09's "Word of Caution" text | `git show d61bb1b` |
| Age | First commit 2025-06-06; two tags in June 2025 (v0.26.0, v0.27.0); no commits until 2026-02; rewrite in `11c5183` (2026-02-15) | `git log`, tags |
| Release cadence | 21 tags. 2026: Feb 1, Apr 2, May 1, Jun 4, Aug 1, Sep 3, Oct 5, Nov 2. Latest v2026.11.1 on 2026-11-13 | `git for-each-ref refs/tags` |
| Versioning | CalVer `YYYY.MM.PATCH` | `CHANGELOG.md` header |
| HACS status | **Custom repository.** `hacs/default` `integration` list contains `kongo09/philips-airpurifier-coap` and three other tinkerologie repos, but not this one | https://raw.githubusercontent.com/hacs/default/master/integration (fetched 2026-11-22) |
| HA Marketplace | HA 2026.11 replaced HACS with a built-in Marketplace; HACS installs are migrated automatically; custom repos need `hacs.json`. The README has a Marketplace badge and says "Search for Philips AirPurifier". Whether the repo is in the Marketplace catalog is **not verified** | https://www.home-assistant.io/integrations/marketplace/ [V-web]; README lines 20-37 |
| Minimum HA | 2026.9.0 (`hacs.json`), Python >= 3.14.2 (`pyproject.toml`); code uses `except A, B:` without parentheses (INT `config_flow.py:210`, `event.py:83`) | files |
| Licence | Apache-2.0 since 2026-10-12 (`e711591`); bundled icon code MIT (Thomas Loven). kongo09's `pyproject.toml` says MIT | `LICENSE`, `LICENSE.txt` |
| Library | `philips-airctrl` on PyPI: 1.0.0 (2026-02-13), 1.1.0 (05-29), 1.2.0 (07-01), 1.3.0 (10-19), 1.4.0 (10-28), 1.5.0 (11-12), 1.5.1 (11-15). Apache-2.0, fork of betaboon's aioairctrl | https://pypi.org/pypi/philips-airctrl/json |
| Released pin | v2026.11.1 `manifest.json` requires `philips-airctrl==1.5.0`; `main` moved only `pyproject.toml` to 1.5.1 (open issue #217) | `git show v2026.11.1:.../manifest.json`; issue #217 [V-web] |
| GitHub numbers | 81 stars, 22 forks, 6 open issues, 40 closed issues, 0 open PRs, 171 closed PRs | repo page [V-web] |
| Tests | 10,939 lines in `tests/`, 503 test functions, `fail_under = 100` | `pyproject.toml`, `grep -c` |
| Size | 7,165 lines Python in the integration (`device_models.py` 1,759, `const.py` 1,100, `coordinator.py` 725, `repairs.py` 545, `config_flow.py` 475) | `wc -l` |

### 1.3 Relation to kongo09 and migration path

- Same protocol, same datapoint keys, same model tables. `device_models.py` still carries comments like
  "MRO: PhilipsAC3420 -> PhilipsAC0950 -> PhilipsNew2GenericFan", which are kongo09 class names.
- The 2026-02 rewrite replaced kongo09's class hierarchy (`philips.py`, 2,282 lines) by data
  (`DeviceModelConfig`), replaced the hand-written coordinator by HA's `DataUpdateCoordinator`, and
  moved from `aioairctrl` to `philips-airctrl`.
- **No migration path.** Different domain, no `async_migrate_entry`, no import flow
  (`grep async_migrate` finds only AI instruction files). A user must remove the kongo09 entry and add
  the device again. Unique IDs have the same shape (`{model}-{device_id}-{key}`) but live under another
  platform, so entities are created fresh.
- Both must not run against the same device: the code assumes one CoAP client per device (INT
  `client.py:171-175`, `config_flow.py:187-191`, README troubleshooting table).

### 1.4 Test coverage and quality scale: what the claims are worth

`quality_scale.yaml` marks everything in Bronze, Silver and Gold as done except five documentation rules
(`docs-actions`, `docs-removal-instructions`, `docs-configuration-parameters`, `docs-examples`,
`docs-use-cases`) and Platinum `strict-typing` (todo). `reauthentication-flow`, `dynamic-devices`,
`stale-devices`, `inject-websession` are exempt. It claims
"test-coverage: 100% line coverage, enforced by the test configuration".

That 100 % is reached with 33 `# pragma: no cover` markers. Excluded from coverage: [V-code]

- the whole fan entity class: INT `fan.py:46` `class PhilipsFan(...):  # pragma: no cover`
- `diagnostics.py:58` (the diagnostics function)
- `repairs.py:437` `async_check_integration_health` and four repair-fix steps (`:104`, `:172`, `:302`, `:365`)
- `light.py:111` `brightness` and `light.py:140` `async_turn_on`
- `climate.py` 7 markers, `humidifier.py` 4

There are still tests for the fan (`tests/test_fan.py`, 29 tests), but the number "100 %" does not
cover the main entity. There is no test fixture or test for AC3210/AC3220/AC3221 (`grep -rn AC3220`
finds only `const.py`, `device_models.py`, `README.md`).

The repository is strongly process driven: 12 workflows, `AGENTS.md` (648 lines), `CLAUDE.md`,
`CODEX.md`, `GEMINI.md`, 17 `.github/instructions/*.md`, a governance bot, and a CodeRabbit "coding
plan" on every issue. `.github/copilot-instructions.md:9` still says
"Domain: `philips_airpurifier_coap` (use this in all user-facing text)", which is wrong for this repo.

### 1.5 CHANGELOG entries about reliability (quoted)

| Version | Date | Entry |
|---|---|---|
| 2026.6.1 | 2026-06-11 | "DHCP discovery now matches already configured devices by MAC address (or host) **before** opening a CoAP connection (#8)". "A purifier that received a new IP address from the router stayed unavailable forever, because the discovery flow had to connect to the device to identify it" |
| 2026.6.2 | 2026-06-14 | "Coordinator reconnect handling now uses exponential backoff retries (5 seconds up to a 60-second cap)". "Devices are no longer marked unavailable immediately when the CoAP observation stream ends; unavailable is now set only when reconnect attempts actually fail" (#51) |
| 2026.8.0 | 2026-08-30 | "Reconnect recovery can no longer wedge indefinitely when a CoAP status read stalls during reconnect. Coordinator CoAP calls are now time-bounded and stale reconnect tasks are treated as wedged" (#101). Added the per-device watchdog on/off option (#100) |
| 2026.9.1 | 2026-09-28 | Status nudge for HU1509/HU1510/HU4209 ("Newer firmware on some of these humidifiers never answers a plain status read and only pushes updates on a real state change"); watchdog re-enabled for nudge devices with 30 min; missed-package threshold configurable (#92) |
| 2026.10.1 | 2026-10-19 | AMF870 with `AWS_Philips_AIR_Combo@86` handled as push-only (#132) |
| 2026.10.3 | 2026-10-28 | "Devices no longer go unavailable every few minutes because the push subscription lapses (#172): `philips-airctrl` 1.4.0 renews the CoAP Observe registration every Max-Age seconds instead of registering it once. The watchdog stays as a safety net." Also the `connection` diagnostics section and stage logging |
| 2026.11.0 | 2026-11-10 | CX5120 firmware 0.4.9 (`AWS_Philips_AIR@86.1`) gets a status nudge (#203); nudge writes time-bounded (#197) |
| 2026.11.1 | 2026-11-13 | "CX5120 heaters with firmware 0.4.9 never answer the observation renewal, so the 60 s renewal of philips-airctrl turned into a reconnect and a display nudge every minute (a beep each time) until the device's CoAP stack stalled. Push-only models now renew the observation only at the nudge watchdog interval (30 min)." Also: one teardown per CoAP context (#198) |

Library CHANGELOG, same period:

- 1.4.0 (2026-10-28): "`observe_status()` no longer goes silent after a few minutes while the device
  stays reachable (#34). It now renews its Observe registration every Max-Age seconds ... A renewal that
  fails raises `NetworkError`, or `TimeoutError` after 10 seconds, so callers can reconnect."
- 1.5.0 (2026-11-12): idempotent `shutdown()` (#36).
- 1.5.1 (2026-11-15): undecryptable pushes are skipped instead of ending the stream (#44). Not yet in a
  released integration version (issue #217).

The README itself warns (line 18): "Some firmware versions disable local CoAP or stop responding to it
intermittently. If local control is a purchase requirement, verify the firmware or buy from a seller
with a return policy."

---

## 2. Architecture walkthrough

### 2.1 `__init__.py` (170 lines)

- `async_setup` registers the frontend bundle and the two actions once (`:58-63`).
- `async_setup_entry` (`:66-141`): `async_create_client(host, timeout=25)` -> `ConfigEntryNotReady` on
  any error; builds the coordinator; `await coordinator.async_first_refresh_and_observe()`; forwards 10
  platforms (binary_sensor, climate, event, fan, humidifier, light, number, select, sensor, switch).
- `:108-109`: when the watchdog option is off and `entry.data["status"]` exists, the stored status from
  the day the device was added is pushed into the coordinator as current data. `:666-670` in the
  coordinator then skips the first status read. Stale values are shown as live until the first push.
- `:114-120`: `async_check_integration_health` is started as a background task **on every coordinator
  update**, so on every push. See 2.8.
- `:123-126`: the full first status is stored in `entry.data["status"]`.

### 2.2 `client.py` (232 lines): helpers around the library

- `_async_prepare_aiocoap_client_transport_env` (`:83-99`) resolves aiocoap's default client transports
  in a worker thread and writes them into the process-wide `os.environ["AIOCOAP_CLIENT_TRANSPORT"]`.
  Purpose: avoid blocking imports in the event loop and a Python 3.14 `SyntaxWarning` from aiocoap's
  tinydtls transport (`:28-55`). It is a process-global side effect that other aiocoap users in the same
  HA process also see.
- `async_create_client` (`:102-110`): `asyncio.wait_for(CoAPClient.create(host), timeout)`.
- `async_fetch_status` (`:113-130`): temporary client, `get_status(observe=False)`, shutdown. Used by the
  config flow and repairs.
- `async_fetch_device_info` (`:133-152`): plaintext `GET /sys/dev/info` with `sync=False`.
- `async_fetch_status_with_nudge` (`:155-232`): for push-only firmware. Opens an observation, writes a
  transient and a resting value for the display backlight, waits 12 s for a push, two attempts.

### 2.3 `coordinator.py` (725 lines)

Subclass of `DataUpdateCoordinator[dict[str, Any]]` without `update_interval` (push). Five task handles:
observe, watchdog, reconnect, reconnect-retry, reconnect-dispatch. Constants (`:28-59`):

| Constant | Value | Meaning |
|---|---|---|
| `DEFAULT_TIMEOUT` | 60 | assumed Max-Age until the device reports one |
| `MISSED_PACKAGE_COUNT` | 3 | watchdog = Max-Age x 3 = 180 s by default (option 1-20, model default, AC3039 = 10) |
| `NUDGE_WATCHDOG_TIMEOUT` | 1800 | watchdog and renewal interval for push-only models |
| `COAP_CALL_TIMEOUT` | 30 | bound on status reads and control writes |
| `RECONNECT_INITIAL_DELAY` / `RECONNECT_MAX_DELAY` | 5 / 60 | backoff 5, 10, 20, 40, 60, 60 ... |
| `RECONNECT_TASK_MAX` | 120 | a reconnect older than this is cancelled and restarted |
| `SHUTDOWN_TIMEOUT` | 10 | wait for task and client teardown |

Flow for a normal (non-nudge) model such as the AC3220:

1. First refresh (`:651-686`): `get_status(observe=False)` with 30 s timeout, else `ConfigEntryNotReady`.
2. `_start_observing` (`:357-384`): bumps a generation counter, starts `_async_observe_status` and the
   watchdog task.
3. `_async_observe_status` (`:408-458`): `async for status in client.observe_status(renew_interval=None)`.
   Each status sets `_last_update`, marks the device available and replaces `coordinator.data` wholesale
   (`:437-440`). When the stream ends for any reason other than cancellation, the `finally` block starts
   `_async_reconnect()` (`:452-458`).
4. `_async_watchdog` (`:464-493`): sleeps until `interval` after the last push; if nothing arrived it
   calls `_mark_unavailable("watchdog timeout")` and `_async_reconnect()`.
5. `_do_reconnect` (`:547-618`): stop observer -> **close the current client** (`:566`) -> create a new
   client (`:568`, 25 s) -> `get_status(observe=False)` (`:575-577`, 30 s) -> mark available ->
   `_start_observing()`. On failure: mark unavailable (`:607`), double the delay (`:603-604`), schedule a
   retry (`:618`).
6. `_mark_unavailable` (`:134-141`) sets `last_update_success = False`; because entities are plain
   `CoordinatorEntity` with no `available` override, **all entities go unavailable**.
7. `async_set_control_values` (`:212-228`): `wait_for(client.set_control_values(...), 30)`; any exception
   becomes a translated `HomeAssistantError`. The boolean result of the library call is discarded (`:221`).
8. `connection_diagnostics` (`:620-649`): generation, pushes in this session, first-push latency,
   reconnect attempts, backoff, stage and type of the last reconnect error, outage seconds.

Push-only ("nudge") models (HU1509, HU1510, HU4209/00, AMF870, CX5120, CX7550) take a different path:
`_async_refresh_via_nudge` (`:314-330`) and renewal every 1800 s (`:424`). The AC3220 is not one of them.

### 2.4 `entity.py` (47 lines)

`CoordinatorEntity` + `has_entity_name`. `DeviceInfo` has identifiers `(DOMAIN, device_id)`, the MAC
connection when known, name, manufacturer, model. It has **no `sw_version` and no `serial_number`**
(`:36-42`); kongo09 sets both (K09 `philips.py:62-72`).

### 2.5 `model.py`, `const.py`, `device_models.py`

- `ApiGeneration` GEN1 (`pwr` "1"/"0"), GEN2 (`D03-02` "ON"/"OFF"), GEN3 (`D03102` 1/0)
  (`model.py:147-172`).
- `DeviceModelConfig` dataclass: preset_modes, speeds, switches, lights, selects, numbers, humidifiers,
  heaters, binary_sensors, unavailable_filters/sensors, oscillation, `status_nudge`,
  `missed_package_count`.
- `DEVICE_MODELS` has 64 keys. Lookup order: exact 9-character model id (`AC3220/10`), then
  "model + WifiVersion prefix", then the 6-character family (`AC3220`) (`config_flow.py:231-250`,
  `coordinator.py:198-206`).
- Entity description tables in `const.py` are plain dicts (`SENSOR_TYPES`, `FILTER_TYPES`,
  `SWITCH_TYPES`, `LIGHT_TYPES`, `SELECT_TYPES`, ...), not `EntityDescription` classes.
- A `#N` suffix on a key (for example `D03105#1`) selects a value scheme and is stripped before the
  device is addressed.
- `_CONFIG_AC32XX` (`device_models.py:581`) is dead code: defined, never referenced.

### 2.6 `config_flow.py` (475 lines)

| Step | Behaviour |
|---|---|
| `dhcp` (`:176-276`) | Matchers in `manifest.json`: MAC prefixes `B0F893`, `047863`, `849DC2`, `80A036`, hostname `mxchip*`, `registered_devices: true`. kongo09 additionally has `6879C4*`. First matches existing entries by MAC or host and updates host plus reload **without** opening a connection (`:192-194`). Otherwise probes the device, detects the model, sets unique id = `DeviceId`, shows a confirm form |
| `user` (`:310-396`) | Host or IP only. Aborts if the host is already configured, probes, creates the entry. Does not learn the MAC |
| `reconfigure` (`:398-424`) | New host; aborts with `different_device` when `DeviceId` differs |
| reauth | None (no credentials; exempt) |
| Options (`:435-475`) | `update_watchdog` (bool) and `missed_package_count` (1-20). There is **no option for the renewal** |
| Push-only probe (`:120-149`) | On status timeout reads plaintext `sys/dev/info`, looks up the model, retries with the nudge |

No zeroconf, SSDP or active scan in the integration.

Gaps: the MAC is only learned through a DHCP discovery. A manually added device whose MAC prefix and
hostname are not in the manifest never gets a MAC stored, so an IP change is not followed automatically
(kongo09 resolved the MAC actively with `getmac`; that dependency was removed in `11c5183`). Issue #215
mentions a newer ESP32 based model with "Versuni MAC vendor prefix, hostname `espressif`". The MAC
prefix of the AC3220 is not known to me. Minor: the options form defaults the threshold to 3 instead of
the model default (`:453-458`), and `self._wifi_version.split("@")` (`:231`, `:352`) raises when
`WifiVersion` is missing.

### 2.7 Diagnostics

`diagnostics.py` returns system info, config, the coordinator's `connection` section, the entity list
and the full device status, with a redaction set of 34 keys (names, ids, MAC, host). Good and worth
copying. The function is excluded from coverage. `device_registry.sw_version` in it is always empty
because the integration never sets it.

### 2.8 Repairs (`repairs.py`, 545 lines)

Five repair flows: `connectivity_issue`, `filter_replacement_warning`, `entity_registry_cleanup`,
`configuration_migration`, `duplicate_entities`. Findings: [V-code]

- The connectivity repair is only raised `if not coordinator.client` (`:453`). `coordinator.client` is
  always a client object, so this repair is effectively never raised during a real outage.
- Its "fix" step opens a second CoAP client to the device (`:126-131`), against the integration's own
  single-client rule.
- The filter repair checks only Gen1 and Gen2 keys (`fltsts0..2`, `D05-14`, `:470-475`). Gen3 keys
  (`D0520D`, `D0540E`) are not checked, so it never fires for an AC3220.
- The health check walks the entity and device registries on every push (`__init__.py:114-120`).
- `configuration_migration` and `duplicate_entities` flows exist but nothing creates those issues.

### 2.9 Actions (`services.py`)

- `philips_airpurifier.set_child_lock` writes `PhilipsApi.CHILD_LOCK` = `"cl"` with a boolean (`:148`).
  That is the Gen1 key. The Gen3 key is `D03103` with 1/0.
- `philips_airpurifier.filter_reset` maps only `fltsts0/1/2` and `D05-14` (`:172-177`). For Gen3 it logs
  "Could not reset filter ...: total capacity unknown" and does nothing.

Both actions are therefore no-ops on an AC3220, and because the library result is ignored the call
reports success.

### 2.10 Events (`event.py`)

One `event` entity "notification" with types `error`, `out_of_water`, `cleared`, fired when the error
code (`err` or `D03240`) changes. Created only when the key is in the first status.

### 2.11 Bundled frontend

`frontend/src` (TypeScript 7 + Lit 3.3.3, 2,068 lines) builds
`INT frontend/philips-airpurifier-cards.js` (70 kB). It contains three Lovelace cards (purifier
controls and filter health, air quality with a 24 h PM2.5 trend, humidity). `frontend.py:37-40` serves it
at `/philips_airpurifier_frontend/` and injects it with `add_extra_js_url` into every frontend session,
whether or not the cards are used. Cards find entities by `translation_key` and device class
(`frontend/src/discovery.ts`). It is optional polish, unrelated to device communication.

---

## 3. How the AC3220 is modelled

### 3.1 Real status dump of an AC3220/10 (kongo09 issue #181, Nov 2024) [V-web, two fetches agree]

https://github.com/kongo09/philips-airpurifier-coap/issues/181 - 56 keys. Firmware then:
`D01S12 = "0.1.9"`, `WifiVersion = "AWS_Philips_AIR_Combo@3.0"`.

| Key | Value | Meaning (LIB `device_info.py:60-200`, INT `const.py`) |
|---|---|---|
| `D01S05` | "AC3220/10" | model id |
| `D01S03`, `D01S04` | strings | name fields |
| `D03102` | 1 | power |
| `D03103` | 0 | child lock |
| `D03105` | 0 | display backlight (0, 115, 123, 101 = auto) |
| `D0310A` | 2 | mode A |
| `D0310C` | 0 | mode B: 0 auto, 17 sleep, 18 turbo, 19 medium |
| `D0310D` | 1 | fan speed |
| `D03110` | 0 | timer |
| `D03120` | 1 | indoor allergen index |
| `D03221` | 1 | PM2.5 |
| `D03125` | 47 | humidity % |
| `D03224` | 212 | temperature x 10 |
| `D0312A` | 1 | preferred index (0 IAI, 1 PM2.5) |
| `D03130` | 100 | beep (100/0) |
| `D03135`, `D03136` | 0, 0 | lamp mode |
| `D03180` | 0 | Auto+ AI |
| `D03211` | 0 | timer remaining |
| `D03240` | 0 | error code |
| `D0520D` / `D05207` | 621 / 720 | pre-filter cleaning: remaining / total hours |
| `D0540E` / `D05408` | 9501 / 9600 | NanoProtect filter: remaining / total hours |
| `Runtime`, `rssi` | 317641004, -49 | uptime ms, Wi-Fi signal |
| `D03-42` | **absent** | Gen2 preferred index key |
| `D03137` | **absent** | ambient light mode |
| `D03122` | **absent** | gas |

A unit bought in 2026 probably runs newer firmware; the key set may differ.

### 3.2 tinkerologie model: `_CONFIG_AC3210` (`device_models.py:618-634`, used for AC3210, AC3220, AC3221 at `:1025-1027`)

| Aspect | Definition |
|---|---|
| Generation | GEN3: power `D03102`, on 1, off 0 |
| Presets (`:177-194`) | `auto` {D03102:1, D0310C:0}; `medium` {.., D0310C:19}; `turbo` {.., 18}; `sleep` {.., 17} |
| Speeds (`:195-216`) | `speed_1` .. `speed_5` = {D03102:1, D0310C:1..5} -> fan percentage 20/40/60/80/100 |
| Light | `D03105#1` display backlight: on 123, medium 115, off 0, effect `auto` = 101 |
| Switches | child lock `D03103` (1/0), beep `D03130` (100/0), Auto+ `D03180` (1/0) |
| Selects | preferred index **`D03-42`** {"IAI","PM2.5"}; lamp mode `D03135#1` {0 off, 1 air_quality, 2 ambient_light_mode}; ambient light `D03137` {1 warm, 2 dawn, 3 calm, 4 breath}; plus the generic `fan_mode` select (auto/medium/turbo/sleep) |
| Sensors | created only for keys present in the first status (`sensor.py:44-53`). With the dump above: IAI `D03120`, PM2.5 `D03221`, humidity `D03125`, temperature `D03224`, time remaining `D03211`, and disabled by default: fan speed `D0310D`, RSSI, Runtime. Filters: NanoProtect `D0540E` (%), pre-filter cleaning `D0520D` (%) |
| Binary sensors | none |
| Event | notification (key `D03240` present) |
| Nudge / watchdog | no nudge; watchdog 3 x Max-Age; renewal every Max-Age |

No AC3220-specific comment, quirk or TODO exists anywhere in the repository.

### 3.3 kongo09 model: `PhilipsAC3220 -> PhilipsAC3210 -> PhilipsAC22xx -> PhilipsNew2GenericFan` (K09 `philips.py:465-498`, `:799-853`, `:1173-1180`)

Same presets, same speeds, same light, same three switches. `PhilipsAC3210` overrides
`AVAILABLE_SELECTS = [PhilipsApi.NEW_PREFERRED_INDEX]` (`:1176`), which drops the timer, lamp mode and
Gen3 preferred index of `PhilipsAC22xx`.

### 3.4 Differences for the AC3220

| # | Topic | kongo09 | tinkerologie |
|---|---|---|---|
| 1 | Preferred index select | `D03-42` (wrong generation) | `D03-42` (same bug, inherited) |
| 2 | Lamp mode select `D03135` | no | yes (after issue #6 on an AC3210) |
| 3 | Ambient light select `D03137` | no | yes; key absent in the 2024 dump, entity is created anyway |
| 4 | Timer select `D03110` | no | no (present in status; only the unused `_CONFIG_AC32XX` has it) |
| 5 | `fan_mode` select for automations | no | yes; shows the first option (`auto`) when no preset matches, also when the device is off (`select.py:168-177`) |
| 6 | Event entity | no | yes |
| 7 | Runtime sensor | commented out (K09 `const.py:734`) | yes, disabled by default |
| 8 | Fan extra state attributes (name, model, firmware, error code, runtime) | yes (`AVAILABLE_ATTRIBUTES`) | none |
| 9 | Device registry firmware and serial | `sw_version = WifiVersion`, `serial_number = DeviceId` | not set |
| 10 | Availability | entity available when `coordinator.status is not None` (K09 `philips.py:80-82`), so effectively always | all entities unavailable on watchdog timeout or failed reconnect |
| 11 | Reconnect | timer 3 x 60 s after last push, new client, new observe, no timeout, no backoff, no status read (K09 `coordinator.py:63-91`) | see section 4 |
| 12 | Observe renewal | none | every Max-Age (60 s) |
| 13 | Commands during a quiet stream | keep working | fail while a reconnect is in backoff (closed client, issue #209) |
| 14 | Options | none | watchdog on/off, missed-package threshold |
| 15 | Diagnostics, repairs, actions, cards | none | yes (actions and repairs do not work for Gen3) |
| 16 | Library | `aioairctrl==0.3.1` (+ `getmac`) | `philips-airctrl==1.5.0` |
| 17 | DHCP MAC prefixes | 5 (incl. `6879C4`) | 4 |

Unverified for both: whether an AC3220 accepts `D0310C = 1..5` (manual speeds). The product has Auto,
Sleep, Medium and Turbo; the five speeds come from the shared AC22xx table.

Additional entity-level defects that affect an AC3220: [V-code]

- `PhilipsSwitch.is_on` returns `status.get(key) != off` (`switch.py:63`), so a switch whose key is
  missing shows **on**.
- Filter sensor and binary sensor index the status dict directly (`sensor.py:125`, `binary_sensor.py:64`)
  and raise `KeyError` if a later status lacks the key.
- Optimistic writes mutate `coordinator.data` in place and re-render only the calling entity
  (`fan.py:116-117`, `:122-123`, `:147`, `:176`; `switch.py:68-69`; `select.py:145-146`). Other entities
  on the same key follow at the next push.

---

## 4. Reliability strategy and where it breaks

### 4.1 What the library does on the wire (LIB `coap/client.py`)

- Every request is `transport_tuning=Unreliable` = CoAP NON (`:143`, `:175`, `:257`, `:374`, `:411`).
  aiocoap does not retransmit NON and has no request timeout (AIOCOAP `protocol.py:567`:
  "# FIXME: Implement timing out with REQUEST_TIMEOUT here"). One lost datagram is a hang until the
  caller's `wait_for` fires (25-30 s in the integration).
- `Context.create_client_context()` with default transports (`:60`): on Linux that is oscore, tinydtls,
  tcpclient, tlsclient, ws and udp6 per client (AIOCOAP `defaults.py:35-79`). udp6 opens an `AF_INET6`
  socket (AIOCOAP `transports/udp6.py:356`). kongo09's aioairctrl uses
  `create_client_context(transports=["simple6"])` (`kongo09_aioairctrl/aioairctrl/coap/client.py:48`).
- `get_status(observe=False)` (`:152-196`) sends `GET /sys/dev/status` with Observe=0, awaits the first
  response and cancels the observation locally. aiocoap's cancel is local only; the next notification on
  that token is answered with RST (AIOCOAP `protocol.py:1195-1217`, `messagemanager.py:389-398`,
  `tokenmanager.py:177-186`).
- `observe_status()` (`:272-345`) registers, yields the first response, then waits for notifications
  until a deadline of Max-Age (default 60). At the deadline it sends a **new** Observe GET with a new
  token and waits `RENEWAL_TIMEOUT = 10.0` s (`:29`, `:328-330`). On timeout the exception leaves the
  generator and the `finally` cancels the old, still working observation (`:344-345`). The test
  `tests/test_client.py:970-984` `test_renewal_that_never_answers_times_out` asserts exactly that both
  observations are cancelled.
- A renewal response equal to the last status is not yielded (`:336-337`).

### 4.2 Failure chain on firmware that does not answer a new registration promptly [V-code + hearsay for the firmware behaviour]

1. T+60 s: renewal GET sent. No answer within 10 s -> `TimeoutError`, healthy observation cancelled
   (LIB `client.py:324-330`, `:344-345`).
2. Coordinator: stream ended -> `_async_reconnect` (INT `coordinator.py:452-458`).
3. `_do_reconnect`: close client (`:566`), new client and sync (`:568`, reported to answer in
   10-200 ms), then `get_status(observe=False)` with 30 s (`:575-577`). This is the same kind of request
   as the renewal that just went unanswered.
4. Timeout -> "failed at the status stage (TimeoutError)", `_mark_unavailable("reconnect failed")`
   (`:607`), all entities unavailable, retry after 5, 10, 20, 40, 60 s.
5. Each attempt holds a request open for 30 s and then idles for the backoff. If the device answers a
   registration only when a value changes, recovery depends on a change falling into an open window.
6. While this runs, `self.client` is a closed client (`:566`, `:599-602`), so every command fails with
   "Client not initialised or already shut down" (issue #209).

The same applies at the watchdog: a device that only pushes on change and is idle for 180 s is marked
unavailable although nothing is wrong (`:478-493`).

### 4.3 Field evidence [V-web; numbers are reporters' own]

Issue #172 (open since 2026-10-27, 13 comments, labels bug + needs-triage),
https://github.com/tinkerologie/ha-philips-airpurifier/issues/172

- Reporter Luke2105-Loft59, AC2210, device firmware 0.2.3, Wi-Fi firmware 86. A/B test, 24 h each:

  | | v2026.10.3 (renewal) | v2026.10.2 (no renewal) |
  |---|---|---|
  | Outages | 118 | 14 |
  | Total unavailable | 10 h 22 min | 3 h 21 min |
  | Outages under 1 min | 45 | 1 |

  Quote: "For my AC2210, v2026.10.3 is clearly worse:".
- His 24 h debug log on 2026.10.3: "Out of 414 renewals, 196 (47 %) got no push within 10 s"; one-shot
  status requests: 885 attempts, 683 timed out. Conclusion: "The AC2210 keeps an established observation
  running fine, but often doesn't answer a new observe request (renewal) or the one-shot status request,
  especially when it has been idle for a while." Requests: "If a renewal gets no response within 10 s,
  keep the existing observation (or retry the renewal) instead of ending the stream; let the watchdog
  decide when the device is really gone." and "Make the periodic renewal optional (or opt-out per
  device)".
- mbreitkreuz (AMF870, `AWS_Philips_AIR_Combo@86`): "This firmware is push-only: it sends a notification
  only when a reported value changes". "Push-only firmware doesn't answer the registration by itself."
  "`get_status()` sends the status GET as a CoAP Observe registration (`observe=0`)."
- Other reporters with the same status-stage timeouts: CX5120/11 (`AWS_Philips_AIR@86.1`), AC2729/10
  (`AWS_Philips_AIR@91.1`, v2026.11.1). In all reports the sync is answered in 10-210 ms during outages.
- Maintainer statements in the thread: "Debug logs will help a lot", "Try the new release and see how
  you go". No diagnosis, no fix plan, no linked PR.

Issue #214 (open since 2026-11-17), https://github.com/tinkerologie/ha-philips-airpurifier/issues/214

- AC3033/14 and AC1715 with the same pattern on v2026.11.1.
- Comment of 2026-11-22 by Karacostapannis: **AC2220/10, `AWS_Philips_AIR_Combo@86`**, v2026.11.1. With
  kongo09 v0.37 over 8.5 days: 5 unavailable periods. After migrating, in 30 hours: 56 unavailable
  periods of 5 to 40 s. He attributes it to the 60 s renewal with 10 s timeout and notes the CX5120 fix
  does not apply because the AC2220 is not flagged push-only.

Library issue #34 (closed), https://github.com/tinkerologie/philips-airctrl/issues/34: on an
AC4220/12 (firmware 0.2.3) the stream "stops yielding updates after about 2.5 minutes. It raises no
error and the iterator never ends." Sessions delivered their last push 2 m 42 s and 2 m 31 s after start.
The plan that led to 1.4.0 assumed: "An idle device still answers renewals, so a failed renewal reliably
indicates an unreachable device." The reports above contradict that assumption for other models.

PR #40 (closed unmerged, June 2026) by an **AC3221** owner stated the device "can be reachable and
return status snapshots while a fresh observe stream stays quiet or does not deliver an initial
payload."

So the evidence conflicts across models: AC4220/12 loses the observation after about 150 s without
renewal; AC2210 keeps it but ignores renewals when idle; AC3221 answers snapshots while a fresh stream
stays quiet. Which of these an AC3220 on current firmware does is unknown.

### 4.4 Requested topics, one by one

| Topic | What it does | Verdict |
|---|---|---|
| Observe loss | Stream end -> reconnect; generation counter keeps a stale stream from restarting recovery (`coordinator.py:119-122`, `:454`) | Sound bookkeeping; the trigger (renewal timeout) is the problem |
| Re-sync | New client and sync on every reconnect; library re-syncs after a rejected control | Works; see 4.5 item 1 for the retry bug |
| Timeouts | Every coordinator call is bounded (25/30/10 s) | Good; kongo09 has none |
| Backoff | 5 -> 60 s, reset on success; a 120 s wedge guard | Good |
| Device IP change | DHCP discovery updates host by MAC and reloads; `registered_devices`; manual reconfigure flow | Works only when the MAC was learned through DHCP discovery (2.6) |
| Startup, device offline | `ConfigEntryNotReady`, HA retries | Standard and correct |
| Command retries | None in the integration. Library retries only when the device answers "not success". A lost datagram is a 30 s wait and an error | Weak |
| Availability debouncing | None. Stream end alone does not mark unavailable (since 2026.6.2), but a failed reconnect or the watchdog does, immediately | Flapping: 45 of 118 outages were under 1 min |
| Liveness model | "A status must arrive every 3 x Max-Age" | Wrong for firmware that only pushes on change |

### 4.5 Remaining weaknesses, with locations

Library:

1. **Retry after re-sync resends the old ciphertext.** `payload_encrypted` is computed once before the
   loop (LIB `client.py:369`) and reused for all six attempts (`:371-388`), although `_sync()` at `:385`
   replaces the client key. betaboon's original recursed and therefore re-encrypted
   (`betaboon_aioairctrl/aioairctrl/coap/client.py:113-131`); kongo09's fork encrypts inside the loop
   (`kongo09_aioairctrl/aioairctrl/coap/client.py:165-166`). The change came with commit `844a15c`
   (2026-02-13). Tests mock `encrypt` and do not notice. Whether the device rejects the stale counter is
   not verified, but the retry exists precisely for the case that it rejected the first one.
2. **No cleanup when `create()` fails or is cancelled.** `_init` creates the aiocoap context and then
   awaits `_sync()` with no `try/finally` (`:59-63`, `:77-90`). When the integration's `wait_for`
   cancels it, the context with its UDP socket is never shut down. With a powered-off device the
   coordinator retries every 60 s, so about 1,440 leaked contexts per day [inference from code].
   kongo09's fork closes the context in that case (`aioairctrl/coap/client.py:50-56`).
3. One unanswered renewal kills a healthy stream (4.1).
4. NON without retransmission everywhere.
5. Heavy dependency set for a protocol client: `aiocoap`, `pycryptodomex`, `netifaces`, `tabulate`,
   `pyyaml`, `click`, `pydantic` (`pyproject.toml`). HA's wheel index has `netifaces` for cp314, so it
   installs, but none of the last five are needed to talk to a purifier.

Integration:

6. Reconnect closes the working client before a new one exists and leaves a closed client in
   `self.client` on failure (`coordinator.py:566`, `:599-602`). Commands fail during the whole backoff
   (issue #209, open). No lock between the command path and the reconnect path.
7. Reconnect success requires a one-shot status read (`:575-577`).
8. `_async_update_data` (`:332-355`), reachable through `homeassistant.update_entity`, registers and
   cancels a second observation on the live session and marks the device unavailable when it fails.
9. Result of `set_control_values` ignored (`:221`); entities then write optimistic state. On a device
   that pushes only on change, a rejected command leaves a wrong state in HA until something else changes.
10. Status replaced wholesale on every push (`:440`); no merge. Assumes full snapshots.
11. Entities for sensors and filters depend on the first status (`sensor.py:44-53`).
12. Stale stored status used as live data when the watchdog is off (`__init__.py:108-109`,
    `coordinator.py:666-670`).
13. Health check on every push; connectivity repair never raised (2.8).
14. Actions and filter repair do not cover Gen3 (2.8, 2.9).
15. Preferred-index select with a Gen2 key on a Gen3 device (`device_models.py:629-633`).
16. `PARALLEL_UPDATES = 0` on all platforms: no serialisation of commands.
17. In the nudge path, an observation that ends early is not noticed (issue #210, open). Not relevant
    for the AC3220.

### 4.6 What is good and worth copying

- Bounded calls, exponential backoff, generation guard, single teardown per client.
- Stage-labelled reconnect logging and the `connection` diagnostics section.
- DHCP matching by MAC before any network I/O.
- `sys/dev/info` plaintext probe to identify a model without a status read.
- Translated exceptions, redacted diagnostics, complete translations in 6 languages including Dutch.
- The Gen3 field dictionary in LIB `device_info.py`.

---

## 5. Open issues at the time of research [V-web]

Integration, https://github.com/tinkerologie/ha-philips-airpurifier/issues (6 open, 40 closed):

| # | Opened | Title | Relevance |
|---|---|---|---|
| 172 | 2026-10-27 | AC2210: CoAP stops responding (mostly at night) while device stays on Wi-Fi and in the cloud app - reconnects fail for 10-40 min | Core problem, same family as AC3220, unresolved |
| 214 | 2026-11-17 | Recurring CoAP status timeouts on Philips AC3033/14 and AC1715 | Same pattern; AC2220/10 regression report added 2026-11-22 |
| 209 | 2026-11-13 | service call error | Commands fail on a closed client; maintainer only asked "Have you tried the latest version 2026.11.1?" |
| 210 | 2026-11-15 | Status nudge keeps waiting for a push after its observation has ended | Nudge models only |
| 217 | 2026-11-20 | manifest.json still pins philips-airctrl 1.5.0 after #216 | Release hygiene |
| 215 | 2026-11-19 | 0700 series does not support local CoAP | AC0720/10: UDP 5683 closed, cloud only. Shows Philips ships models without local CoAP |

Closed issues that matter: #6 (AC3210 ambient light entity), #8 (IP change), #51 (stream ended ->
unavailable), #58 (AC2210/10 support), #132 (AMF870 push-only). No issue names the AC3220.

Library, https://github.com/tinkerologie/philips-airctrl/issues: 7 issues, all closed (#34 renewal,
#36 double shutdown, #44 undecryptable push, #1 AC4221 power-on needed the `-I` integer flag). No issue
or PR about tolerant or optional renewal exists in either repo.

Responsiveness: external PRs with tests are merged in about two days (#208 opened 2026-11-10, merged
2026-11-12; #101; #199; library #40 and #45 by mbreitkreuz). PR #40 (a larger redesign) got a detailed
review and was closed by its author. The contribution process requires an issue first, a CodeRabbit
plan, a draft PR, a governance checklist and a 90 % patch coverage gate (`CONTRIBUTING.md`,
`codecov.yml`).

---

## 6. Assessment for an AC3220 owner in November 2026

**Will it already solve the inconsistent behaviour?** Not reliably, and it may make it worse.

- If the user's AC3220 firmware answers every Observe registration at once, v2026.11.1 should be stable:
  the 60 s renewal removes the lapse that kongo09 only repairs every 3 minutes.
- If it behaves like the AC2210 and AC2220 on `AWS_Philips_AIR_Combo@86` (same family tables, likely the
  same firmware line), expect frequent short unavailability and failing commands during those periods.
  There is no option to switch renewal off; the only workaround reporters use is pinning v2026.10.2,
  which then has the watchdog-driven cycle.
- Independent of connectivity: preferred-index select wrong, ambient-light select possibly dead, both
  actions no-ops, no firmware version on the device page.

**Options**

| Option | For | Against |
|---|---|---|
| (a) Just use it | 10 minutes to try; best logging to learn how this unit behaves | Open core issue; three functional defects on this model; entities flap; no migration from kongo09 |
| (b) Contribute fixes | Maintainer merges tested PRs quickly; small fixes are easy (model key, Gen3 actions, manifest pin) | The real fix spans library and coordinator and changes a design the maintainer chose (and tests enforce); heavy process; four weeks without maintainer diagnosis on #172 |
| (c) Fork | Full control | 7 k lines of integration, 11 k lines of tests, 64 models, cards, 12 workflows to carry for one device |
| (d) New focused integration | One device, one generation: roughly 600-900 lines. Free to choose the right liveness model. Can target core quality rules from the start | Must own the session layer; loses multi-model coverage |

**Recommendation: (d), combined with a small part of (b).**

- Do not build on `philips_airctrl.CoAPClient.observe_status()` or `get_status(observe=False)`: their
  semantics are the failure mode. The reusable part is small: `EncryptionContext` (69 lines), the four
  resource paths, the request JSON shape, and the Gen3 field dictionary. Either depend on the library
  only for `philips_airctrl.coap.encryption`, or implement those 69 lines on `cryptography` /
  `pycryptodomex` and talk CoAP through aiocoap with `transports=["udp6"]` or `["simple6"]`, or through
  a minimal own NON client.
- Upstream what is cheap and helps others: the `D0312A` key for AC3210/AC3220/AC3221, Gen3 keys in the
  actions, re-encrypt per retry and context cleanup in the library.
- Before designing, install the tinkerologie integration for a day with debug logging to record how
  this unit answers registrations, then remove it. Only one client at a time.

---

## 7. Design implications for a new integration

1. **Separate liveness from data.** Sync (`POST /sys/dev/sync`) is answered in 10-210 ms even when
   status requests are not. Use sync or `GET /sys/dev/info` as heartbeat. Silence on the status stream
   is not an outage.
2. **One observation per session.** Take the initial state from the registration response. Do not do a
   one-shot read followed by a second registration on the same socket; the cancelled token is answered
   with RST by aiocoap.
3. **Renewal must be make-before-break without a deadline.** Keep the old observation until the new one
   has delivered. Never end a working stream because a renewal was not answered. Make interval and
   behaviour configurable.
4. **Keep the control path alive while the observe path recovers.** Do not close the client before a
   replacement is ready. Serialise commands with a lock.
5. **Retransmit NON requests in the application** (for example 3 tries, 2-3 s apart) for sync and
   control, and re-encrypt with a new counter per attempt.
6. **Check the command result** and raise on `status != success`. Confirm state from the next push
   instead of writing optimistic state unconditionally; if optimistic, time it out.
7. **Debounce availability**: grace period before entities go unavailable; keep last values meanwhile.
8. **Merge status updates** into a persistent dict and read with `.get`, so partial pushes are harmless.
9. **Static entity set per model**, not derived from the first payload.
10. **AC3220 mapping** to start from: power `D03102`; mode `D0310C` (0/17/18/19); fan speed `D0310D`
    (read only); child lock `D03103`; display `D03105` (0/115/123/101); beep `D03130` (100/0); Auto+
    `D03180`; preferred index `D0312A` (0/1); lamp `D03135`; timer `D03110` / `D03211`; sensors
    `D03221`, `D03120`, `D03125`, `D03224`/10; filters `D0540E`/`D05408`, `D0520D`/`D05207`; error
    `D03240`; `rssi`, `Runtime`; firmware `D01S12`, `WifiVersion` into `sw_version`.
11. **Store the MAC at setup** (DHCP discovery info, or look it up) and declare `registered_devices`,
    so IP changes are followed. Offer a reconfigure flow.
12. **Ship diagnostics like theirs** (connection section with stage and counters, redacted status).
13. Skip bundled cards, repairs for registry cleanup, and generic multi-model tables.

---

## 8. Open questions (need the user's device)

1. Firmware of the user's AC3220: `D01S12` and `WifiVersion` (2024 sample: 0.1.9 /
   `AWS_Philips_AIR_Combo@3.0`; problem reports: `...Combo@86`).
2. Does it answer an Observe registration immediately, or only at the next state change? Measure the
   latency of repeated `philips-airctrl status -H <ip>` calls while idle and while PM2.5 is changing.
3. Does an unrenewed observation stop after about 150 s (AC4220/12) or keep running (AC2210)?
4. Does an RST on a cancelled token, or a second registration from the same socket, end the first one?
   Needs a packet capture.
5. Which Observe sequence numbers does the device send? aiocoap drops notifications it considers out of
   order for 128 s (AIOCOAP `protocol.py:695-715`, `numbers/constants.py:142`).
6. Are pushes full snapshots or deltas?
7. Does the device accept CON requests? Does it serve more than one client?
8. Does `D0310C = 1..5` work on the AC3220? Is `D03137` present on current firmware?
9. MAC prefix and DHCP hostname of the AC3220 (for discovery matchers).
10. Is this repo in the HA Marketplace catalog, or only installable as a custom link?

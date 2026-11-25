# 02 - Critical code review of kongo09/philips-airpurifier-coap (HACS, domain `philips_airpurifier_coap`)

Research date: 2026-11-22. Angle: why the established HACS integration is unreliable, what exactly it exposes for the AC3220, and what a better integration must do differently.

## 0. Sources and how far each claim was verified

Code paths are relative to `scratchpad/src/`.

| Tag | Meaning |
|---|---|
| **[V-code]** | Verified by reading the source at the pinned commit (file:line given). |
| **[V-sim]** | Verified by a static AST simulation I wrote (`scratchpad/scripts02/mro_sim.py`, no third-party code executed). |
| **[V-dep]** | Verified by reading the dependency's source (aiocoap 0.4.17 sdist from PyPI, HA core `dev` branch files from raw.githubusercontent.com). |
| **[R-issue]** | Reported in a GitHub issue/PR discussion. Read through WebFetch (a summarising fetch, so wording is second-hand; numbers and code references are as relayed). Not reproduced by me. |
| **[R-pr]** | Read directly from the PR's git ref (`refs/pull/N/head`), i.e. primary source for the *proposed code*, but the claims in its commit message are the PR author's. |
| **[I]** | My inference. |

Pinned revisions:

- `kongo09_philips-airpurifier-coap` master = `964ef214fc7de1aa6d98f9e392b7c404426f6ee5` (2026-07-26). Latest release tag `v0.37` = `0a2fc46` (2026-07-26); `git diff v0.37 origin/master` only touches `manifest.json` formatting/version. A pre-release `v0.37.1-beta.1` (2026-07-26) exists "only for AC3420" [R-issue, releases page]. **No commit on master since 2026-07-26** (4 months) [V-code, `git fetch` on 2026-11-22].
- `kongo09_aioairctrl` master = tag `v0.3.1` = `cc280461366437be25b05a00952f647ecd974aff` (2026-03-01). PyPI: 0.2.5 (2024-01-01), 0.2.6 (2026-02-21), 0.3.0 and 0.3.1 (both 2026-03-01). No release since.
- `Denaun_philips-airpurifier-coap` (ancestor) = `d1583b2` (2021-08-02).
- aiocoap 0.4.17 (PyPI, 2025-11-05; latest as of today).
- HA core `dev` = 2026.12 (`homeassistant/const.py` MAJOR 2026, MINOR 12).

The full history of the integration repo was unshallowed (952 commits) and all PR heads were fetched (`refs/remotes/pr/*`) so that unmerged PRs could be read as code.

---

## 1. Architecture walkthrough

### 1.1 Files

`kongo09_philips-airpurifier-coap/custom_components/philips_airpurifier_coap/`: `__init__.py` (205 lines), `config_flow.py` (368), `coordinator.py` (151), `timer.py` (89), `philips.py` (2282, entity base classes + one fan class per model), `const.py` (1096, key names + per-platform description dicts), `model.py`, `helpers.py`, `config_entry_data.py`, platforms `fan/sensor/binary_sensor/switch/light/select/number/humidifier/climate`, `main.js` + `icons/pap/*.svg` (custom icon set injected into the frontend), `icons.json`, `strings.json`, translations `bg de en nl ro sk`.

No `diagnostics.py`, no `quality_scale.yaml`, no `services.yaml`. Tests: 43 lines total, of which `tests/test_smoke.py` is `assert True` and `tests/test_mac_address.py` tests MAC normalisation only [V-code].

`AGENTS.md` in the repo describes an architecture that does **not** match the code: it says the coordinator is a "DataUpdateCoordinator with push-based updates", that `async_set_updated_data()` notifies listeners, that entities read `self.coordinator.data`, and that `ConfigEntryData` lives on `entry.runtime_data`. None of this exists on master (see 1.4, 5) [V-code, `AGENTS.md` vs `coordinator.py`, `__init__.py:180`].

### 1.2 manifest / packaging [V-code `manifest.json`, `hacs.json`]

```json
"dependencies": ["frontend", "http"],
"dhcp": [ {"macaddress": "6879C4*"}, {"macaddress": "B0F893*"}, {"macaddress": "047863*"},
          {"macaddress": "849DC2*"}, {"macaddress": "80A036*"}, {"hostname": "mxchip*"},
          {"registered_devices": true} ],
"integration_type": "device", "iot_class": "local_push",
"requirements": ["aioairctrl==0.3.1", "getmac>=0.9.4"],
"version": "0.25.0"   // rewritten by a release workflow
```

- DHCP matcher history: `f91cb50` 2022-04-19 (initial), `4315385` 2024-01-21 (AMF), `64c8d2c` 2024-10-05 ("mac of new devices"), `a0377a5` 2026-01-31 (added `6879C4*`). I did not look up which vendors own these OUIs; whether a 2026-production AC3220/10 uses one of them is **unknown** (see open questions).
- `hacs.json` says minimum HA `2024.8.0`, but `config_flow.py:15` imports `homeassistant.helpers.service_info.dhcp`, which only exists from HA 2025.2.0 (HTTP 404 for that file at tags 2024.12.0 and 2025.1.4, 200 at 2025.2.0) [V-dep]. Real minimum is 2025.2.
- No zeroconf/ssdp matcher. No `loggers` key.

### 1.3 Config flow (`config_flow.py`) [V-code]

Three entry points, all doing the same network probe: `CoAPClient.create(host)` under a 30 s `TimeoutManager` timeout, then `client.get_status()` under another 30 s, then `client.shutdown()`.

- `async_step_dhcp` (L62-160): takes `discovery_info.ip`, probes the device **first** (L70-86), and only afterwards derives the unique id from the status (`status[PhilipsApi.DEVICE_ID]`, L109) and calls `async_set_unique_id` + `_abort_if_unique_id_configured(updates={CONF_HOST: self._host})` (L146-147). So an already-configured device is fully probed on every discovery event before the flow learns that it is already configured.
- `async_step_user` (L192-302): one field (host), same probe, creates the entry.
- `OptionsFlowHandler.async_step_init` (L305-364): "reconfigure IP" implemented as an *options* flow; stores `{CONF_HOST: new_host}` in `entry.options` after checking the DeviceId matches.

Model detection (L119-139 / L257-277): `extract_model()` returns the first 9 chars of `modelid` / `D01-05` / `D01S05` (`helpers.py:22-32`), then tries `model` -> `model + " " + WifiVersion.split("@")[0]` -> `model[:6]` against `model_to_class`. For an AC3220/10 this resolves to the family key `"AC3220"`.

Entry data written: `host`, `model` (matched key, e.g. `AC3220`), `name`, `device_id`, and **`status` = the complete status dict captured during the flow** (L174-178, L243-247).

Bugs in the flow itself:

| Where | Problem |
|---|---|
| L98-100, L231-233 | `raise exceptions.ConfigEntryNotReady` inside a config flow. In the DHCP step this is an unhandled exception in the flow manager. |
| L91-96 | Timeout in the DHCP step aborts with reason `model_unsupported` (wrong reason). |
| L70-96, L209-229, L319-358 | No `finally`: when `get_status()` times out or raises, `client.shutdown()` is never called, so the aiocoap context, its UDP socket and the device-side observe registration are leaked. (PR #389 `beefb15` rewrites this with `try/finally`.) |
| L120, L258 | `self._wifi_version.split("@")` with `self._wifi_version = status.get("WifiVersion")`: `AttributeError` if the key is absent. |
| L200-204 | `raise InvalidHost` at L202 is *before* the `try:` at L204 whose `except InvalidHost` (L290) is meant to catch it, so an invalid hostname crashes the flow instead of showing the form error. |
| L147 vs `__init__.py:139` | Host has two sources of truth, see 3 (W9). |

### 1.4 Setup, coordinator, data flow

`async_setup` (`__init__.py:93-105`): registers static paths for `main.js` and the `pap` icon directory, calls `add_extra_js_url` (injects a JS module into every frontend session) and registers an unauthenticated `ListingView` (`requires_auth = False`, L66).

`async_setup_entry` (`__init__.py:136-186`):

1. L139 `host = entry.options.get(CONF_HOST, entry.data[CONF_HOST])`.
2. L143 `mac = await async_get_mac_address_from_host(hass, host)` - runs `getmac.get_mac_address` in the executor on every setup; result only used for `DeviceInfo.connections`.
3. L147-153 `client = await asyncio.wait_for(CoAPClient.create(host), timeout=25)`; any exception -> `ConfigEntryNotReady`.
4. L157-171: **if `CONF_STATUS` is in `entry.data` (always, for entries created since v0.22.0 / 2024-11), the coordinator is constructed with that stored status and no live read is done.** Only legacy entries without a stored status call `coordinator.async_first_refresh()`.
5. L174-180 stores a `ConfigEntryData` dataclass in `hass.data[DOMAIN][entry.entry_id]` (not `entry.runtime_data`).
6. L182 forwards 9 platforms; L184 registers an update listener that reloads the entry on any entry update.

`Coordinator` (`coordinator.py`) is a hand-written class (not `DataUpdateCoordinator`):

- State: `self.client`, `self.status` (dict), `self._listeners`, `self._task` (observe task), `self._reconnect_task`, `self._timeout = 60` (L42), `self._timer_disconnected = Timer(timeout=60 * MISSED_PACKAGE_COUNT(=3) = 180 s, callback=self.reconnect, autostart=True)` with auto-restart (L44-49).
- `async_add_listener` (L107-122): the first listener triggers `_start_observing()`.
- `_start_observing` (L143-151): cancels any previous observe task (not awaited), `asyncio.create_task(self._async_observe_status())`, resets the timer.
- `_async_observe_status` (L134-141):

  ```python
  async for status in self.client.observe_status():
      self.status = status
      self._timer_disconnected.reset()
      for update_callback in self._listeners:
          update_callback()
  ```
  No `try/except`, no done-callback.
- `reconnect` (L63-74) is the timer callback: cancels a running `_reconnect_task` and starts a new one.
- `_reconnect` (L76-91):

  ```python
  with contextlib.suppress(Exception):
      await self.client.shutdown()
  self.client = await CoAPClient.create(self.host)   # no timeout
  self._start_observing()
  except asyncio.CancelledError:  # "Silently drop this exception ... Reconnect took to long"
      pass
  ```
- `shutdown` (L51-61): cancels reconnect task (not awaited), cancels timer, `await self.client.shutdown()` unguarded. Does not cancel `self._task` (relies on listener removal).

`Timer` (`timer.py`, docstring L1: *"Timer class to handle instable Philips CoaP API."*): a task that sleeps `timeout`, awaits the callback, and loops when auto-restart is on. `reset()` = cancel + start a new task (called on every notification). `cancel()` raises `CallbackRunningException` if called while the callback runs (L67-73).

Entities (`philips.py:39-100`): `PhilipsEntity(Entity)` with `_attr_has_entity_name = True`, `should_poll = False`, `available = self.coordinator.status is not None` (L79-82), `_device_status = self.coordinator.status` (L84-87), registers `_handle_coordinator_update` (which just calls `async_write_ha_state()`) with the coordinator in `async_added_to_hass`. `DeviceInfo` is built once in `__init__` from the status available at that moment (L59-72): `model = extract_model(status)`, `sw_version = status["WifiVersion"]`, `serial_number = identifiers = DeviceId`, `connections = {(mac)}` if getmac returned one.

Commands: every entity awaits `self.coordinator.client.set_control_value(s)(...)` directly and then mutates the shared status dict optimistically and writes its own state, e.g. `philips.py:260-263`:

```python
await self.coordinator.client.set_control_value(self.KEY_PHILIPS_POWER, self.STATE_POWER_ON)
self._device_status[self.KEY_PHILIPS_POWER] = self.STATE_POWER_ON
self._handle_coordinator_update()
```

There are 28 such call sites (`grep -n set_control_value *.py`), none checks the boolean return value, none has a timeout, none converts errors into `HomeAssistantError` [V-code].

Unload (`__init__.py:194-205`): `async_forward_entry_unload` per platform in a loop (results ignored), then `await config_entry_data.coordinator.shutdown()`, then pops `hass.data`.

### 1.5 The CoAP client actually used (aioairctrl 0.3.1) [V-code `kongo09_aioairctrl/aioairctrl/coap/client.py`, `encryption.py`]

- `Client._init` (L47-56): `Context.create_client_context(transports=["simple6"])`, then `_sync()`.
- `_sync` (L69-86): **NON** POST to `coap://host:5683/sys/dev/sync` with 8 random hex chars; the reply payload is taken verbatim as the "client key" (no validation).
- `get_status` (L88-108): NON GET `/sys/dev/status` **with `Observe: 0`** (L98) - i.e. it registers an observation and only consumes the first response; returns `(state.reported, max_age)` with `max_age` defaulting to 60.
- `observe_status` (L110-139): NON GET with `Observe: 0`, yields the first response then every notification; `finally: observation.cancel()`.
- `set_control_values` (L146-188): payload `{"state":{"desired":{"CommandType":"app","DeviceId":"","EnduserId":"", **data}}}`, encrypted, NON POST to `/sys/dev/control`; up to `retry_count + 1 = 6` attempts; re-`_sync()` after the first non-`success` reply; returns `True/False`.
- Encryption (`encryption.py`): envelope = 8 hex chars counter + AES-128-CBC ciphertext (hex) + SHA-256 hex of (counter + ciphertext); key/IV = two halves of `MD5("JiangPan" + counter).hexdigest().upper()`; counter incremented by 1 before each encrypt (`int(self._client_key, 16) + 1`, L39).
- **No timeout on any await** (L83, L99, L130, L173). All messages are NON, which aiocoap sends exactly once.

Relevant aiocoap 0.4.17 facts [V-dep]:

- `aiocoap/protocol.py:567` - `# FIXME: Implement timing out with REQUEST_TIMEOUT here`: there is no request timeout. A NON request whose reply is lost is awaited forever.
- `aiocoap/messagemanager.py:77-84` - `shutdown()` iterates `self._active_exchanges.values()` and then sets `self._active_exchanges = None`; `Context.shutdown()` (`protocol.py:415-455`) does not clear `request_interfaces`. A second `shutdown()` on the same context therefore raises `AttributeError: 'NoneType' object has no attribute 'values'`.
- `aiocoap/transports/simple6.py:24` - the hard-coded transport describes itself as *"experimental, likely to change, and not fully tested yet"*; it opens one connected UDP socket per remote per context, so every new `Client` uses a new source port.
- `aiocoap/protocol.py:700-708` - observation notifications are only delivered to the application if the Observe option value increased (mod 2^24 rules) or more than `OBSERVATION_RESET_TIME = 128` s passed since the last accepted one; otherwise they are dropped without any log line.
- `aiocoap/messagemanager.py:95-108` - message-ID deduplication applies to requests only, not to responses. (aioairctrl <= 0.2.6 globally monkeypatched `MessageManager._deduplicate_message` to always return "not a duplicate"; removed in `bcc2a89`, 2026-03-01.)

### 1.6 Comparison with the Denaun ancestor [V-code `Denaun_philips-airpurifier-coap/custom_components/philips_airpurifier_coap/__init__.py`]

Denaun (2021, YAML-only, 1237 lines, platforms fan + sensor, aioairctrl 0.2.1 from git) already contains the same `Coordinator` skeleton: listener list, `_start_observing`, the unguarded `async for status in self.client.observe_status()` loop (L159-164) and `available = self.coordinator.status is not None` (L184-186). Differences that matter:

- Denaun always did a live `await coordinator.async_first_refresh()` at setup (L99). kongo09 kept that until 2024-11; commit `0f69456` (2024-11-10, first released in v0.22.0) moved it into the "legacy entry without stored status" branch, so normal setups now start from the cached status.
- kongo09 added: config flow + DHCP (2022-04), the `Timer` watchdog and reconnect logic (2022-04/05, by Marcel Hetzendorfer / @mhetzi: `6e899e1`, `0a986d2`, `4896591`, `37be22c`), many models, extra platforms, custom icons.
- The reconnect/timer code has had **no functional change since May 2022**; `git log -- coordinator.py timer.py` after that shows only refactors and lint commits (`19dbb81` 2024-11-02, `e97b001` 2024-11-03, ruff commits 2026-03, import fix 2026-07-26).

---

## 2. What the integration exposes for the AC3220

### 2.1 Class chain and how entity lists are built

`PhilipsAC3220 -> PhilipsAC3210 -> PhilipsAC22xx -> PhilipsNew2GenericFan -> PhilipsGenericFanBase -> PhilipsGenericControlBase -> PhilipsEntity` (`philips.py:1179`, `1173`, `799`, `465`, `181`, `103`, `39`; mapping `FanModel.AC3220: PhilipsAC3220` at `philips.py:2250`). Added in commit `2a8bc9b` (2024-11-03, PR #183), originally as `PhilipsAC32xx`; renamed to the shared `PhilipsAC22xx` base in `978f306` (2026-01-28).

Each platform walks `reversed(model_class.__mro__)` and **concatenates** the `AVAILABLE_*` lists of every class (e.g. `select.py:37-39`); `getattr` also returns inherited values, so a subclass cannot remove an entry of its parent, only add. Sensors and filter sensors are created for every key of `SENSOR_TYPES` / `FILTER_TYPES` that is present in the **stored** status (`sensor.py:48`, `68-78`).

Static simulation result for `PhilipsAC3220` [V-sim]:

```
AVAILABLE_SELECTS  merged = ['D03110#2', 'D03135#1', 'D0312A#1', 'D03-42', 'D03-42']
   -> created (SELECT_TYPES order): ['D03135#1', 'D03-42', 'D0312A#1', 'D03110#2']
AVAILABLE_SWITCHES -> ['D03103', 'D03130', 'D03180']
AVAILABLE_LIGHTS   -> ['D03105#1']
AVAILABLE_NUMBERS / BINARY_SENSORS / HUMIDIFIERS / HEATERS -> []
KEY_PHILIPS_POWER = D03102, STATE_POWER_ON = 1, STATE_POWER_OFF = 0, KEY_OSCILLATION = None
```

(`#n` suffixes are an internal trick to have several descriptions for one device key; the platform strips everything from `#` before talking to the device.)

### 2.2 Reference status dump of a real AC3220/10

From issue #181 "Support for AC3220/AC3221" (tomasz-soltysik, 2024-11-04), device firmware `D01S12 = 0.1.9`, `WifiVersion = AWS_Philips_AIR_Combo@3.0`, state "Auto mode, light off, 1 PM2.5, 1 IAI, 47% humidity, 21.2 C" [R-issue; JSON relayed by WebFetch as verbatim]:

```json
{"D01102":0,"D01S03":"Salon","D01S04":"Unicorn","D01S05":"AC3220/10","D01107":0,"D01108":3,"D01109":3,
 "D0110A":0,"D0110C":19,"D01S0D":"688001001384","D0110F":3,"D01S12":"0.1.9","D01213":0,
 "ProductId":"<product_id A>","DeviceId":"<device_id A>",
 "otacheck":false,"Runtime":317641004,"rssi":-49,"wifilog":false,"blelog":false,"free_memory":154416,
 "WifiVersion":"AWS_Philips_AIR_Combo@3.0","StatusType":"status","ConnectType":"Online",
 "D03102":1,"D03103":0,"D03105":0,"D03106":1,"D0310A":2,"D0310C":0,"D0310D":1,"D03110":0,"D03211":0,
 "D03115":0,"D0311F":0,"D03120":1,"D03221":1,"D03224":212,"D03125":47,"D0312A":1,"D0312B":1,"D0312C":4,
 "D03130":100,"D03134":0,"D03135":0,"D03136":0,"D03240":0,"D03180":0,"D03182":1,
 "D03R81":"AAEBAQIBAgID\n","aqit_ext":0,
 "D05102":3,"D05207":720,"D05408":9600,"D0520D":621,"D0540E":9501}
```

Key naming [I, from the pattern of all keys above and the sentinel remark in PR #384]: `D` + 2-digit group (`01` device info, `03` control/sensors, `05` filters) + a type/size code (`1` = 1 byte, `2` = 2 bytes, `4` = 4 bytes, `S` = string, `R` = raw/base64) + 2 hex digits id. This matches e.g. `D03130 = 100` (1 byte), `D03224 = 212` (2 bytes), `D05408 = 9600` (4 bytes), `D01S05 = "AC3220/10"`. The older "NEW" generation uses the hyphenated form `D03-02`.

### 2.3 Entity table for an AC3220/10 (17 entities, one of them dead)

Unique-id prefix: `AC3220-<DeviceId>` (`philips.py:209-211`; `<model>` is the matched family key).

| # | Platform | Raw key | Meaning | Encoding / mapping | HA entity (translation key -> en / nl name) | Unit / device class / category | Unique-id suffix |
|---|---|---|---|---|---|---|---|
| 1 | fan | `D03102` | Power | `1` on, `0` off (`philips.py:495-497`) | main entity, name = device name (`_attr_name = None`, translation key `pap`) | features PRESET_MODE, SET_SPEED, TURN_ON, TURN_OFF | (none) |
|   |     | `D0310C` | Mode / manual speed | see 2.4 | presets + percentage of the fan | | |
| 2 | sensor | `D03120` | Indoor allergen index | int, as is (`const.py:621-624`) | `indoor_allergen_index` -> "Indoor allergen index" / "Binnen allergie-index" | no unit, no device class, `measurement`; icon `pap:iai` | `-d03120` |
| 3 | sensor | `D03221` | PM2.5 | int ug/m3 (`const.py:637-642`) | `pm25` -> "PM2.5" | `ug/m3` via deprecated `CONCENTRATION_MICROGRAMS_PER_CUBIC_METER`, `SensorDeviceClass.PM25`, `measurement` | `-d03221` |
| 4 | sensor | `D03125` | Relative humidity | int % (`const.py:660-665`) | `humidity` -> "Humidity" / "Luchtvochtigheid" | `%`, `HUMIDITY`, `measurement` | `-d03125` |
| 5 | sensor | `D03211` | Timer remaining | int minutes (`const.py:666-671`) | `time_remaining` -> "Time remaining" / "Resterende tijd" | `min`, `DURATION`, `measurement` | `-d03211` |
| 6 | sensor | `D03224` | Temperature | `value / 10` deg C (`const.py:683-694`) | `temperature` -> "Temperature" / "Temperatuur" | deg C, `TEMPERATURE`, `measurement`; dynamic mdi thermometer icon | `-d03224` |
| 7 | sensor | `rssi` | Wi-Fi RSSI | int dBm (`const.py:719-733`) | `rssi` -> "RSSI" | dBm, `SIGNAL_STRENGTH`, `measurement`, DIAGNOSTIC, enabled by default | `-rssi` |
| 8 | sensor | `D0540E` (total `D05408`) | Main (NanoProtect HEPA) filter remaining | `round(100 * D0540E / D05408)` -> 99 % in the dump; attributes `total`, `time_remaining` (hours, as string) (`const.py:818-826`, `sensor.py:193-229`) | `nanoprotect_filter` -> "NanoProtect filter" / "NanoProtect-filter" | `%`, DIAGNOSTIC, `measurement` | `-nanoprotect_filter` |
| 9 | sensor | `D0520D` (total `D05207`) | Pre-filter cleaning interval remaining | `round(100 * D0520D / D05207)` -> 86 % (`const.py:827-835`) | `pre_filter` -> "Pre-filter" / "Voorfilter" | `%`, DIAGNOSTIC, `measurement` | `-pre_filter` |
| 10 | switch | `D03103` | Child lock | on `1`, off `0` (`const.py:845-850`) | `child_lock` -> "Child lock" / "Kinderslot" | CONFIG | `-d03103` |
| 11 | switch | `D03130` | Beep | on `100`, off `0` (`const.py:851-856`) | `beep` -> "Beep" / "Pieptoon" | CONFIG | `-d03130` |
| 12 | switch | `D03180` | "Auto+ AI" | on `1`, off `0` (`const.py:862-866`) | `auto_plus` -> "Auto plus" | no category | `-d03180` |
| 13 | light | `D03105` (desc. `D03105#1`) | Display backlight | off `0`, "medium/low" `115`, on/bright `123`, auto `101` (`const.py:913-921`) | `display_backlight` -> "Display backlight" / "Achtergrondverlichting weergeven" | CONFIG; `ColorMode.BRIGHTNESS`; effect list `["auto"]` | `-d03105#1` |
| 14 | select | `D03135` (desc. `D03135#1`) | Lamp mode | `0` off, `1` air_quality, `2` ambient_light_mode (`const.py:500-504`, `948-952`) | `lamp_mode` -> "Lamp mode" / "Lampmodus" | CONFIG | `-d03135#1` |
| 15 | select | `D0312A` (desc. `D0312A#1`) | Preferred index shown on display | `0` indoor_allergen_index, `1` pm25 (`const.py:520-523`, `973-977`) | `preferred_index` -> "Preferred index" / "Voorkeursindex" | CONFIG | `-d0312a#1` |
| 16 | select | `D03110` (desc. `D03110#2`) | Off-timer | `0` "Off", `2` "1h", `3` "2h", ... `13` "12h" (`TIMER2_MAP`, `const.py:581-595`) | `timer` -> "Timer" | CONFIG | `-d03110#2` |
| 17 | select | **`D03-42`** | Preferred index of the *older* key generation | `"IAI"` / `"PM2.5"` strings (`const.py:534-537`, `968-972`) | second `preferred_index` entity (gets entity id suffix `_2`) | CONFIG | `-d03-42` |

Entity 17 is a defect: `PhilipsAC3210.AVAILABLE_SELECTS = [PhilipsApi.NEW_PREFERRED_INDEX]` (`philips.py:1176`) uses the hyphenated "NEW" key `D03-42`, which does not exist in the AC3220 status dump, and because lists are concatenated it is *added* to the AC22xx selects rather than replacing them. `current_option` then returns `str(None)` which is not in the options, so the entity is permanently `unknown` (`select.py:89-95`); selecting an option would send `{"D03-42": "IAI"}` to the device. The same list-accumulation defect was reported for AC4220 in unmerged PR #351 (`5f450f1`, 2026-03-20) [R-pr]. The tinkerologie fork carries the same `NEW_PREFERRED_INDEX` entry for AC3210/AC3220 (`tinkerologie_ha-philips-airpurifier/custom_components/philips_airpurifier/device_models.py:618-632`) [V-code].

Fan `extra_state_attributes` for New2 devices (`philips.py:468-489`): `name` (`D01S03`), `model_id` (`D01S05`), `product_id`, `device_id`, `software_version` (`D01S12`), `wifi_version`, `error_code` (`D03240`), `preferred_index` (`D0312A` through the gas map `0/1/2`), `runtime` (`Runtime` ms -> `str(timedelta)`). `runtime` changes with every status push, so every notification creates a new recorded fan state (issue #395 asks to exclude it) [V-code + R-issue].

Not exposed although present in the AC3220 status [V-code]: `D0310D` (actual fan speed; the sensor is commented out at `const.py:695-707`), `D03134` (standby sensors; a switch description exists at `const.py:857-861` but AC22xx does not list it), `D03137` (ambient light scene; AC3210 not listed), `D03240` error code as an entity, firmware as a sensor, filter reset actions, and the unidentified keys `D03106`, `D0310A`, `D03115`, `D0311F`, `D0312B`, `D0312C`, `D03136`, `D03182`, `D03R81`, `D05102`, `D011xx`.

No binary sensors, numbers, humidifier or climate entities for this model.

### 2.4 Presets and speeds: exact payloads

All from `PhilipsAC22xx` (`philips.py:802-841`). The dict shown is merged into the `desired` object; the plaintext sent (before encryption) is `{"state":{"desired":{"CommandType":"app","DeviceId":"","EnduserId":"", ...}}}` to `POST /sys/dev/control`.

| HA action | Keys written |
|---|---|
| `fan.turn_on` (no args) | `{"D03102": 1}` (`philips.py:260`) |
| `fan.turn_off` / percentage 0 | `{"D03102": 0}` (`philips.py:267`, `366-367`) |
| preset `auto` | `{"D03102": 1, "D0310C": 0}` |
| preset `sleep` | `{"D03102": 1, "D0310C": 17}` |
| preset `turbo` | `{"D03102": 1, "D0310C": 18}` |
| preset `medium` | `{"D03102": 1, "D0310C": 19}` |
| percentage 1-20 (`speed_1`) | `{"D03102": 1, "D0310C": 1}` |
| percentage 21-40 (`speed_2`) | `{"D03102": 1, "D0310C": 2}` |
| percentage 41-60 (`speed_3`) | `{"D03102": 1, "D0310C": 3}` |
| percentage 61-80 (`speed_4`) | `{"D03102": 1, "D0310C": 4}` |
| percentage 81-100 (`speed_5`) | `{"D03102": 1, "D0310C": 5}` |
| child lock on/off | `{"D03103": 1}` / `{"D03103": 0}` |
| beep on/off | `{"D03130": 100}` / `{"D03130": 0}` |
| Auto+ on/off | `{"D03180": 1}` / `{"D03180": 0}` |
| display light on / brightness 255 | `{"D03105": 123}` |
| display light brightness < 255 | `{"D03105": 115}` (`light.py:170-171`) |
| display light effect `auto` | `{"D03105": 101}` |
| display light off | `{"D03105": 0}` |
| lamp mode | `{"D03135": 0 or 1 or 2}` |
| preferred index | `{"D0312A": 0 or 1}` |
| timer | `{"D03110": 0, 2..13}` |

State readback: `preset_mode` is the first preset whose whole pattern equals the status (`philips.py:278-294`); `percentage` likewise over the speed patterns (`philips.py:347-361`), so in a preset the percentage is `None` and in a manual speed the preset is `None`.

Cross-check from a sibling model: issue #416 (AC4221/11, firmware 0.2.3, `AWS_Philips_AIR_Combo@86`, opened 2026-11-14) reports by diffing status against app actions: `D0310C` 0 = auto, 1-5 = manual speed, 17 = sleep, 18 = turbo, 19 = medium, **-16 when powered off**; `D0310D` follows 1-4, shows 18 for speed 5 and turbo, 3 for medium, 1 for auto/sleep; `D03105` 101 = Auto, 123 = Bright, 115 = Low, 0 = Off; `D03135` 0/1/2; `D03137` 1-4 scenes; `D03110` 0 = off, 2 = 1 h, 3 = 2 h with `D03211` = minutes [R-issue]. The same issue reports that on that firmware the lamp can be switched **off** via local CoAP but writes that should turn it on or change the scene are ignored, while fan, mode and child-lock writes work. Whether the AC3220 really has five manual speeds and whether its light is writable on current firmware is not confirmed anywhere I found.

---

## 3. Reliability weaknesses in this code

Each item: mechanism, where, and the user-visible symptom. W-numbers are referenced later.

### W1 - Entities never become unavailable while the entry is loaded; they show the last known values [V-code]

`philips.py:79-82` returns `self.coordinator.status is not None`; nothing ever sets `status` back to `None` (`coordinator.py` assigns it only at L36, L97, L138). A purifier that has been unplugged for a day still shows as available with yesterday's readings and its controls "work" optimistically (W4). The only path to `unavailable` is a failed/pending config-entry setup.

### W2 - After every restart or reload, a months-old status snapshot is shown as live state [V-code + R-issue #394]

`__init__.py:169-171` seeds the coordinator with `entry.data[CONF_STATUS]`, the dict saved when the entry was created (`config_flow.py:178`, `247`). It is never refreshed. Consequences:

- Entities start with stale values until the first notification arrives. Issue #394 (mbreitkreuz, 2026-10-09, AMF870/15 on `AWS_Philips_AIR_Combo@86`) measured about 3 min 25 s, 4 min 11 s, 3 min 1 s after three HA starts and about 30 s after a reload, with the fan shown "on, preset auto" from a snapshot dated 2024-09-29 while the device was actually off.
- `DeviceInfo.sw_version` and `model` come from the same snapshot (`philips.py:60-72`), so the device registry keeps the firmware version from the day of installation.
- Which sensors exist is decided from the snapshot (`sensor.py:48`, `68-78`; `binary_sensor.py:32`, `45`). Keys that appear after a firmware update never get entities until the entry is deleted and re-added.
- Entities mutate that dict in place before the first notification (`self._device_status[key] = value`), i.e. they modify the config entry's data object in memory without `async_update_entry`.

### W3 - No timeout on any CoAP request; a lost datagram blocks forever [V-code + V-dep + R-issue #363]

`aioairctrl/coap/client.py:83, 99, 130, 173` await `ctx.request(...).response`; all messages are NON (sent once), and aiocoap has no request timeout (`protocol.py:567`). The integration adds a timeout only around the very first `create()` (`__init__.py:148`) and in the config flow. Therefore:

- A command whose request or reply is lost never returns. Issue #363 (villeparamio, 2026-06-18, AC0950/10, v0.36.2) observed a `fan.set_preset_mode` call hanging about 1 h 46 min and then failing with `aiocoap.error.LibraryShutdown` when an unrelated reconnect tore the client down. A hanging entity service call also hangs the script/automation that issued it.
- The watchdog does not help: it is reset by notifications (`coordinator.py:139`), so while the device keeps pushing sensor updates it never fires.

### W4 - Command results are ignored and state is set optimistically [V-code]

`set_control_values` returns `False` after 6 rejected attempts (`client.py:187-188`), but all 28 call sites discard the return value and then write the requested value into the shared status dict (`philips.py:260-263`, `267-270`, `302-304`, `372-374`; `switch.py:93-95`, `99-101`; `light.py:181-183`, `188-190`; `select.py:110-112`; `number.py:112-114`). A command the device refused is displayed as applied until some later notification happens to contradict it. Only the calling entity is re-rendered, not other entities reading the same key.

### W5 - The only liveness mechanism is a 180 s silence watchdog that rebuilds the whole client [V-code + R-issue #396, #394]

- `MISSED_PACKAGE_COUNT = 3` x `_timeout = 60` (`coordinator.py:18`, `42-49`). `max_age` from the device is only applied in `async_first_refresh` (L97-100), which normal setups skip, so the period is always 180 s.
- The design assumes the device sends a notification at least every `max_age` seconds. Reports for current firmware say it only notifies on value changes (issue #394, unmerged PR #388 `0279bc8` "refresh observation without reconnecting client", unmerged PR #408 `ad1e725` "recover silent AMF870 and AC3420 status streams"). In standby with nothing changing, the watchdog then fires every 3 minutes, forever. The maintainer already noted in issue #205 (2024-11-24): "Some devices need polling to update data as push doesn't work, like CX3550" and proposed sending a beep-off write to provoke a status push; that was never implemented.
- Each firing does `client.shutdown()` + new aiocoap context + new UDP socket (new source port) + new `/sys/dev/sync` + new observe registration (`coordinator.py:80-83`).
- `CoAPClient.create()` in `_reconnect` has no timeout (L82). If the single sync datagram or its reply is lost, the task hangs until the *next* watchdog tick cancels it; the `CancelledError` is swallowed without logging (L85-88). Issue #396 (2026-10-12, packet capture on an AMF870/15) counted 32 of 403 reconnect syncs (7.9 %) unanswered, later 119 of 2,991 (4.0 %) over 13 days, with up to four in a row (about 12 minutes deaf). 31 of the first 32 never left the host because the kernel had no ARP entry and the purifier answered only about 61 % of broadcast ARP requests (versus 99.7 % of unicast ones). Debug signature: a `syncing` line without a matching `synced`.

Symptom: "works, then is deaf for 3 to 12 minutes with nothing in the log", most often when the purifier is idle - exactly when an automation wants to switch it on.

### W6 - `self.client` points at a dead context during and after a failed reconnect; unload can strand the entry in `failed_unload` [V-code + V-dep + R-issue #397 + R-pr #393]

- Between `await self.client.shutdown()` and the assignment of the new client (`coordinator.py:80-82`) every command goes to a shut-down aiocoap context and raises (issue #396 follow-up: four of six failed button presses raised `LibraryShutdown`). The window is milliseconds when sync succeeds and up to 180 s or more when it does not.
- `Coordinator.shutdown()` (L60-61) calls `self.client.shutdown()` unguarded. If the client was already shut down by `_reconnect`, aiocoap raises `AttributeError: 'NoneType' object has no attribute 'values'` (`aiocoap/messagemanager.py:77-82`), which propagates out of `async_unload_entry` (`__init__.py:200-201`). HA then sets `ConfigEntryState.FAILED_UNLOAD` (`homeassistant/config_entries.py`, state defined at L166), from which the entry cannot be reloaded; only an HA restart recovers. Reported as issue #397 (AC3210/12, v0.37, HA 2026.10.1); independently analysed in PR #393 (`eeeb816`) and patched minimally in PR #398 (`1e927f5`). Neither is merged.
- This is triggered by any reload during an outage: options flow, the DHCP flow updating the IP (`config_flow.py:147` reloads the entry), or the user pressing "Reload".

### W7 - The observe task dies silently on any exception [V-code + V-dep + R-issue #396]

`coordinator.py:134-141` has no error handling and the task has no done-callback. It ends when:

- the library raises while decoding a notification: `DigestMismatchException`, `ValueError` from `bytes.fromhex`/padding, `UnicodeDecodeError`, `json.JSONDecodeError` (`client.py:113-118`, `encryption.py:68-79`). Issue #396 logged a malformed notification containing NUL bytes about 16 times in ten days and 18 in 87,981 notifications later; issue #205 has `ValueError: non-hexadecimal number found in fromhex() arg at position 488`; issue #376 has `invalid literal for int() with base 16: '27AA\x00\x00\x00\x00'` (a sync reply padded with NULs reaching `int(self._client_key, 16)`). aioairctrl PR #14 (open since 2026-09-16) would skip unreadable notifications; aioairctrl PR #13 (open since 2026-06-20) would add observe timeouts.
- aiocoap reports a transport error or ends the observation (`ObservationCancelled`, `NetworkError`).
- **any entity's state property raises** inside `update_callback()` (L140-141). HA's `Entity.async_write_ha_state` does not catch exceptions from state calculation (`homeassistant/helpers/entity.py:1094-1104`, `1225-1250`) [V-dep], so one bad value (for example `KeyError` in `sensor.py:125` `self._device_status[self.kind]`, `TypeError` in `light.py:125` `int(None)`, `ZeroDivisionError` in `sensor.py:216` when a filter total is 0) aborts the loop: the remaining listeners are not updated and the stream stops.

Recovery is only the 180 s watchdog, after which the same payload can kill it again.

### W8 - The discovery flow opens a second session to an already configured device [V-code + R-issue #394/#396]

`async_step_dhcp` probes before it knows the device is configured (1.3). `get_status()` registers an observation (`client.py:98`). Issue #396 states (from packet captures) that the device keeps one observer per source IP and the newest observe GET wins, so the probe takes over the notification stream and then closes its socket; the running coordinator hears nothing until its watchdog re-registers (up to 3 minutes). Issue #394 attributes the multi-minute stale period after each HA start to this. Unmerged PR #389 (`beefb15`) adds an early abort when the IP matches an existing entry. In HA core `dev` the DHCP watcher re-processes a client only when its IP/hostname data changed (`homeassistant/components/dhcp/__init__.py:207-216`), so this hits at HA start and on address changes, not on every lease renewal [V-dep].

### W9 - Two sources of truth for the host [V-code]

`__init__.py:139` prefers `entry.options[CONF_HOST]` over `entry.data[CONF_HOST]`. The options flow writes options (`config_flow.py:351`); DHCP rediscovery and "add again with the new IP" write data (`config_flow.py:147`, `285`). Once a user has used the options flow, later automatic IP updates are stored but ignored, and the integration keeps talking to the old address.

### W10 - Slow or delayed recovery at startup [V-code + V-dep]

- One single-shot sync with a 25 s wait (`__init__.py:148`); a lost packet costs the full 25 s and raises `ConfigEntryNotReady`.
- HA retries with `min(2**tries * 5, 600)` s (`homeassistant/config_entries.py:834`, `SETUP_RETRY_MAX_WAIT = 600` at L146): 5, 10, 20, 40, 80, 160, 320, 600 s. After a long outage it can take up to about 10 minutes after the purifier is back before entities return.
- `getmac` runs before every setup attempt (`__init__.py:143`).

### W11 - No serialisation of commands; resync races [V-code, I for impact]

`set_control_values` has no lock. Two concurrent service calls interleave counter increments and, on a rejection, both call `_sync()` and overwrite each other's key (`client.py:165-186`). Notifications produced before a command took effect replace the optimistic dict (`coordinator.py:138`), so the UI can flip back and forth.

### W12 - Fragile dependency stack and release history [V-code + V-dep + R-issue]

- `aioairctrl==0.3.1` pulls `aiocoap>=0.4.17,<0.5` and unpinned `pycryptodomex`, Python >= 3.12. aiocoap is shared in-process with HA core's IKEA Tradfri integration (`pytradfri[async]==15.0.0` -> `aiocoap~=0.4.5`).
- aioairctrl <= 0.2.6 monkeypatched aiocoap process-wide (`aioairctrl/coap/aiocoap_monkeypatch.py` at tag v0.2.5).
- v0.35.0 (2026-01-31, `3eb702e`) set `AIOCOAP_CLIENT_TRANSPORT`/`AIOCOAP_SERVER_TRANSPORT=simple6` in `os.environ` at import time to fix IPv6-disabled hosts (issue #256, `OSError: [Errno 97]` from aiocoap's udp6 transport); that broke Tradfri (issue #322) and was reverted in `36b186e`, with the transport now hard-coded inside aioairctrl 0.3.1 (`client.py:48`).
- v0.36.0 (2026-03-01) shipped the invalid requirement `"aioairctrl=0.3.0"` (`5e62a64`), fixed the same day (`d7fbd02`, issue #331 "0.36.0 breaks integration").
- Issue #323 (2026-02): sockets leaked whenever the device was unreachable because the 25 s timeout cancelled `create()` mid-sync without closing the context; fixed in aioairctrl 0.3.x (`client.py:50-56`).

### W13 - Possible silent loss of notifications inside aiocoap [V-dep, impact unverified]

`aiocoap/protocol.py:700-708` drops notifications whose Observe value is not newer than the last one unless 128 s have passed. If the Philips firmware does not increase the Observe option monotonically, updates would be discarded with no log. Issue #394 notes that after 4 of about 43 commands the next update only arrived 120-222 s later; the cause was not determined. Needs a packet capture on the AC3220.

### W14 - Task and lifecycle hygiene [V-code]

Bare `asyncio.create_task` / `ensure_future` (`coordinator.py:71`, `150`; `timer.py:85`) instead of `entry.async_create_background_task`; cancelled tasks are not awaited (`coordinator.py:55`, `68`, `147`); `Timer.cancel()` can raise during shutdown (`timer.py:69-70`); a new timer task is created on every notification (`timer.py:75-80`).

### W15 - Model-definition defects relevant to the AC3220 [V-code / V-sim / R-issue]

- Dead `D03-42` select (2.3).
- `light.py:162-165`: if `effect` is supplied and is not `"auto"`, `value` is never assigned -> `UnboundLocalError` at L181.
- Timer options are literal strings `"Off"`, `"1h"` ... while `strings.json` only translates `off`/`on`.
- `strings.json` has the key `oscillaton` (typo) for the number platform.
- Light writes may be ignored by current firmware (issue #416, sibling model).

### Scenario walk-through (derived from the code paths above; timings are from the code, not measured)

| Scenario | What the code does | What the user sees |
|---|---|---|
| HA starts, device reachable | getmac, sync (single NON), coordinator seeded with the stored snapshot, platforms created, observe GET sent when the first entity is added. | Entities appear immediately with the snapshot values, then jump to live values when the first status arrives (immediately if the device answers the observe GET; otherwise after the first value change or after a watchdog cycle, W2/W5/W8). |
| HA starts, device offline | `create()` waits 25 s, `ConfigEntryNotReady`, HA backoff 5 s ... 600 s (W10). | Entry "retrying setup", entities unavailable; recovery up to about 10 min after the device returns. |
| Device loses power / reboots while HA runs | No notifications; after 180 s `_reconnect`: old client shut down, new sync. While the device is down each attempt hangs until the next tick. Commands sent before the first tick go to the still-open old client (hang if no reply, W3); after the first tick they go to a dead client and raise (W6). After the device is back, the next tick's sync succeeds. | Entities stay "available" with frozen values (W1). Commands hang or error. Recovery 0-180 s after the device is reachable again, longer if a sync is lost (W5). |
| Device gets a new IP | Reconnect attempts keep targeting the old IP. A DHCP discovery flow probes the new IP, matches the DeviceId, updates `entry.data[host]` and reloads - unless `entry.options[host]` exists (W9). The reload calls `shutdown()` on an already shut-down client (W6). | Frozen values; possibly `failed_unload` until HA restart; or silently still using the old IP. |
| Device idle (standby, nothing changing) on push-on-change firmware | Watchdog fires every 180 s and rebuilds the client each time (W5). | Mostly invisible, but each cycle has a window where commands fail and a chance of a lost sync (3+ min deaf). |
| Command while notifications keep flowing but the command's datagram is lost | `set_control_values` awaits forever; watchdog never fires (W3). | Service call never returns; script/automation stuck. |
| Device rejects a command 6 times | Returns `False`, ignored; optimistic value written (W4). | HA shows the new state, the device did not change. |
| Corrupt notification or sync reply | Exception ends the observe task or the command (W7; `int('27AA\x00...', 16)` in `encryption.py:39`). | Frozen values until the next watchdog cycle; or "Failed to perform the action ... invalid literal for int()". |
| Two commands at once (scene/script) | Unserialised counters and resyncs (W11). | Occasional rejected command and a retry; rarely a lost one. |

---

## 4. What the maintainers themselves say

Primary sources read directly from the repository [V-code]:

1. `README.md:18-20` ("Word of Caution", introduced in `331834a`, 2022-04-02, still there):
   > "Due to a bug in the Philips devices, this integration is rather instable. It might or might not work. Even if it seems ok at first, it might stop working after a while. Sometimes, a power cycle of the Philips device helps. Sometimes, only a power cycle and a Home Assistant restart together help. It is frustrating. Do not report this as an issue here. Nobody can help right now. @mhetzi contributed timer code to attempt reconnects if the device is not responsive. Sometimes, that helps. But not always. You've been warned."
2. `README.md:62`, added in the very commit that added AC3210/AC3220/AC3221 (`2a8bc9b`, 2024-11-03):
   > "Note: Some of these models seem to have a newer firmware that does not allow local connections anymore. If you buy the device with the intention to manage it via Home Assistant, make sure you can return it, if the integration doesn't work for you."
3. `README.md:24`: Philips' "proper API ... only works with the Philips cloud and it is not public".
4. `timer.py:1`: `"""Timer class to handle instable Philips CoaP API."""`
5. Commit `5e62a64` (2026-03-01): "Aioairctrl has been refactored significantly. Hopefully, that solves more problems than it creates. Please report any issues you observe."

Via issue pages [R-issue]: kongo09 in #323 said he was "a little bit out of my depth" regarding the socket leak; in #256 "I honestly don't know why" (IPv6-disabled failures); in #205 the polling quote above. Issues #376, #379 and #386 were closed by the stale bot (`.github/workflows/stale.yml`: stale after 60 days, closed 7 days later) without a maintainer reply.

Maintenance signal [V-code from git refs]: last master commit 2026-07-26. Unmerged PR heads that address reliability: #364 `a58a04b` (2026-06-18, command timeout + reconnect + one retry through the coordinator; reported closed by the stale bot), #387 `b2c104f` (await observer shutdown), #388 `0279bc8` (refresh observation without replacing the client), #389 `beefb15` (no duplicate discovery observers), #393 `ed68deb` (never raise from shutdown, drop dead client reference, forced timer cancel, 4 regression tests), #398 `1e927f5` (swallow shutdown errors), #408 `ad1e725` (status "wake" by toggling beep for AMF870/AC3420). Also #351 (duplicate selects), #377/#401 (deprecated unit constant).

A lead that needs independent verification: PR #384 `9c51731` (foXaCe, opened and closed unmerged on 2026-08-26, no review, no statement about hardware tests) vendors aioairctrl and adds, "reverse-engineered from the Philips Air+ app": a key exchange on `POST /sys/dev/info/tls` (client sends `{"type":"config_encrypt","random2":<1000-9999>,"pk":<RSA-1024 PEM>}`, device answers `random1` + RSA-encrypted `prekey`; secret = first 16 hex chars of `SHA256(<little-endian uint32 of random1 + random2 + prekey>)`), AES-GCM instead of AES-CBC when the device's discovery `option` field has bit 6 set, a +/-10 message-id freshness window, CoAP multicast discovery on `224.0.1.187:5683` at `/sys/dev/info` and `/sys/dev/info/encryption` with an AES-CBC encrypted `didt` field (key/IV from `MD5("JiangPan" + <local IP>)`), sentinel sensor values `255` (tvoc) / `65535` (others) meaning "no reading", and an SSDP matcher `urn:philips-com:device:DiProduct:1`. If true, this would be the mechanism behind "newer firmware that does not allow local connections". I only verified that the code exists in the PR ref.

---

## 5. HA code-quality gaps versus current standards [V-code unless noted]

| Area | State in kongo09 master |
|---|---|
| Runtime data | `hass.data[DOMAIN][entry.entry_id]` (`__init__.py:180`); no typed `ConfigEntry[...]` / `entry.runtime_data`. |
| Coordinator | Custom class; no `DataUpdateCoordinator`, no `CoordinatorEntity`, no `last_update_success`, no first refresh. |
| Availability | Constant `True` (W1). |
| Entity naming | `has_entity_name = True` and translation keys are used (good). Main fan uses `_attr_name = None` (good). |
| Entity descriptions | Plain dicts keyed by a mix of HA constants and a `FanAttributes` enum (`const.py:604-1096`); no `EntityDescription` dataclasses; `self.hass = hass` assigned in entity `__init__` (`philips.py:54`). |
| Errors | No `HomeAssistantError`/`ServiceValidationError`; raw aiocoap exceptions reach the user; `PARALLEL_UPDATES` not set. |
| Config flow | Options flow used for host; no `async_step_reconfigure`; `ConfigEntryNotReady` raised in flows; duplicated probe code three times; unique id only known after a network probe. |
| Unload | Per-platform `async_forward_entry_unload` loop ignoring results instead of `async_unload_platforms`; can raise (W6). |
| Diagnostics / repairs | None. |
| Tests / CI | Effectively none (43 lines); ruff + hassfest workflows exist. |
| Icons | Custom `pap:` icon set served through an injected frontend module plus an unauthenticated listing endpoint; the fan's `icon` property returns these (`philips.py:376-392`). Issue #386 reports all automatically derived icons disappearing while the integration is enabled (closed by stale bot, no analysis). |
| Recorder | Volatile `runtime` attribute on the fan, RSSI sensor enabled by default. |
| Deprecations that will break | `const.py:18` imports `CONCENTRATION_MICROGRAMS_PER_CUBIC_METER`, which HA core marks `DeprecatedConstantEnum(UnitOfDensity.MICROGRAMS_PER_CUBIC_METER, "2027.8")` (`homeassistant/const.py:836-837`) [V-dep] - once removed, the module import fails and the whole integration stops loading. `climate.py:104` uses `_attr_temperature_unit`, deprecated until 2027.11 (`homeassistant/components/climate/entity.py:276-278`) [V-dep]. Tracked upstream as issues #378 and #415, PRs #377/#401 unmerged. |
| Metadata | `hacs.json` minimum HA version wrong (1.2); `model.py:8` imports `boolean` from `xmlrpc.client`. |

---

## 6. Design implications for a new integration

1. Treat liveness as a first-class concern in the transport layer: per-request timeouts (2-5 s), bounded retries for sync / control / observe registration (NON needs application-level retransmission), and a cheap periodic probe (CoAP ping or a status GET every 30-60 s) so that "quiet" and "gone" can be told apart. The periodic unicast traffic also keeps the host's ARP entry fresh (issue #396).
2. Keep one long-lived UDP socket and re-register the observation on it; do not rebuild a client per recovery. Re-sync only when the device rejects a command.
3. Validate everything coming from the device: sync reply must be 8 hex chars (strip NULs), envelope digest must match, JSON must parse; drop bad notifications and keep the stream alive.
4. Supervise the receive task (catch, log, restart with backoff) and isolate entity callbacks from the receive loop.
5. Use `DataUpdateCoordinator` push (`async_set_updated_data`) with a fallback `update_interval`, `entry.runtime_data`, `CoordinatorEntity`; make entities unavailable after N missed probes; do a live first refresh at setup; never present cached state as current.
6. Store only identifiers in the entry (`host`, `device_id`, `mac`, `model`); build entities from the live status plus a per-model description; tolerate missing keys by returning `None`.
7. Send commands through one serialised coordinator method with timeout, confirmation and `HomeAssistantError` on failure; update state from the device's answer or the next push, not optimistically.
8. Discovery must not disturb a running session: match known devices by MAC before opening any CoAP exchange and update the host silently; keep a single source of truth for the host and offer a reconfigure step.
9. Consider a small purpose-built asyncio CoAP client (the protocol subset is NON GET/POST, tokens, Observe, Max-Age) to avoid aiocoap's missing request timeout, double-shutdown error, silent Observe-ordering drops and the dependency shared with HA's Tradfri integration.
10. AC3220 model definition: power `D03102`; mode `D0310C` (0 auto, 17 sleep, 18 turbo, 19 medium, 1-5 manual, -16 when off on a sibling); actual speed `D0310D`; sensors `D03120`, `D03221`, `D03125`, `D03224`/10, `rssi`; filters `D0540E`/`D05408` and `D0520D`/`D05207`; child lock `D03103`; beep `D03130` (0/100); Auto+ `D03180`; display `D03105` (0/115/123/101); lamp `D03135`; preferred index `D0312A`; timer `D03110` + `D03211`; standby sensors `D03134`. No `D03-42`.
11. Plan for firmware variance: detect capability at runtime, and keep room for a different handshake (PR #384 lead) or a cloud fallback.
12. Standard icons (`icons.json` with mdi), diagnostics with redaction, Dutch translations, tests against a fake device, volatile values kept out of state attributes.

## 7. Open questions

- Does a 2026-production AC3220/10 (current firmware, probably `AWS_Philips_AIR_Combo@86` or later) still accept the plain `JiangPan` AES-CBC sync, or does it require the `/sys/dev/info/tls` handshake described in PR #384?
- Does it answer an observe (re-)registration with a full status, and does it push periodically or only on change? What Max-Age does it send? Are its Observe sequence numbers monotonic?
- Is "one observer per source IP, newest wins" true for the AC3220?
- Does the AC3220 have five manual speeds (`D0310C` 1-5), and are `D03105`/`D03135`/`D03137` writable locally on current firmware?
- MAC OUI and DHCP hostname of the user's unit: is it matched by any of the five OUIs or `mxchip*`?
- Which integration and version the user actually runs (kongo09 v0.37 or the tinkerologie one), and what their log shows (`syncing` without `synced`, `LibraryShutdown`, `failed_unload`, stale values).
- Meaning of the unidentified AC3220 keys (`D03106`, `D0310A`, `D03115`, `D0311F`, `D0312B`, `D0312C`, `D03136`, `D03182`, `D03R81`, `D05102`, `D011xx`).

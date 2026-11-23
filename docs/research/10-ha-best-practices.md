# 10 - Home Assistant best practices (late 2026) for a local-push UDP/CoAP integration, and how to distribute it

Round 2, angle "HA best practices and distribution". Date of research: 2026-11-22.
Builds on round 1 (notes 01-06) and is aligned with round-2 note 09 (AC3220 capabilities). It does not
re-derive protocol or issue history.

## 0. Sources and evidence legend

All paths below are relative to the scratchpad
(`scratchpad`).

| Tag | Meaning |
|---|---|
| **[V-core]** | Read in a shallow sparse clone of `home-assistant/core` `dev`, commit `69d5ed2c` (2026-11-22, version `2026.12.0.dev0`), at `src10/ha_core/` |
| **[V-docs]** | Read in a clone of `home-assistant/contributors.home-assistant.io`, commit `9ebc60e` (2026-11-21), at `src10/ha_contrib/src/content/` (docs under `docs/`, blog under `blog/`) |
| **[V-olddocs]** | Read in the frozen clone of `home-assistant/developers.home-assistant` (last commit 2026-10-16) at `src10/ha_devdocs/` |
| **[V-hacs]** | Read in a clone of `hacs/documentation`, commit `4f06a5b` (2026-10-17), at `src10/hacs_docs/`, or in `https://raw.githubusercontent.com/hacs/default/master/integration` / `https://data-v2.hacs.xyz/integration/data.json` (saved in `dl10/`) |
| **[V-pypi]** | PyPI JSON API (`https://pypi.org/pypi/<pkg>/json`), saved in `dl10/` |
| **[V-code]** | Read in a cloned third-party repo under `src/` |
| **[R]** | Reported by a WebFetch summary of a GitHub page (model-written; quotes are as returned, treat as paraphrase-grade) |
| **[Inf]** | My inference from verified facts |

URL scheme of the current docs: rule pages are `https://contributors.home-assistant.io/core/quality-scale/<rule>/`
(confirmed by `RULE_URL` in `src10/ha_core/script/hassfest/quality_scale.py:104-108`), integration pages are
`https://contributors.home-assistant.io/core/integrations/<page>/`, Marketplace pages are
`https://contributors.home-assistant.io/marketplace/...`, blog posts are
`https://contributors.home-assistant.io/blog/YYYY/MM/DD/<slug>/`. Where I cite a docs file I give the repo path
and the URL it is published at.

---

## 1. Five things that changed in 2026 and that round 1 did not have

These change the "how to build and ship" answer materially.

1. **The developer docs moved.** `developers.home-assistant.io` was replaced on 2026-10-16 by
   `contributors.home-assistant.io` [V-olddocs `src10/ha_devdocs/README.md:5`: "As of October 16, 2026, the Home
   Assistant developer documentation lives at contributors.home-assistant.io ... It replaces
   developers.home-assistant.io, design.home-assistant.io, and data.home-assistant.io."]. Hassfest error messages
   already link there. Use the new site as the reference.

2. **HACS is now built into Home Assistant as the "Marketplace"** (HA 2026.11, Settings > Marketplace)
   [V-docs `docs/marketplace/index.md`: "It is built into Home Assistant starting with 2026.11, under Settings >
   Marketplace. It grew out of HACS ... and it uses the same catalog and the same `hacs.json` file."; and
   `docs/marketplace/how-it-works.md`: "The Marketplace is an integration in Home Assistant Core, `marketplace` ...
   It ships with Home Assistant 2026.11, and is set up by default." and "On the first start after the update, the
   Marketplace takes over a HACS installation"]. `marketplace` and `brands` exist as core components
   [V-core: `git ls-tree HEAD homeassistant/components/`]. Consequence: every HA 2026.11+ user can install a
   custom integration from a link without installing HACS first; the catalog is still `hacs/default`.

3. **`pytest-homeassistant-custom-component` is dead; core publishes `pytest-homeassistant`.**
   [V: `https://raw.githubusercontent.com/MatthewFlamm/pytest-homeassistant-custom-component/master/README.md`:
   "`homeassistant/core` now offers testing infrastructure into it's own package ...
   `pytest-homeassistant-custom-component`, this package, is now broken. Custom component developers should move
   to the centrally managed package."]. Last PHACC release 0.13.375 on 2026-10-25, tracking HA 2026.10.4 [V-pypi].
   `pytest-homeassistant` 2026.11.2 (2026-11-16) pins `homeassistant==2026.11.2`, and has beta releases
   (`2026.11.0b4` ... `b6`) [V-pypi]. README: `src10/ha_core/packages/pytest-homeassistant/README.md`.

4. **Custom integrations ship their own brand images** in `custom_components/<domain>/brand/` since HA 2026.3;
   the brands repo folder `custom_integrations/` is "Legacy" [V-docs `blog/2026-02-24-brands-proxy-api.md`;
   `https://raw.githubusercontent.com/home-assistant/brands/master/README.md` lines 18-19, 97-99]. HACS checks
   for the `brand` folder first [V-hacs `source/docs/publish/include.md:55-60`].

5. **Devices belong to exactly one config entry since HA 2026.8** [V-docs
   `blog/2026-07-21-device-registry-single-config-entry.md`: "Devices are no longer merged across integrations:
   a physical device supported by several integrations is now represented by one device per config entry"].
   Consequence: the new integration can run next to kongo09's or tinkerologie's for the same purifier without
   the device pages merging (useful for A/B testing; note both would still talk CoAP to the same device).

Other 2026 API changes that affect the code are collected in section 9.

---

## 2. Integration Quality Scale (IQS)

### 2.1 Status of the scale for custom integrations

- "The integration quality scale has no tiers for custom integrations, but its rules are still a good guide."
  [V-docs `docs/marketplace/guides/integrations.md:109`,
  https://contributors.home-assistant.io/marketplace/guides/integrations/]
- Hassfest does not validate `quality_scale.yaml` outside core: `validate_iqs_file` starts with
  `if not integration.core: return` [V-core `script/hassfest/quality_scale.py:2029-2032`]. The loader reports
  custom integrations as tier "custom" [V-olddocs `docs/core/integration-quality-scale/index.md`, "Custom" tier].
- Recommendation: keep a `quality_scale.yaml` in the integration folder as a self-audit and as preparation for a
  possible core submission, but do not put a `quality_scale` key in `manifest.json` (it has no effect for a
  custom integration). A new core integration needs all Bronze rules [V-docs
  `docs/core/integrations/create.md:28`].

### 2.2 The rules per tier (54 rules) and what they mean here

Rule list from [V-olddocs `docs/core/integration-quality-scale/_includes/tiers.json`]; the same 54 rule pages
exist on the new site [V-docs `docs/core/quality-scale/`]. "Matters" = how much it shapes this integration.

**Bronze (20)**

| Rule | Matters | Plan for this integration |
|---|---|---|
| `action-setup` | low | exempt: no custom actions (use entities) |
| `appropriate-polling` | medium | push integration; the only interval is the silence probe (section 3.2). Rule exempts push APIs |
| `brands` | yes | `brand/icon.png` (+ `logo.png`) in the integration folder |
| `common-modules` | yes | `coordinator.py`, `entity.py` |
| `config-flow-test-coverage` | yes | 100 % of `config_flow.py`, every path ends in create or abort |
| `config-flow` | yes | UI only; `data_description` for the host field; nothing in `options` at first |
| `dependency-transparency` | **key** | decides the library question (section 5). Exempt if there is no external dependency |
| `docs-actions`, `docs-triggers`, `docs-conditions` | low | exempt (none provided). The last two are new 2026 rules |
| `docs-high-level-description`, `docs-installation-instructions`, `docs-removal-instructions` | yes | README |
| `entity-event-setup` | low | exempt: entities use `CoordinatorEntity`, they do not subscribe themselves |
| `entity-unique-id` | yes | `f"{device_id}_{description.key}"` |
| `has-entity-name` | yes | `_attr_has_entity_name = True`; the fan gets `_attr_name = None` |
| `runtime-data` | yes | `type PurifierConfigEntry = ConfigEntry[PurifierCoordinator]` |
| `test-before-configure` | **key** | config flow must reach the device (plaintext `/sys/dev/info` + sync) |
| `test-before-setup` | **key** | see 3.3: the rule now explicitly allows "set up but unavailable" |
| `unique-config-entry` | yes | `async_set_unique_id(device_id)` + `_abort_if_unique_id_configured` |

**Silver (10)**

| Rule | Matters | Plan |
|---|---|---|
| `action-exceptions` | **key** | every failed command raises `HomeAssistantError`; bad input `ServiceValidationError` |
| `config-entry-unloading` | **key** | close the UDP transport, cancel tasks, deregister the observation |
| `docs-configuration-parameters` | low | exempt (no options flow) |
| `docs-installation-parameters` | yes | describe "Host" |
| `entity-unavailable` | **key** | the core of the user's complaint, see 3.4 |
| `integration-owner` | yes | `codeowners` |
| `log-when-unavailable` | **key** | once at info when lost, once at info when back, see 3.4 |
| `parallel-updates` | yes | `PARALLEL_UPDATES = 0` on read-only platforms, `1` on platforms with actions |
| `reauthentication-flow` | no | exempt: the protocol has no authentication |
| `test-coverage` | yes | > 95 % |

**Gold (21)**

| Rule | Matters | Plan |
|---|---|---|
| `devices` | yes | one device per entry, full `DeviceInfo` |
| `diagnostics` | **key** | the tool for the next reliability report; redact ids |
| `discovery`, `discovery-update-info` | yes | DHCP matchers + `registered_devices`; update host on IP change |
| `docs-data-update`, `docs-known-limitations`, `docs-troubleshooting`, `docs-supported-devices`, `docs-supported-functions`, `docs-examples`, `docs-use-cases` | yes | README sections (push + silence probe, UDP fragmentation, VLANs) |
| `dynamic-devices`, `stale-devices` | no | exempt: "Integrations with a single, fixed device per config entry ... are exempt" |
| `entity-category` | yes | config for child lock/display/beep, diagnostic for filter, RSSI, error |
| `entity-device-class` | yes | PM2.5, humidity, temperature, duration, signal strength |
| `entity-disabled-by-default` | yes | RSSI, actual speed level, raw diagnostics |
| `entity-translations`, `exception-translations`, `icon-translations` | yes | `translations/en.json` (+ `nl.json`), `icons.json` |
| `reconfiguration-flow` | yes | `async_step_reconfigure` to change the host |
| `repair-issues` | optional | e.g. "device answers sync but never sends status" (fragmentation/firewall hint) |

**Platinum (3)**

| Rule | Matters | Plan |
|---|---|---|
| `async-dependency` | yes | everything is asyncio |
| `inject-websession` | no | exempt: "If the integration makes no HTTP requests ... this rule does not apply" |
| `strict-typing` | yes | `mypy --strict`, `py.typed` in the library |

Exemption wording quoted from the rule pages' "exceptions" sections [V-docs `docs/core/quality-scale/<rule>.md`].

### 2.3 `quality_scale.yaml` example (complete: hassfest in core rejects a file with a missing rule)

Format from [V-docs `docs/core/quality-scale/quality-scale-file.md`,
https://contributors.home-assistant.io/core/quality-scale/quality-scale-file/]: statuses `done`, `todo`,
`exempt` (comment required).

```yaml
rules:
  # Bronze
  action-setup:
    status: exempt
    comment: The integration does not provide custom actions.
  appropriate-polling:
    status: exempt
    comment: Push based (CoAP Observe). The only timer is a liveness probe after a period of silence.
  brands: done
  common-modules: done
  config-flow-test-coverage: done
  config-flow: done
  dependency-transparency: done   # or exempt while the protocol code is vendored (no external dependency)
  docs-actions:
    status: exempt
    comment: No custom actions.
  docs-triggers:
    status: exempt
    comment: No triggers.
  docs-conditions:
    status: exempt
    comment: No conditions.
  docs-high-level-description: done
  docs-installation-instructions: done
  docs-removal-instructions: done
  entity-event-setup:
    status: exempt
    comment: Entities are CoordinatorEntity based and do not subscribe to events themselves.
  entity-unique-id: done
  has-entity-name: done
  runtime-data: done
  test-before-configure: done
  test-before-setup: done
  unique-config-entry: done
  # Silver
  action-exceptions: done
  config-entry-unloading: done
  docs-configuration-parameters:
    status: exempt
    comment: No options flow.
  docs-installation-parameters: done
  entity-unavailable: done
  integration-owner: done
  log-when-unavailable: done
  parallel-updates: done
  reauthentication-flow:
    status: exempt
    comment: The local protocol has no authentication.
  test-coverage: done
  # Gold
  devices: done
  diagnostics: done
  discovery-update-info: done
  discovery: done
  docs-data-update: done
  docs-examples: done
  docs-known-limitations: done
  docs-supported-devices: done
  docs-supported-functions: done
  docs-troubleshooting: done
  docs-use-cases: done
  dynamic-devices:
    status: exempt
    comment: One fixed device per config entry.
  entity-category: done
  entity-device-class: done
  entity-disabled-by-default: done
  entity-translations: done
  exception-translations: done
  icon-translations: done
  reconfiguration-flow: done
  repair-issues: todo
  stale-devices:
    status: exempt
    comment: One fixed device per config entry.
  # Platinum
  async-dependency: done
  inject-websession:
    status: exempt
    comment: The integration makes no HTTP requests (UDP/CoAP only).
  strict-typing: done
```

---

## 3. Architecture for a push device that is often silent

### 3.1 What the docs prescribe for push

[V-docs `docs/core/integrations/fetching-data.md:142-153`,
https://contributors.home-assistant.io/core/integrations/fetching-data/]:

> "A coordinator also works for push APIs. Leave out `update_interval`, so it never polls, and call
> `async_set_updated_data` when new data arrives ... If the coordinator also polls, this resets the time until
> the next poll."

Source of that last sentence [V-core `homeassistant/helpers/update_coordinator.py:657-672`]:

```python
    @callback
    def async_set_updated_data(self, data: _DataT) -> None:
        """Manually update data, notify listeners and reset refresh interval."""
        self._async_unsub_refresh()
        self._debounced_refresh.async_cancel()

        self.data = data
        self.last_update_success = True
        ...
        if self._listeners:
            self._schedule_refresh()

        self.async_update_listeners()
```

### 3.2 Design decision D1: the coordinator's `update_interval` is the silence watchdog

[Inf, resting on the code above.] Give the coordinator an `update_interval` of N seconds (for example 60-120 s)
and call `async_set_updated_data()` for every decrypted notification. Because each push re-arms the timer,
`_async_update_data()` only runs after N seconds **without** a push. That method is therefore exactly the
"explicit liveness probe after silence" that openHAB/ioBroker added (round 1), with none of kongo09's "rebuild
the client every 180 s" or tinkerologie's "renew every 60 s with a 10 s deadline" behaviour:

- `_async_update_data()` = probe: `POST /sys/dev/sync` with a timeout and a small retry budget (round 1: sync
  and control keep answering when status GETs are ignored). Optionally refresh the Observe registration on the
  same socket. It must not require a status payload.
- Probe succeeded, no new status: return `self.data` unchanged. Create the coordinator with
  `always_update=False` so an unchanged value does not write states [V-docs fetching-data.md: "set
  `always_update=False` when creating the DataUpdateCoordinator to avoid unnecessary callbacks"; needs `__eq__`
  on the data class].
- Probe failed after retries: raise `UpdateFailed` (or `UpdateFailedUnreachable`, see 3.4). All
  `CoordinatorEntity` entities become unavailable through `last_update_success` [V-core
  `update_coordinator.py:752`]. The coordinator keeps probing on its interval and logs recovery itself.
- Pass `config_entry=entry` to the coordinator constructor (core enforces it; for custom integrations it is
  only ignored today) [V-core `update_coordinator.py:110-123`].
- The timer only runs while entities listen (`if self._listeners`), which is always the case here.

This keeps one single place that decides availability, and it is the place HA's own machinery expects.

### 3.3 Design decision D2: setup must not depend on receiving a status payload

Current rule text [V-docs `docs/core/quality-scale/test-before-setup.md:51-53`,
https://contributors.home-assistant.io/core/quality-scale/test-before-setup/]:

> "### Devices that are often offline — Some devices are offline on purpose ... Raising `ConfigEntryNotReady`
> and letting Home Assistant retry is usually still the simplest approach. But you can also finish the setup
> without reaching the device. Refresh the coordinator with `await coordinator.async_refresh()`, which does not
> raise, and the entities stay unavailable until the device answers. ... Until then, `coordinator.data` is
> still `None`, so code that reads it while setting up the platforms has to handle that. Fetch anything you
> could not get during setup, like device information, once the device is back."

(The frozen docs said the same with the options named "Defer setup" and "Continue setup"
[V-olddocs `docs/core/integration-quality-scale/rules/test-before-setup.md:18-21`].)

`entity-unavailable` adds the distinction that matters for this firmware [V-olddocs
`.../rules/entity-unavailable.md:11-14`]: "If we can't fetch data from a device or service, we should mark it
as unavailable ... If we can successfully fetch data but are temporarily missing a few pieces of data, we
should mark the entity state as unknown instead."

Resulting three-state model [Inf]:

| Situation | Config entry | Entities |
|---|---|---|
| Sync answered and a status has been received | loaded | available, values known |
| Sync answered, no status yet (the "@86 answers nothing until the next change" case) | loaded | **available, state unknown** for values not yet known (or last known values kept at runtime) |
| Sync not answered after retries (device unplugged, wrong IP) | loaded (D2a) or setup-retry (D2b) | unavailable |

- **D2a (recommended): continue setup.** Store model, device id and name in `entry.data` during the config flow
  (they come from the plaintext `/sys/dev/info`, round 1), so entities and `DeviceInfo` can be created without
  the device. In `async_setup_entry`: create client and coordinator, `await coordinator.async_refresh()`, set
  `entry.runtime_data`, forward platforms. One code path handles "unreachable" at start and at runtime; the
  entry does not flap between `SETUP_RETRY` and `LOADED` when a purifier is unplugged for a season.
- **D2b (also conformant): `ConfigEntryNotReady` only when the liveness probe fails**, never because a status
  did not arrive. Bonus: "Even without changes, a discovery reloads an entry that is waiting to retry its
  setup: the device is evidently online again." [V-docs `docs/core/integrations/config-flow.md:125`]. Do not
  log before raising ("Home Assistant already reports these exceptions, and for `ConfigEntryNotReady` it would
  log on every retry" [V-docs test-before-setup.md:49]).
- Either way use `ConfigEntryError` only for permanent conditions (for example the device id at that IP is a
  different device: the WiZ integration raises `ConfigEntryNotReady` with `translation_key="unexpected_device"`
  in that case [V-core `homeassistant/components/wiz/__init__.py:77-91`]).
- Core precedent for push over UDP plus a poll: WiZ uses `update_interval=timedelta(seconds=15)` and calls
  `coordinator.async_set_updated_data(...)` from the push callback [V-core `wiz/__init__.py:107-116`,
  `wiz/coordinator.py:46-58`].

Core integrations must now return `None` from `async_setup_entry`/`async_unload_entry` and raise instead of
returning `False`; "Custom integrations can keep returning a boolean." [V-docs
`blog/2026-10-23-config-entry-methods-return-none.md`]. `async_unload_platforms_or_raise` is new in 2026.11;
if the minimum HA version is 2026.11 use the new pattern, it is the direction of travel.

### 3.4 Availability and logging

- Rule `log-when-unavailable`: "log once when unavailable and once when back connected", "Logging should
  happen at `info` level" [V-olddocs `.../rules/log-when-unavailable.md:2,18-20`].
- With the probe in `_async_update_data` this comes for free from HA 2026.12: raise
  `UpdateFailedUnreachable(translation_domain=DOMAIN, translation_key="update_unreachable")`; the coordinator
  logs "`<name> is unavailable: <message>`" once at info and "`Fetching <name> data recovered`" at info
  [V-docs `blog/2026-11-13-update-failed-unreachable.md`; V-core `update_coordinator.py:62-67, 549, 614`].
  On HA 2026.11 plain `UpdateFailed` logs the first failure at **error** level (the blog post explains this is
  why the new class exists).
- Pitfall: `coordinator.async_set_update_error(err)` logs at error level ("Error requesting %s data")
  [V-core `update_coordinator.py:649-655`]. Do not use it to report "device went quiet"; let the probe decide.
- A push that arrives while the coordinator is in the failed state sets `last_update_success = True` silently
  (debug log only) [V-core `update_coordinator.py:664-668`]; log the "back online" info line yourself in that
  path so the pair of messages stays complete.
- Never mark entities unavailable just because no push arrived: silence is normal on this firmware (round 1).

### 3.5 Commands, exceptions, parallelism

- Rule `action-exceptions` [V-olddocs `.../rules/action-exceptions.md`]: "When the problem is caused by
  incorrect usage ... we should raise a `ServiceValidationError`. When the problem is caused by an error in the
  service action itself (for example, a network error ...) we should raise a `HomeAssistantError`." and "Platform
  actions (for example, switching a `switch` or turning on a `light`) count towards this rule as well".
- Rule `exception-translations`: `raise HomeAssistantError(translation_domain=DOMAIN,
  translation_key="command_failed", translation_placeholders={...})` with the text under `"exceptions"` in the
  translation file. Core example in a fan platform: SwitchBot
  [V-core `homeassistant/components/switchbot/fan.py:165-168`].
- Every command needs a deadline and bounded retries inside the client (round 1: no timeout exists in aiocoap
  for NON; issue #363 hung for 1 h 46 min). Translate `TimeoutError`/protocol errors at one place
  (a small decorator or `coordinator.async_send()`), never let library exceptions reach the user.
- Rule `parallel-updates` [V-olddocs `.../rules/parallel-updates.md`]: "you can set `PARALLEL_UPDATES = 0` for
  read-only platforms (`binary_sensor`, `sensor`, ...)" and "A coordinator only centralizes the inbound data
  updates; it does not limit outbound action calls." Use `PARALLEL_UPDATES = 1` in `fan.py`, `switch.py`,
  `select.py`, `number.py`, `light.py`, `button.py` (the encryption counter is shared mutable state, round 1),
  and additionally an `asyncio.Lock` in the client. Core examples: VeSync fan `PARALLEL_UPDATES = 1`
  [V-core `vesync/fan.py:49`].
- After a successful command, merge the written keys into the coordinator data and call
  `async_set_updated_data` (optimistic), then let the device's own push confirm. Do not call
  `async_request_refresh()` to "read back": a status GET may not be answered on this firmware.

### 3.6 Entities

- `entity.py`: `class PurifierEntity(CoordinatorEntity[PurifierCoordinator])` with `_attr_has_entity_name = True`,
  `_attr_device_info`, and `_attr_unique_id = f"{device_id}_{description.key}"`.
- `EntityDescription` pattern with frozen, keyword-only dataclasses carrying `value_fn` and `exists_fn`, as in
  VeSync [V-core `vesync/sensor.py:96-113`: `value_fn=lambda device: device.state.filter_life`,
  `exists_fn=lambda device: rgetattr(device, "state.filter_life") is not None`]. `exists_fn` lets the entity set
  follow the keys the device actually reports (round-2 note 09 lists them).
- Names: `translation_key` per entity; an entity on `binary_sensor`, `button`, `number`, `sensor` "with a device
  class needs no translation key when the name of the device class fits" [V-docs
  `docs/core/quality-scale/entity-translations.md:47`]. The main feature (the fan) uses `_attr_name = None`
  [V-docs `docs/core/quality-scale/has-entity-name.md:38-45`; V-core `vesync/fan.py:113`,
  `switchbot/fan.py:243-244`].
- Icons in `icons.json`, including per-preset icons under `state_attributes.preset_mode.state`
  [V-docs `docs/core/quality-scale/icon-translations.md:11-13`; V-core `switchbot/icons.json`: `"air_purifier":
  {"default": "mdi:air-purifier", "state": {"off": "mdi:air-purifier-off"}, "state_attributes": {"preset_mode":
  {"state": {"auto": "mdi:auto-mode", ... "sleep": "mdi:power-sleep"}}}}`].
- **Translations in a custom integration**: no `strings.json`; ship `translations/en.json` (complete) and
  `translations/nl.json`; "References do not work in these files: nothing replaces them, so users see the raw
  `[%key:...%]` text. Write out every string in full." [V-docs `docs/core/integrations/translations.md:335-350`].
  (kongo09 and tinkerologie both carry a `strings.json`, which is unnecessary.)
- Entity categories: `EntityCategory.CONFIG` for child lock, display brightness, beep, Auto+, preferred index,
  lamp mode; `EntityCategory.DIAGNOSTIC` for filter life, RSSI, error code, firmware. Disabled by default
  (`entity_registry_enabled_default=False`): RSSI, actual speed level, runtime counters.
- New in 2026.11: an entity is no longer removed and re-added when its `entity_id` is renamed; custom
  integrations that implement `async_added_to_hass`/`async_will_remove_from_hass` must implement
  `async_entity_id_changed` to opt in, and the old behaviour is removed in 2027.11
  [V-docs `blog/2026-10-12-new-entity-lifecycle-hooks.md`]. Plain `CoordinatorEntity` subclasses that do not
  key anything on their own `entity_id` only need a trivial implementation; check this when writing `entity.py`.

### 3.7 Device registry

Fields [V-docs `docs/core/integrations/device-registry.md:25-39`]: `identifiers`, `connections`, `name`,
`manufacturer`, `model`, `model_id`, `serial_number`, `sw_version`, `hw_version`, `configuration_url`,
`via_device_id`.

| Field | Value for the AC3220 | Source key (round 1 / note 09) |
|---|---|---|
| `identifiers` | `{(DOMAIN, device_id)}` | `DeviceId` / `device_id` from `/sys/dev/info` |
| `connections` | `{(CONNECTION_NETWORK_MAC, format_mac(mac))}` when the MAC is known | not in any payload; only from DHCP discovery (see 3.8) |
| `manufacturer` | `"Philips"` | constant |
| `model` | product name, e.g. "PureProtect 3200 series" or `D01S04`-derived | `name`/`type` |
| `model_id` | `"AC3220/10"` | `D01S05` / `modelid` |
| `serial_number` | only if a real serial is exposed (candidate `D01S0D`, unverified) | open question |
| `sw_version` | `D01S12` (e.g. "0.2.3") | status; update on change |
| `hw_version` | Wi-Fi module firmware (`WifiVersion`, e.g. "AWS_Philips_AIR_Combo@86") is firmware, not hardware: better a diagnostic sensor/diagnostics field than `hw_version` | judgement |

2026.11-2026.12 changes [V-docs `blog/2026-10-13-device-info-class.md`, `blog/2026-11-19-device-info-mapping.md`,
`blog/2026-11-10-device-info-constants.md`]: `DeviceInfo` is a dataclass; build it with keyword arguments and
read/write attributes; dict-style use (`device_info["sw_version"]`, `.get()`, `.update()`, `**device_info`) is
deprecated in 2026.12 and "will stop working in 2027.12"; the `ATTR_SW_VERSION`, `ATTR_MODEL`, ... constants in
`homeassistant.const` are removed in 2027.12 [V-core `homeassistant/const.py:388-403`]; `via_device` (tuple) is
replaced by `via_device_id` (2027.8). To update the firmware version after setup use
`dr.async_get(hass).async_update_device(device.id, sw_version=...)` from the coordinator.

### 3.8 Discovery, unique id, reconfigure

- Unique id rules [V-docs `docs/core/integrations/config-flow.md:127-136`]: "It must be a string, stable, and
  not something the user can change. Good: a serial number, a MAC address formatted with `format_mac`, a unique
  identifier printed on the device or burned into it ... Never: an IP address, a device name, a URL, or a
  hostname the user can change." and "Get the MAC address from the device API or from discovery. Tools that read
  the ARP cache, like `getmac`, do not work in every network setup Home Assistant runs in." -> use the
  device id from `/sys/dev/info`; do **not** depend on `getmac` (kongo09 requires `getmac>=0.9.4`
  [V-code `src/kongo09_philips-airpurifier-coap/custom_components/philips_airpurifier_coap/manifest.json`]).
- DHCP manifest matchers [V-docs `docs/core/integrations/manifest.md:300-316`]: "`hostname` must be lowercase,
  and `macaddress` (the first part of the MAC address, without colons) must be uppercase and contain a
  wildcard"; "A matcher with `"registered_devices": true` matches devices that your integration already
  registered in the device registry with a MAC address connection. Use it to learn about new IP addresses of
  known devices". Existing matcher sets to start from: `{"hostname": "mxchip*"}` and OUIs `047863*`, `6879C4*`,
  `80A036*`, `849DC2*`, `88A68D*`, `B0F893*`, `D0BAE4*` [V-code
  `src/mrverrall_philips-heater-coap/custom_components/philips_heater_coap/manifest.json`; kongo09 and
  tinkerologie manifests carry subsets]. Which OUI/hostname the user's AC3220 uses is unverified.
- The DHCP step [V-docs `docs/core/integrations/config-flow.md:151-185`]: a discovery step must "Make sure no
  other flow is already setting up the same device", "Make sure the device is not already set up", and "Always
  ask the user to confirm. A discovery step must never create an entry by itself." Flow for this device:
  1. `async_step_dhcp(discovery_info: DhcpServiceInfo)` (`ip`, `hostname`, `macaddress` lowercase without
     colons [V-docs `docs/core/integrations/discovery.md:57`]).
  2. If a config entry's device has this MAC: update host and abort (covers `registered_devices`).
  3. Otherwise one plaintext `GET /sys/dev/info` with a short timeout. No answer or unsupported model ->
     `async_abort(reason="not_supported"/"cannot_connect")`. This keeps the flow from offering every MXCHIP
     device on the network (the same matchers fire the kongo09, tinkerologie and heater integrations).
  4. `await self.async_set_unique_id(device_id)`;
     `self._abort_if_unique_id_configured(updates={CONF_HOST: ip, CONF_MAC: mac})`
     ("If the data changed, Home Assistant updates the entry and reloads it" [config-flow.md:118-123]).
  5. `async_step_discovery_confirm` with `self._set_confirm_only()`.
- Getting the MAC when the user adds the device by IP: `dhcp.async_discovered_service_info(hass)` "returns the
  devices that are still in the DHCP cache, as `DhcpServiceInfo` objects with `ip`, `hostname`, and
  `macaddress`" [V-docs `docs/core/integrations/network-discovery.md:56-65`; V-core
  `homeassistant/components/dhcp/helpers.py:41`]. Look the IP up there (add `"dhcp"` to `dependencies`), store
  the MAC in `entry.data` when found, otherwise leave `connections` empty until a DHCP discovery supplies it.
  The same helper can be used at runtime to find the new IP of a known MAC when the device stops answering
  (the heater integration added "recover heaters after DHCP address changes" on 2026-11-05 [V-code git log]).
- Deprecation trap: "using a config entry listener together with any reloading methods in a config flow is
  deprecated and will result in an error from 2026.12" [V-olddocs
  `blog/2026-05-07-config-entry-listener-together-with-reloading-methods.md`]. Do not register an
  `add_update_listener` that reloads **and** call `_abort_if_unique_id_configured(updates=...)` /
  `async_update_reload_and_abort`. Simplest: no update listener at all.
- Reconfigure [V-docs `docs/core/integrations/reauth-reconfigure.md:121-160`]: `async_step_reconfigure`,
  `entry = self._get_reconfigure_entry()`, probe the new host, `await self.async_set_unique_id(device_id)`,
  `self._abort_if_unique_id_mismatch()`, `return self.async_update_reload_and_abort(entry,
  data_updates=user_input)`.
- Always pass `step_id` to `async_show_form` (required from 2027.5) [V-docs
  `blog/2026-10-23-flow-results-require-step-id.md`]; do not use `show_advanced_options` (removed 2027.6)
  [V-olddocs `blog/2026-05-26-advanced-mode-config-flow-deprecation.md`; V-core
  `homeassistant/data_entry_flow.py:708`].
- Abort reasons `already_in_progress`, `reconfigure_successful` are translated centrally since 2026.10 when the
  helpers raise them [V-olddocs `blog/2026-09-28-central-config-flow-abort-reasons.md`]; `already_configured`,
  `cannot_connect`, `not_supported` need full text in `translations/en.json` (no `[%key%]` references).

### 3.9 Diagnostics and repairs

- `diagnostics.py` with `async_get_config_entry_diagnostics`; "Users share these files in public issues, so
  redaction is part of the rule" [V-docs `docs/core/quality-scale/diagnostics.md:11-35`], using
  `async_redact_data(data, TO_REDACT)`. Redact `DeviceId`, `ProductId`, the device name (`D01S03`), serial-like
  fields and the MAC. Include what is needed to debug this device family: last raw status, firmware and Wi-Fi
  version, time since last push, number of probes sent/failed, re-registrations, command timeouts, sync counter
  resyncs, undecryptable datagrams.
- Repairs: since 2026.11 an issue can be linked to its entry with `config_entry_id=entry.entry_id` and is
  deleted with the entry [V-docs `blog/2026-10-28-issue-registry-refresh.md`]. Candidate issue: "the device
  answers but no status has ever been received" (points to UDP fragmentation/VLAN/firewall documentation).

---

## 4. Modelling the purifier

### 4.1 Fan entity

Current page [V-docs `docs/core/entities/fan.mdx:73-77`, https://contributors.home-assistant.io/core/entities/fan/]:

> "A preset is a mode where the fan controls its own speed, or does something else on its own. Common examples
> are `auto`, `smart`, `eco`, and `breeze`. When no preset is active, `preset_mode` must be `None`."
>
> "Named manual speeds are not presets: represent them as percentages. Setting a speed by hand must end the
> active preset. If the device lets you set a speed while a preset stays active, represent that preset with a
> separate switch instead."

and (`fan.mdx:56-69`) "`speed_count` ... The number of speeds the fan has. Home Assistant uses it to calculate
`percentage_step`"; convert with `ordered_list_item_to_percentage` / `percentage_to_ranged_value` from
`homeassistant.util.percentage`. The frozen page said the same in older words
[V-olddocs `docs/core/entity/fan.md:24-30`].

Features: `PRESET_MODE`, `SET_SPEED`, `TURN_ON`, `TURN_OFF` (plus `OSCILLATE`, `DIRECTION`, not applicable).

How current core integrations model purifiers [V-core]:

| Integration | Features | Presets | Speed |
|---|---|---|---|
| VeSync (`vesync/fan.py:107-113, 172-196, 206-214`, `vesync/const.py:41-47`) | SET_SPEED, PRESET_MODE, TURN_ON, TURN_OFF | `auto`, `sleep`, `turbo`, `pet`, `normal`, `eco`; "manual" is not a preset | `speed_count = len(fan_levels)`, `percentage` from the level with `ordered_list_item_to_percentage`; returns `None` outside manual on legacy models; `preset_mode` is `None` in manual |
| SwitchBot air purifier (`switchbot/fan.py:232-262`, `strings.json`) | PRESET_MODE, SET_SPEED, TURN_ON, TURN_OFF | `auto`, `level_1`, `level_2`, `level_3`, `pet`, `sleep` (levels as presets, against the letter of the doc) | `percentage` from the library |
| Xiaomi Miio purifiers (`xiaomi_miio/fan.py:156-171, 347-431`) | mostly PRESET_MODE only (`speed_count = 1`); MIOT models add SET_SPEED with `speed_count = 3` | "Auto", "Silent", "Favorite", "Fan" (capitalised legacy) | favourite level as a separate `number` |
| LG ThinQ (`lg_thinq/fan.py:55-57, 114-134`) | SET_SPEED, TURN_ON, TURN_OFF, PRESET_MODE when "auto" exists | `["auto"]` only | named speeds as ordered list |

Recommendation for the AC3220 (consistent with round-2 note 09, section on the fan entity):

- `_attr_name = None`, `_attr_translation_key = "purifier"`,
  `supported_features = PRESET_MODE | SET_SPEED | TURN_ON | TURN_OFF`.
- **Variant A (recommended, same as note 09):** `preset_modes = ["auto", "sleep", "medium", "turbo"]`
  (lower-case keys, translated in `entity.fan.purifier.state_attributes.preset_mode.state`). These are the
  device's own mode-button positions (`D0310C` = 0/17/19/18), distinct on the wire and on the display from
  manual speeds 1-5. VeSync's `turbo` preset and SwitchBot's level presets are core precedents, and existing
  automations written for kongo09's integration use these preset names.
- **Variant B (strict reading of the current page):** only `auto` and `sleep` are presets in the sense "the fan
  controls its own speed, or does something else on its own" (sleep also switches the display off). Medium and
  Turbo are fixed speeds (note 09: `D0310D` reads 3 in Medium and the top level in Turbo), i.e. "named manual
  speeds", and would be reported as 60 % and 100 % with `preset_mode = None`. A core reviewer could ask for B.
- Keep the mode table data-driven so A can be turned into B without touching the entity logic.
- `speed_count = 5`; `async_set_percentage` -> `math.ceil(percentage_to_ranged_value((1, 5), pct))` ->
  `D0310C` = 1..5, which leaves any preset (so `preset_mode` becomes `None`), as the page requires.
  `percentage == 0` -> turn off.
- `async_turn_on(percentage, preset_mode)`: send power plus the mode in one control message.
- Whether manual speeds 1-5 work on the AC3220 is not proven (note 09). If they do not, drop `SET_SPEED` and
  keep the presets (the Xiaomi "preset only" model), or go to variant B with three speeds.
- Auto+ (`D03180`) and Allergy Sleep modify a mode without replacing it: per the last quoted sentence they are
  `switch` entities, not presets.

### 4.2 Sensors and other entities

Device classes and units [V-core `homeassistant/components/sensor/const.py:160-164, 235-239, 351-367, 434-438,
657, 693, 713-715, 822, 857`; `homeassistant/const.py:809-826, 851, 885`]:

| Entity | Device class | Unit | State class | Category / default | Notes |
|---|---|---|---|---|---|
| PM2.5 (`D03221`) | `SensorDeviceClass.PM25` | `UnitOfDensity.MICROGRAMS_PER_CUBIC_METER` | measurement | primary | **not** `CONCENTRATION_MICROGRAMS_PER_CUBIC_METER` (removed 2027.8) |
| Indoor allergen index (`D03120`, 1-12) | none (not `AQI`: `AQI` exists with unit `None`, but IAI is a Philips scale, not an air quality index standard) | none | measurement | primary | `translation_key="indoor_allergen_index"`; optionally a second `enum` sensor for the band (good/fair/poor/very poor) |
| Humidity (`D03125`) | `HUMIDITY` | `UnitOfRatio.PERCENTAGE` (= `PERCENTAGE`) | measurement | primary | only if the key is reported |
| Temperature (`D03224` / 10) | `TEMPERATURE` | `UnitOfTemperature.CELSIUS` | measurement | primary | only if the key is reported |
| Filter remaining, percent (`D0540E`/`D05408`) | none | `UnitOfRatio.PERCENTAGE` | measurement | diagnostic | precedent: VeSync `filter-life` and Xiaomi `filter_life_remaining` are `%`, `EntityCategory.DIAGNOSTIC` [V-core `vesync/sensor.py:97-105`, `xiaomi_miio/sensor.py:288-296`]; compute with enough precision that it does not round to 0 % early (issue #413 in round 1) |
| Filter remaining, hours | `DURATION` | `UnitOfTime.HOURS` | measurement | diagnostic, optionally disabled | precedent: Xiaomi `filter_hours_used` (`DURATION`, hours) [V-core `xiaomi_miio/sensor.py:297-305`] |
| Pre-filter cleaning due (`D0520D`/`D05207`) | same pair | | | diagnostic | |
| Wi-Fi signal (`rssi`) | `SIGNAL_STRENGTH` | `SIGNAL_STRENGTH_DECIBELS_MILLIWATT` (`"dBm"`) | measurement | diagnostic, disabled by default | |
| Error (`D03240`) | `binary_sensor` `PROBLEM` and/or `enum` sensor | | | diagnostic | |
| Filter replace/clean needed | `binary_sensor` `PROBLEM` | | | diagnostic | |
| Child lock, beep, Auto+ | `switch` | | | config | |
| Display brightness / lamp mode / preferred index / timer | `select` or `light` / `number` | | | config | note 09 lists the value sets |
| Firmware | device `sw_version` (no entity) | | | | an `update` entity is not possible without an OTA API |

"Please note that the use of `PERCENTAGE` constant is also deprecated when used as a unit of measurement, even
if the constant itself is not deprecated." [V-olddocs `blog/2026-06-30-new-unit-enumerators.md`] -> write
`UnitOfRatio.PERCENTAGE` in entity descriptions, as core does now.

---

## 5. The library question

### 5.1 What HA requires

- Core: "Home Assistant does not contain protocol code. An integration never builds HTTP requests or parses a
  device's packets itself: it uses a Python library, published on PyPI" [V-docs
  `docs/core/integrations/api-library.md:9`]. Library requirements: sdist on PyPI, public repo with tagged
  releases matching PyPI, automated publishing, issue tracker, OSI licence for the library "and everything it
  depends on" [`api-library.md:18-24`].
- Custom: no such requirement. "Only list `requirements` that are not already requirements of Home Assistant
  itself." [V-docs `docs/marketplace/guides/integrations.md:37`; same in the manifest page: "Custom
  integrations should only include requirements that are not required by the Core requirements.txt"
  V-olddocs `docs/creating_integration_manifest.md:175-177`]. `cryptography==50.0.2` is in core
  `requirements.txt` and `package_constraints.txt` [V-core `requirements.txt:25`,
  `homeassistant/package_constraints.txt:33`], so an integration that only needs `cryptography` lists **no**
  requirement at all. `pycryptodomex` is not a core requirement (only a `pycryptodome>=3.6.6` constraint exists
  [V-core `package_constraints.txt:85-87`]).
- How HA installs requirements [V-core `homeassistant/requirements.py:112-119`]:
  `if pkg_util.is_installed(req) or _install_with_retry(req, kwargs)` with pip `constraints` = core's
  `package_constraints.txt` (`:96-99`). Every integration's requirement string is checked against the one shared
  environment. [Inf] Two custom integrations that pin different exact versions of the same library fight over
  it. This is not hypothetical here: `philips_heater_coap` pins `aioairctrl==0.2.5` and
  `philips_airpurifier_coap` pins `aioairctrl==0.3.1` [V-code both `manifest.json`], both are in the HACS
  default catalog [V-hacs].

### 5.2 aiocoap inside Home Assistant, concretely

- No core integration lists aiocoap directly and core does not pin it: it is absent from
  `requirements_all.txt`, `requirements.txt` and `package_constraints.txt` [V-core, grep]. It arrives
  transitively through two core requirements:
  - `pytradfri[async]==15.0.0` (IKEA TRADFRI; `requirements_all.txt:2937`,
    `homeassistant/components/tradfri/manifest.json`) -> `aiocoap~=0.4.5`, `DTLSSocket~=0.1.12` [V-pypi];
    pytradfri 15.0.0 was released 2026-11-11.
  - `aiohomekit==4.0.1` (HomeKit Device / `homekit_controller`, used for HomeKit over Thread;
    `requirements_all.txt:314`) -> `aiocoap>=0.4.5` [V-pypi].
- Therefore the aiocoap version in an official HA 2026.11 image is whatever pip resolved at image build time
  for `>=0.4.5,<0.5`; the newest release is 0.4.17 of 2025-11-05, with no release in the twelve months since
  [V-pypi]. [Inf] HA 2026.11 ships 0.4.17. I did not inspect an image.
- A custom integration that requires `aiocoap<0.5` would break, or be broken by, a future core bump of
  pytradfri/aiohomekit to an aiocoap 0.5 line, with no control over the timing.
- Process-global state and known conflicts (round 1 has the details; new evidence marked):
  - kongo09 v0.35.0 set `AIOCOAP_CLIENT_TRANSPORT` in `os.environ` and broke IKEA TRADFRI (issue #322).
  - tinkerologie writes `os.environ["AIOCOAP_CLIENT_TRANSPORT"]` from a worker thread (note 03).
  - **New**: `philips_heater_coap` monkeypatches `aiocoap.defaults.get_default_clienttransports` around every
    client creation, under a module lock, to avoid "the blocking filesystem scan triggered by aiocoap's TLS
    transport initialisation on Python 3.14+"; its changelog calls the override "process-wide"
    [V-code `src/mrverrall_philips-heater-coap/custom_components/philips_heater_coap/helpers.py:49-66`,
    `CHANGELOG.md:58`]. Three independent integrations needed a process-global workaround for the same library.
  - IPv6: aiocoap's default `udp6` transport opens an `AF_INET6` socket and fails with `[Errno 97]` on hosts
    with IPv6 disabled; upstream declined to support that (round 1, F12).
  - No request timeout for NON, silent Observe-ordering drops, double-shutdown error (round 1, W13 etc.).
- History in core review: the 2022 core PR for a Philips purifier integration used a fork of the library
  (`phipsair`) and its description said "There's one monkey patch left that fixes an exception when shutting
  down device connections." [R https://github.com/home-assistant/core/pull/68714].

### 5.3 The four options

| | (a) depend on `philips-airctrl` | (b) depend on `aioairctrl` | (c) new small library on aiocoap | (d) new library, own minimal CoAP codec + `cryptography` |
|---|---|---|---|---|
| Version / date [V-pypi] | 1.5.1, 2026-11-15; 1.1.0 -> 1.5.1 in under six months | 0.3.1, 2026-03-01 | - | - |
| Dependencies [V-pypi] | `aiocoap>=0.4.11`, `click`, `netifaces>=0.11.0`, `pycryptodomex`, `pydantic`, `pyyaml`, `tabulate` | `pycryptodomex`, `aiocoap>=0.4.17,<0.5` | `aiocoap`, crypto lib | none beyond what core ships (`cryptography`; MD5/SHA-256 are in `hashlib`) |
| Install risk | `netifaces` is unmaintained (last release 0.11.0, 2021-05-31, PyPI wheels up to cp39 only [V-pypi]); works on HA OS/Container only because `wheels.home-assistant.io/musllinux` carries cp314 musl wheels for x86_64/aarch64 [V index listing]; needs a compiler elsewhere | small | small | none (manifest `requirements: []`) |
| Semantics | Observe renewal behaviour is the failure mode on this firmware (note 03) | no timeouts, NON sent once (note 02) | timeouts must be bolted on from outside; inherits every aiocoap issue in 5.2 | full control of timeouts, retries, token/MID handling, liveness, socket lifetime |
| Shared-environment conflicts | fast-moving exact pin shared with tinkerologie's integration if both installed | exact-pin clash already exists between two catalog integrations (5.1) | couples to core's unpinned transitive aiocoap | none |
| Upstream control | one maintainer, heavy contribution process (note 03) | one maintainer, stale (note 02) | own | own |
| Code to write and test | least | least | medium | most: CoAP header/token/options codec, NON request/response matching, Observe, ACK/RST, dedup (round 1 scoped this as a small subset: NON GET/POST, Uri-Path, Observe, Max-Age, ACK incoming CON, no blockwise, no DTLS) |
| Core-eligible later | no (dependency hygiene) | unlikely | possible | best position: small, typed, async, no monkeypatching |

**Recommendation: (d)**, developed as a self-contained, HA-agnostic package with its own tests and a fake
device. Two packaging choices, both legitimate for a custom integration:

- **D3a (recommended to start): vendor it** as a sub-package inside the integration folder (for example
  `custom_components/<domain>/airlink/`), with `"requirements": []`. One release artefact, no pip at HA start,
  no version skew, `dependency-transparency` exempt ("If the integration does not have any external
  dependencies, this rule does not apply"). Keep the boundary strict: the sub-package must not import
  `homeassistant`.
- **D3b (when stable, or if core is a goal): publish it on PyPI** from its own repository with trusted
  publishing from GitHub Actions and a tag per release, pin `==x.y.z` in the manifest. This is what core
  requires (5.1).

Receive buffer and fragmentation: note 01 infers the AC3220 status datagram is about 1.9 kB and IP-fragmented.
An asyncio `DatagramProtocol` receives whole reassembled datagrams, so the codec is unaffected, but it is a
documentation item ("fragmented UDP must pass between HA and the purifier") and a candidate repair issue.

---

## 6. Testing and CI

- Test package: `pytest-homeassistant` pinned to the HA version under test; "Use the package release that
  matches your Home Assistant version. Upgrade them together." Pytest config from its README
  [V-core `packages/pytest-homeassistant/README.md`]:

  ```toml
  [tool.pytest.ini_options]
  asyncio_mode = "auto"
  asyncio_default_fixture_loop_scope = "function"
  addopts = "-p no:respx"
  pythonpath = ["."]
  testpaths = ["tests"]
  ```

  Imports move from `pytest_homeassistant_custom_component.common` to `pytest_homeassistant.common`; "The
  wrapper fixture requesting `enable_custom_integrations` can be removed; custom integrations are enabled by
  default." Requires Python >= 3.14.2 (as HA itself: `REQUIRED_PYTHON_VER = (3, 14, 2)` [V-core
  `homeassistant/const.py:30`]).
- Layout [V-docs `docs/core/development/tests.md:10-42`]: "one test file per file of your integration":
  `tests/conftest.py`, `fixtures/` (status JSON dumps), `snapshots/`, `test_init.py`, `test_config_flow.py`,
  `test_fan.py`, `test_sensor.py`, `test_diagnostics.py`, ...
- Snapshot tests with Syrupy and the `snapshot_platform` helper for "the state of all entities, a diagnostics
  dump, or the entries in a registry" [V-docs `tests.md:94-114`]; helper modules
  `pytest_homeassistant.syrupy`, `pytest_homeassistant.components.diagnostics`, `...components.repairs`.
- Config flow: rule `config-flow-test-coverage` ("Test the config flow fully", no exceptions): user step
  success, cannot_connect then recovery, unsupported model, already configured, DHCP new device, DHCP known
  device with new IP (entry updated), DHCP for a foreign MXCHIP device (abort), reconfigure success, reconfigure
  to a different device (`unique_id_mismatch`).
- **Fake UDP device.** `pytest-homeassistant` blocks sockets by default but allows loopback:
  `pytest_socket.socket_allow_hosts(["127.0.0.1"])` then `pytest_socket.disable_socket(allow_unix_socket=True)`
  [V-core `packages/pytest-homeassistant/pytest_homeassistant/plugins.py:248-249`]; a test that opens sockets
  must request the `socket_enabled` fixture. Two layers:
  1. Protocol package tests (no HA): an `asyncio.DatagramProtocol` fake purifier bound to `127.0.0.1:0` that
     implements sync/status/control/info and scripted misbehaviour: silent after the first notification, never
     answering status GETs, dropping the first N datagrams, duplicate MIDs, CON notifications, counter
     wrap-around, undecryptable payload, stale Observe sequence numbers, a 2-3 kB status payload. Golden crypto
     vectors come from round 1 (note 01).
  2. Integration tests: patch the client class where the integration imports it and drive the coordinator
     with fixtures; advance time with the `freezer` fixture and `async_fire_time_changed` to trigger the
     silence probe; assert "one info log on loss, one on recovery" with `caplog`. A few end-to-end tests may use
     the real fake device with `socket_enabled`.
- GitHub Actions:
  - `home-assistant/actions/hassfest@master` (validates manifest, translations, `icons.json`, services; the
    standalone hassfest package "is not ready for external consumption" yet [V-core
    `packages/hassfest/README.md`]).
  - `hacs/action@main` with `category: integration`, on push, PR and nightly schedule [V-docs
    `docs/marketplace/reference/validation.md`]; it also checks manifest `categories` ("a missing key is a
    warning, an unknown category fails the check").
  - `ruff check` + `ruff format --check`, `mypy --strict` over the integration and the protocol package.
  - pytest matrix: the minimum supported HA (pin `pytest-homeassistant==<min>`), the latest stable, and a
    scheduled job with the newest pre-release (`pip install --pre pytest-homeassistant`) to catch breaking
    changes during the beta week. Marketplace guide: "Test your integration against the beta, and set
    `homeassistant` in `hacs.json` when a release needs a newer Home Assistant." Developer-facing changes "are
    deprecated for 12 months first, and announced on the blog" [V-docs
    `docs/marketplace/guides/integrations.md:107`].
  - Fail CI on deprecation warnings from HA's `frame.report_usage` in the test log (grep for "is deprecated"),
    since that is how the removals in section 9 announce themselves.

---

## 7. Distribution

### 7.1 Marketplace/HACS: from a link first, catalog later

- From day one users can add the repository from a My link (custom repository): `marketplace_repository`
  (HA 2026.11+) or the older `hacs_repository`, which "opens HACS before 2026.11, and the Marketplace after, so
  it reaches users on both" [V-docs `docs/marketplace/guides/catalog.md:14-24`]. Custom repositories update via
  the GitHub API "every 48 hours, and only with a GitHub connection"; catalog entries within hours
  [V-docs `docs/marketplace/guides/releases.md:24-30`].
- Catalog (default list) = pull request to `hacs/default`. Requirements [V-hacs
  `source/docs/publish/include.md`; V-docs `docs/marketplace/guides/catalog.md:26-67`]: owner or major
  contributor submits; public GitHub repo with description, topics, issues enabled, README; HACS action passing
  "without any errors or ignores"; hassfest passing; a full GitHub release (not just a tag); `hacs.json` with at
  least `name`; `manifest.json` with `domain`, `documentation`, `issue_tracker`, `codeowners`, `name`,
  `version`; brand images (`brand/icon.png`, or the brands repo as fallback); OSI-approved licence that GitHub
  can identify; no domain conflict with core "including integrations coming in the next release"; PR from a
  personal account, entry in alphabetical order. "Be ready to wait ... new additions take months to be
  reviewed."
- Precedent that a new, narrow Philips CoAP integration gets in: `mrverrall/philips-heater-coap`
  (domain `philips_heater_coap`, MIT, CHANGELOG 1.1 dated 2026-01-14) is in the default list today, with
  `brand/icon.png` in the integration folder [V-hacs default list; V-code]. Also in the list:
  `kongo09/philips-airpurifier-coap`, `Ka3seBr0t/HA_Philips_Air_Plus`,
  `renaudallard/homeassistant_philips_homeid`. **Not** in the list: `tinkerologie/ha-philips-airpurifier`.

### 7.2 Files

`hacs.json` [keys: V-docs `docs/marketplace/reference/hacs-json.md:21-29`]:

```json
{
  "name": "Philips PureProtect (local)",
  "homeassistant": "2026.11.0"
}
```

- `homeassistant`: "The minimum Home Assistant version for this release ... Only checked for repositories with
  releases." Add `zip_release` + `filename` only if the release workflow builds an archive.
- Minimum HA version: I suggest 2026.11.0 (Marketplace present, `DeviceInfo` dataclass attribute API, repair
  issues linked to an entry, `UnitOfDensity`/`UnitOfRatio` from 2026.7, `brand/` from 2026.3). Raise to
  2026.12.0 when `UpdateFailedUnreachable` is used. There is no minimum-version key in `manifest.json`; the
  Marketplace enforces `hacs.json`.

`manifest.json` (custom-only keys `version`, `issue_tracker`, optional `import_executor` [V-docs
`docs/core/integrations/manifest.md:191-197`]):

```json
{
  "domain": "<domain>",
  "name": "Philips PureProtect",
  "categories": ["climate.air_purifiers_humidifiers"],
  "codeowners": ["@<github-user>"],
  "config_flow": true,
  "connectivity": ["network"],
  "dependencies": ["dhcp"],
  "dhcp": [
    { "hostname": "mxchip*" },
    { "macaddress": "B0F893*" },
    { "registered_devices": true }
  ],
  "documentation": "https://github.com/<owner>/<repo>",
  "integration_type": "device",
  "iot_class": "local_push",
  "issue_tracker": "https://github.com/<owner>/<repo>/issues",
  "loggers": ["custom_components.<domain>"],
  "requirements": [],
  "version": "0.1.0"
}
```

- `categories`: VeSync and Xiaomi Miio use `climate.air_purifiers_humidifiers`; `connectivity: ["network"]` as
  AirGradient [V-core manifests; blog `2026-10-20-integration-categories.md`: optional for custom integrations,
  hassfest warns on unknown, HACS action fails on unknown].
- `dhcp` in `dependencies` only if `dhcp.async_discovered_service_info` is used (3.8); keys must stay sorted
  the way hassfest wants (domain, name, then alphabetical).
- Name rule [V-olddocs `docs/creating_integration_manifest.md:44-50`]: the local variant uses "the plain product
  or service name with no suffix ... Do not append 'Local'" (a core naming rule; for a custom integration that
  coexists with two others a distinguishing name is defensible, but avoid "Local"/"CoAP" in the name if core is
  ever the goal).

### 7.3 Versioning and releases

- `version` must be "a valid version recognized by AwesomeVersion like CalVer or SemVer"; hassfest accepts
  CalVer, SemVer, SimpleVer, BuildVer, PEP 440 [V-core `script/hassfest/manifest.py:199-213`].
- "For an integration, use the same version in `manifest.json` as in the tag. The Marketplace refuses to
  install an integration without a `version` in its manifest." and "A tag alone is not enough: it has to be a
  published release." [V-docs `docs/marketplace/guides/releases.md:12-18`].
- Either scheme works. SemVer (`0.1.0` -> `1.0.0`) communicates breaking changes of the integration itself;
  CalVer (`2026.11.1`, as tinkerologie and philips_homeid use) mirrors HA. Pick one and never change the
  ordering scheme, because update entities compare versions.
- Use GitHub pre-releases for betas: "Users only get it when they turn on the Pre-release switch of your
  repository" [`releases.md:32-34`]. Put breaking changes at the top of release notes (shown in the update
  entity).
- A release workflow should verify that the tag equals `manifest.json` `version` before publishing.

---

## 8. Strategy: contribute, fork, or start new?

### 8.1 Was there ever a core integration or PR?

- No Philips air purifier integration exists in core: the only `philips*` domains are `philips_js` and
  `philips_infrared`; the Philips brand file lists `dynalite`, `hue`, `hue_ble`, `philips_infrared`,
  `philips_js` [V-core `git ls-tree`, `homeassistant/brands/philips.json`].
- Three core PRs, none merged [R, GitHub PR search on home-assistant/core and the PR pages]:
  - #31367 "Add Philips Air Purifier" (shexbeer), closed 2020-02-01.
  - #68714 "Add Philips air purifier integration" (mfrister; label `integration: philips_air_purifier`,
    `new-integration`, `has-tests`), opened 2022-03-26 with a fan-only platform and the forked library
    `phipsair`; reviewers asked about taking over the original library and about typing/availability; closed by
    the author on 2022-10-04: "I've now attempted to find someone to give more feedback on this PR over the
    course of 6 months".
  - #109769 "Register custom integration for Philips brand" (kongo09), closed 2024-02-06 by MartinHjelmare:
    "We don't add custom integrations in these brands files."
- I found no architecture discussion about Philips purifiers (searched via web search only; the GitHub API is
  not reachable from here, so absence is not proven).
- Current official path [V-docs `docs/core/integrations/create.md:12-24`]: "For a new integration, the project
  recommends that you publish it in the Marketplace first, as a custom integration ... Once it has matured and
  has a user base, ask in the #developers channel on Discord whether it should ship built in." Core also needs
  the PyPI library (5.1) and a minimal first PR: "One platform only ... No diagnostics, custom actions,
  reauthentication flow, or reconfigure flow."

### 8.2 Options (adds HA-side evidence to round 1, note 03 section 6)

| Option | HA-side evidence |
|---|---|
| Contribute to `tinkerologie/ha-philips-airpurifier` | Not in the catalog [V-hacs]; requires HA >= 2026.9 and `philips-airctrl==1.5.0` with the dependency set of 5.3 [V-code]; its liveness design is the disputed part (note 03). Small fixes are worth upstreaming; the availability model is not a "small fix". |
| Fork it | Same dependency set; "Two repositories can not install the same domain. When a user has one installed, the Marketplace refuses the other." [V-docs `docs/marketplace/guides/integrations.md:57`] -> a fork must change its domain anyway, which removes the main benefit of forking (drop-in replacement). |
| Contribute to kongo09 | Maintainer capacity is the bottleneck (note 02/04); two scheduled hard breakages still open (section 9). |
| **New focused integration** | Matches the official guidance (Marketplace first), the catalog precedent `philips_heater_coap`, and the single-config-entry device model (coexists with the old one during migration). Lets D1-D3 be designed in from the start. Cost: own protocol layer (5.3 d) and one device family only. |

**Recommendation: new focused integration**, plus upstreaming cheap fixes and findings to both existing
projects (and reading `philips_heater_coap` as a third reference: it replaced its polling mode by Observe plus
an idle "tickle" probe - after 45 s of silence it writes a functionless control field `D03182` to make the
device push a status, with a 15 s timeout and 3 rounds [V-code
`src/mrverrall_philips-heater-coap/custom_components/philips_heater_coap/__init__.py:39-41`,
`helpers.py:69-93`, `const.py:53`]. Whether that field exists and behaves the same on the AC3220 is untested;
it belongs to the protocol angle.)

### 8.3 Domain name

Rules: "This domain has to be unique and cannot be changed." [V-olddocs
`docs/creating_integration_manifest.md:40-42`]; "Pick one that no integration in core uses" and the
one-domain-per-catalog rule above; HACS "Check core domain conflict" [V-hacs `include.md:62-67`].

Taken or burdened [V-hacs `data.json`, V-core, R]:

| Domain | Owner |
|---|---|
| `philips_airpurifier_coap` | kongo09 (catalog; images in brands repo) |
| `philips_airpurifier` | tinkerologie (not in catalog, but installed base) |
| `philips_air_purifier` | used by the 2022 core PR #68714; one underscore away from tinkerologie's |
| `philips_airplus` | Ka3seBr0t (cloud, CX3550) |
| `philips_homeid` | renaudallard |
| `philips_heater_coap` | mrverrall |
| `philips_js`, `philips_infrared` | core |
| also in catalog | `philips_pet_series`, `philips_shaver`, `philips_sonicare_ble`, `philips_home_access`, `philips_android_tv`, `philips_ambilight_hue` |

Free in the catalog and in core today [V]: `philips_pureprotect`, `philips_air_local`, `philips_air_coap`,
`philips_purifier`, `philips_air`.

Suggestion: `philips_pureprotect` if the scope is the PureProtect/"Unicorn" generation-3 family (clear, hard
to confuse with the three `philips_air*purifier*` names, describes the product line as HA domains usually do);
`philips_air_local` if the ambition is all generation-3 CoAP devices. Avoid `philips_air_purifier` and anything
that differs from an existing domain by an underscore: support threads and log lines would be ambiguous. The
choice is the user's; it cannot be changed later without a migration.

---

## 9. Deprecations and removals to design around (HA 2026.x - 2027.x)

The two "hard breakages" of kongo09's code base named in round 1 are:

| # | What | Deprecated in | Removed in | Evidence | Where kongo09 uses it |
|---|---|---|---|---|---|
| 1 | `CONCENTRATION_MICROGRAMS_PER_CUBIC_METER` (and the other `CONCENTRATION_*` constants) -> `UnitOfDensity` / `UnitOfRatio` | 2026.7 | **2027.8** | [V-core `homeassistant/const.py:836-838`: `DeprecatedConstantEnum(UnitOfDensity.MICROGRAMS_PER_CUBIC_METER, "2027.8")`; V-olddocs `blog/2026-06-30-new-unit-enumerators.md`] | module-level import in `const.py:18` -> whole integration fails to import |
| 2 | Climate `_attr_temperature_unit`, `current_temperature`, `target_temperature*` -> `native_` prefixed names | 2026.11 | **2027.11** | [V-olddocs `blog/2026-10-08-climate-native-temperature.md`: "Support for the old names will be removed in Home Assistant Core 2027.11."] | `climate.py:104, 146` [V-code grep] |

(Tinkerologie already uses `native_current_temperature` with a compatibility branch [V-code
`.../philips_airpurifier/climate.py:106-125`].) A purifier-only integration has no climate entity, so #2 does
not apply to the new code; #1 is avoided by using `UnitOfDensity.MICROGRAMS_PER_CUBIC_METER`.

Other scheduled changes a new integration should be born compatible with:

| What | Timeline | Evidence | Do instead |
|---|---|---|---|
| Config entry listener + reloading helper in the same flow | error from **2026.12** | [V-olddocs `blog/2026-05-07-...`] | no update listener, or `async_update_and_abort` |
| `step_id` omitted in `async_show_form`/`async_show_menu`/`async_show_progress` | required from **2027.5** | [V-docs `blog/2026-10-23-flow-results-require-step-id.md`] | always pass `step_id` |
| `FlowHandler.show_advanced_options` | removed **2027.6** | [V-olddocs `blog/2026-05-26-...`; V-core `data_entry_flow.py:708`] | use form sections |
| `DeviceInfo(via_device=...)`, `DeviceEntry.config_entries`/`primary_config_entry`, `async_update_device(add_config_entry_id=...)` | **2027.8** (properties: 2027.10 for custom) | [V-docs/olddocs `blog/2026-07-21-...`, `blog/2026-09-15-...`; V-core `helpers/device_registry.py` seven `breaks_in_ha_version="2027.8"`] | `via_device_id`, `config_entry_id` |
| `DeviceInfo.default_name` | **2027.9** | [V-docs `blog/2026-11-10-device-info-constants.md`] | `name` |
| Entity removed/re-added on `entity_id` rename unless `async_entity_id_changed` is implemented | compatibility removed **2027.11** | [V-docs `blog/2026-10-12-new-entity-lifecycle-hooks.md`] | implement the hook if lifecycle hooks are overridden |
| `ATTR_SW_VERSION`, `ATTR_MODEL`, `ATTR_MANUFACTURER`, `ATTR_IDENTIFIERS`, ... from `homeassistant.const` | **2027.12** | [V-core `const.py:388-400`; V-docs `blog/2026-11-10-...`] | `DeviceInfo(...)` keyword arguments |
| Dict-style access to `DeviceInfo` | **2027.12** | [V-docs `blog/2026-11-19-device-info-mapping.md`] | attributes |
| `UNDEFINED` / `UndefinedType` -> `Undefined` | deprecated 2026.12 (removal date not stated in the post) | [V-docs `blog/2026-11-01-undefined-helper.md`] | `Undefined` once min HA >= 2026.12 |
| `PERCENTAGE` "when used as a unit of measurement" | deprecated 2026.7, no date | [V-olddocs `blog/2026-06-30-...`] | `UnitOfRatio.PERCENTAGE` |
| `voluptuous` | replaced by Probatio in 2026.9; `import voluptuous as vol` keeps working through an alias, error texts differ | [V-olddocs `blog/2026-09-30-probatio-validation-engine.md`] | either import works in a custom integration; do not assert on validation error text in tests |
| `async_setup_entry` returning `bool` | core must return `None` from 2026.11; custom may keep `bool` | [V-docs `blog/2026-10-23-config-entry-methods-return-none.md`] | return `None`, raise `ConfigEntry*` exceptions |
| `pytest-homeassistant-custom-component` | broken since ~2026.11 | section 1 | `pytest-homeassistant` |
| `strings.json` + `[%key%]` references in a custom integration | never worked | section 3.6 | full text in `translations/*.json` |

---

## 10. Recommended file layout and checklist

### 10.1 Repository layout

```text
<repo>/
├── custom_components/<domain>/
│   ├── __init__.py            # async_setup_entry / async_unload_entry, typed ConfigEntry
│   ├── manifest.json
│   ├── const.py               # DOMAIN, timings, key names shared by platforms
│   ├── coordinator.py         # push coordinator + silence probe (D1), availability, logging
│   ├── entity.py              # base CoordinatorEntity, DeviceInfo, unique_id
│   ├── config_flow.py         # user, dhcp, discovery_confirm, reconfigure
│   ├── fan.py                 # PARALLEL_UPDATES = 1
│   ├── sensor.py              # PARALLEL_UPDATES = 0, EntityDescriptions with value_fn/exists_fn
│   ├── binary_sensor.py       # PARALLEL_UPDATES = 0
│   ├── switch.py  select.py  number.py  light.py   # as the device supports (note 09)
│   ├── diagnostics.py         # async_redact_data
│   ├── repairs.py             # optional
│   ├── icons.json
│   ├── quality_scale.yaml     # self-audit (section 2.3)
│   ├── brand/icon.png  brand/logo.png   (+ @2x, dark_ variants optional)
│   ├── translations/en.json  translations/nl.json
│   └── airlink/               # D3a: vendored protocol package, imports nothing from homeassistant
│       ├── __init__.py  py.typed
│       ├── coap.py            # message codec (header, token, options, payload)
│       ├── transport.py       # asyncio.DatagramProtocol, request/response matching, deadlines, retries
│       ├── crypto.py          # MD5 key/IV derivation, AES-128-CBC via cryptography, SHA-256 digest
│       ├── client.py          # sync, info, observe, control, probe; one lock; typed exceptions
│       └── models.py          # typed state view over the D0xxxx keys
├── tests/
│   ├── conftest.py            # mock client fixture, MockConfigEntry
│   ├── fixtures/              # status/info JSON samples (0.1.9 and 0.2.3 firmware)
│   ├── snapshots/
│   ├── test_init.py  test_config_flow.py  test_coordinator.py
│   ├── test_fan.py  test_sensor.py  ...  test_diagnostics.py
│   └── airlink/               # protocol tests with the fake UDP purifier (no HA imports)
├── .github/workflows/         # hassfest, hacs action, lint+typing, tests (min/stable/beta), release
├── hacs.json
├── pyproject.toml             # ruff, mypy, pytest config
├── README.md                  # install, setup, supported devices/functions, data updates, limits, troubleshooting, removal
└── LICENSE                    # OSI-approved (MIT or Apache-2.0)
```

File names follow [V-docs `docs/core/integrations/file-structure.md`] and the Marketplace guide's example tree
[V-docs `docs/marketplace/guides/integrations.md:16-24`].

### 10.2 Design decisions and the page each rests on

| # | Decision | Rests on |
|---|---|---|
| D1 | `DataUpdateCoordinator` in push mode (`async_set_updated_data`), with `update_interval` acting as a silence-triggered liveness probe; `always_update=False` | https://contributors.home-assistant.io/core/integrations/fetching-data/ ; `homeassistant/helpers/update_coordinator.py:657-672` |
| D2 | Setup never waits for a status payload. Continue setup with `async_refresh()` (or `ConfigEntryNotReady` only when the liveness probe fails) | https://contributors.home-assistant.io/core/quality-scale/test-before-setup/ ("Devices that are often offline") |
| D3 | Own minimal asyncio CoAP client + `cryptography`; no aiocoap, no shared pinned library; vendored first, PyPI later | https://contributors.home-assistant.io/marketplace/guides/integrations/ ("Only list requirements ...") ; https://contributors.home-assistant.io/core/integrations/api-library/ ; `homeassistant/requirements.py:112-119` |
| D4 | Unavailable = probe failed; reachable-but-unknown = `None` values; log once at info each way (`UpdateFailedUnreachable` from 2026.12) | https://contributors.home-assistant.io/core/quality-scale/entity-unavailable/ ; .../log-when-unavailable/ ; https://contributors.home-assistant.io/blog/2026/11/13/update-failed-unreachable/ |
| D5 | Typed `ConfigEntry[Coordinator]` + `entry.runtime_data`; nothing in `hass.data` | https://contributors.home-assistant.io/core/quality-scale/runtime-data/ |
| D6 | Unload closes the socket and cancels every task; return `None`/raise | https://contributors.home-assistant.io/core/quality-scale/config-entry-unloading/ ; https://contributors.home-assistant.io/blog/2026/10/23/config-entry-methods-return-none/ |
| D7 | Commands: deadline + bounded retry in the client, serialized (`PARALLEL_UPDATES = 1` + lock), failures -> translated `HomeAssistantError` | https://contributors.home-assistant.io/core/quality-scale/action-exceptions/ ; .../exception-translations/ ; .../parallel-updates/ |
| D8 | Unique id = device id from `/sys/dev/info`; MAC only from DHCP data; no `getmac` | https://contributors.home-assistant.io/core/integrations/config-flow/ ("What makes a good unique ID") |
| D9 | DHCP discovery with a non-intrusive plaintext probe, confirm step, host update via `_abort_if_unique_id_configured(updates=...)`, `registered_devices` | https://contributors.home-assistant.io/core/integrations/manifest/ (dhcp) ; .../config-flow/ ("Discovery steps", "Update connection details on the fly") ; https://contributors.home-assistant.io/core/quality-scale/discovery-update-info/ |
| D10 | Reconfigure flow for the host with `_abort_if_unique_id_mismatch` | https://contributors.home-assistant.io/core/integrations/reauth-reconfigure/ |
| D11 | Fan: presets auto/sleep/medium/turbo (table-driven, variant B possible), 5 manual speeds as percentage, modifiers as switches | https://contributors.home-assistant.io/core/entities/fan/ ; core `vesync/fan.py`, `switchbot/fan.py` |
| D12 | Sensors with `UnitOfDensity`/`UnitOfRatio`, device classes, diagnostic category for filter/RSSI | `homeassistant/components/sensor/const.py` ; https://contributors.home-assistant.io/core/quality-scale/entity-device-class/ ; .../entity-category/ |
| D13 | `has_entity_name`, `translation_key`, `icons.json`, `translations/*.json` with full strings | .../has-entity-name/ ; .../entity-translations/ ; .../icon-translations/ ; https://contributors.home-assistant.io/core/integrations/translations/ ("Custom integrations") |
| D14 | `DeviceInfo(...)` dataclass with `model_id`, `sw_version`, optional MAC connection; no `ATTR_*` constants | https://contributors.home-assistant.io/core/integrations/device-registry/ ; https://contributors.home-assistant.io/blog/2026/10/13/device-info-class/ |
| D15 | Diagnostics with redaction and link-health counters | https://contributors.home-assistant.io/core/quality-scale/diagnostics/ |
| D16 | Tests on `pytest-homeassistant`; fake UDP purifier on 127.0.0.1; snapshot tests; CI on min/stable/beta | `packages/pytest-homeassistant/README.md` in core ; https://contributors.home-assistant.io/core/development/tests/ |
| D17 | Ship via Marketplace link first, `hacs/default` PR after the first stable release; `brand/` folder; `hacs.json` with `homeassistant` minimum; GitHub releases with tag == manifest version | https://contributors.home-assistant.io/marketplace/guides/catalog/ ; .../guides/releases/ ; .../reference/hacs-json/ ; https://hacs.xyz/docs/publish/include/ |
| D18 | New domain that cannot be confused with the existing ones | https://contributors.home-assistant.io/marketplace/guides/integrations/ ("Pick a domain that is yours") |

### 10.3 Checklist

Protocol package
- [ ] No import of `homeassistant`; fully typed; `py.typed`.
- [ ] One UDP socket per device for the lifetime of the entry; explicit `close()`; idempotent.
- [ ] Every request has a deadline and a bounded retry policy; typed exceptions (`Unreachable`, `ProtocolError`).
- [ ] Liveness probe that does not depend on a status payload.
- [ ] One lock for counter + control; re-encrypt on every retry (round 1).
- [ ] Fake purifier and golden vectors in the tests.

Integration
- [ ] `manifest.json`: `config_flow`, `integration_type: device`, `iot_class: local_push`, `dhcp` matchers incl.
      `registered_devices`, `categories`, `version`, `issue_tracker`, `requirements: []`.
- [ ] `async_setup_entry` continues when the device is silent; `entry.runtime_data`; unload closes everything.
- [ ] Coordinator: push + silence probe; info-level log once on loss and once on recovery; no error-level noise.
- [ ] Entities: `has_entity_name`, unique ids from the device id, descriptions with `exists_fn`, categories,
      disabled-by-default for noisy diagnostics, `PARALLEL_UPDATES` in every platform file.
- [ ] Commands raise translated `HomeAssistantError`; nothing can hang.
- [ ] Config flow: user, dhcp (+confirm), reconfigure; `step_id` always; unique id; host update on new IP.
- [ ] `diagnostics.py` with redaction; `icons.json`; `translations/en.json` complete, `nl.json`.
- [ ] No deprecated API from section 9; CI fails on HA deprecation warnings.

Repository
- [ ] `brand/icon.png`, `hacs.json`, README with the Gold documentation topics, OSI licence, description,
      topics, issues enabled.
- [ ] Workflows: hassfest, HACS action (no ignores), ruff, mypy strict, pytest (min, stable, beta).
- [ ] GitHub release with tag == manifest version; pre-releases for betas.
- [ ] After the first stable release: PR to `hacs/default`.

---

## 11. What I could not verify

- The aiocoap version inside the official HA 2026.11 container image (inferred 0.4.17 from unpinned transitive
  requirements; no image inspected).
- Whether any architecture discussion about Philips purifiers exists (no GitHub API access; web search found
  none).
- Details of the three core PR pages are from WebFetch summaries, not raw text.
- The DHCP hostname and OUI of the user's AC3220/10, and whether its payloads expose a serial number
  (`D01S0D` is a candidate) or a MAC (none seen in the dumps in note 09).
- Whether `philips_heater_coap`'s tickle field `D03182` exists on the AC3220.
- Whether a core reviewer would accept "medium" and "turbo" as fan presets (section 4.1, variants A and B) is
  a judgement call; the docs and the core precedents point in slightly different directions.
- HA's retry timing for `ConfigEntryNotReady` and the coordinator's back-off schedule after `UpdateFailed` were
  not read in source.

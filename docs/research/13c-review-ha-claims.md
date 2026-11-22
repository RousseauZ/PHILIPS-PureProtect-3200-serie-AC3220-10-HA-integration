# 13c - Review of the Home Assistant platform claims (H1-H15) and of report section 6.7

Reviewer lens: skeptical verifier of the Home Assistant platform claims that note 10 introduced and that
`docs/onderzoek.md` section 6.7 (plus the distribution/testing advice) builds on.
Date of verification: 2026-11-22. Nothing from note 10 was accepted as evidence; every verdict below rests on a
primary source fetched in this session. Raw downloads are in `scratchpad/dl13c/`.

Outcome in one line: all fifteen claims hold up against primary sources (12 confirmed, 3 confirmed only in a
narrower form: H9, H12 dates, H14). Note 10 is reliable. The problems are in the report: section 6.7 says that
2026 changes "raken het plan" but never names them, and three of its rows are inconsistent with the rest of
the report or with the verified platform behaviour.

## 1. Sources fetched (all 2026-11-22)

| Tag | What | URL |
|---|---|---|
| core-dev | `home-assistant/core` branch `dev` (version `2026.12.0.dev0` per `const.py:24-26`) | `https://raw.githubusercontent.com/home-assistant/core/dev/...` |
| core-tag | `home-assistant/core` tag `2026.11.2` and `2026.10.4` | `https://raw.githubusercontent.com/home-assistant/core/2026.11.2/...` |
| docs | `home-assistant/contributors.home-assistant.io` branch `main`, `src/content/docs/...` and `src/content/blog/...` | `https://raw.githubusercontent.com/home-assistant/contributors.home-assistant.io/main/src/content/...` |
| olddocs | `home-assistant/developers.home-assistant` `master` README | `https://raw.githubusercontent.com/home-assistant/developers.home-assistant/master/README.md` |
| site | HTTP status of `developers.home-assistant.io` and `contributors.home-assistant.io` (curl) | |
| pypi | `https://pypi.org/pypi/pytest-homeassistant/json`, `.../pytest-homeassistant-custom-component/json`, `.../pytradfri/json`, `.../aiohomekit/json` | |
| hacs | `https://raw.githubusercontent.com/hacs/default/master/integration`, `https://data-v2.hacs.xyz/integration/data.json` (5545 entries), `https://hacs.xyz/docs/publish/include/` | |
| other | PHACC README, `home-assistant/brands` README, `pyca/cryptography` CHANGELOG | raw.githubusercontent.com |

## 2. Verdicts

### H1 docs moved - CONFIRMED
- olddocs README: "As of October 16, 2026, the Home Assistant developer documentation lives at
  contributors.home-assistant.io ... It replaces developers.home-assistant.io, design.home-assistant.io, and
  data.home-assistant.io." and "This repository is kept for its history and is no longer maintained."
- site: `https://developers.home-assistant.io/` -> 301 to `https://contributors.home-assistant.io/`;
  `.../docs/integration_fetching_data` -> 301 to `.../core/integrations/fetching-data/`;
  `.../blog/2026/10/13/device-info-class/` -> 301 to the same path on the new host. New site answers 200.
- So: old site redirects (deep links too), old repo is frozen.

### H2 HACS -> built-in "Marketplace" in 2026.11 - CONFIRMED (with conditions on "immediately")
- core-tag: `homeassistant/components/marketplace/manifest.json` exists at tag `2026.11.2`
  (`"domain": "marketplace", "name": "Marketplace", "integration_type": "system"`), 404 at tag `2026.10.4`.
- docs `marketplace/index.md`: "It is built into Home Assistant starting with 2026.11, under Settings >
  Marketplace. It grew out of HACS ... and it uses the same catalog and the same `hacs.json` file. ... though
  the Marketplace checks a few things more strictly before it installs."
- docs `marketplace/how-it-works.md`: catalog is `hacs/default`, served from `data-v2.hacs.xyz`; "On the first
  start after the update, the Marketplace takes over a HACS installation ... and HACS is removed"; "The
  catalog, `hacs.json`, the folder structure, and the HACS action are the same."
- Custom repository from a link: "A user can also add a repository that is not in the catalog, from a link: a
  custom repository. That needs a GitHub connection, and the repository has to meet the same requirements as
  one in the catalog." (`how-it-works.md`). Updates for link-added repositories: "through the GitHub API
  instead, every 48 hours, and only with a GitHub connection" (`guides/releases.md`).
- hacs.xyz banner: "HACS is built into Home Assistant as the Marketplace, starting with 2026.11."
- Catalog review: "new additions take months to be reviewed" (`guides/catalog.md`, also hacs.xyz).

### H3 PHACC broken, core publishes pytest-homeassistant - CONFIRMED
- PHACC README (master), first lines: "`homeassistant/core` now offers testing infrastructure into it's own
  package. ... `pytest-homeassistant-custom-component`, this package, is now broken. Custom component
  developers should move to the centrally managed package." Badge: HA core version 2026.10.4.
- pypi PHACC: latest 0.13.375, 2026-10-25, requires `homeassistant==2026.10.4`.
- pypi pytest-homeassistant: latest 2026.11.2 (2026-11-16), author "The Home Assistant Authors", repository
  `home-assistant/core`, requires `homeassistant==2026.11.2` plus pinned pytest stack. Releases: `2026.11.0b4`,
  `b5`, `b6` (2026-11-03/04), `2026.11.0`, `2026.11.1`, `2026.11.2`. (Four unrelated 0.1.x releases from 2020
  are the previous owner of the name.)
- core-dev `packages/pytest-homeassistant/README.md`: "Use the package release that matches your Home
  Assistant version. ... Do not install it together with `pytest-homeassistant-custom-component`"; has a
  migration section; "The `hass` fixture enables custom integrations by default."
- Consequence not in note 10 or the report: there is **no** `pytest-homeassistant` release for any HA version
  before 2026.11.0b4. "Test against the minimum HA version" is therefore only possible for a minimum of
  2026.11.0 or newer (or with the abandoned PHACC for 2026.10.4 and older).

### H4 brand images in `brand/` since 2026.3 - CONFIRMED
- docs blog `2026-02-24-brands-proxy-api.md`: "Starting with Home Assistant 2026.3, custom integrations can
  include their own brand images ... directly in the integration directory. No more submitting to a separate
  repository"; files `icon.png`, `logo.png`, `@2x`, `dark_` variants.
- brands README lines 18-19: "`custom_integrations` ... Legacy folder: Since HA 2026.3.0, custom components can
  include their brand icons directly."
- hacs.xyz include page / docs `guides/catalog.md`: catalog check "Brands: a `brand` folder with at least an
  `icon.png`, or images for the domain in the brands repository."

### H5 custom integrations: full-text `translations/*.json`, no `strings.json`/references - CONFIRMED
- docs `core/integrations/translations.md`, section "Custom integrations": "Custom integrations do not use
  `strings.json` ... The compile step that turns `strings.json` into translations only runs in core. ...
  `en.json` is required and complete ... References do not work in these files: nothing replaces them, so
  users see the raw `[%key:...%]` text. Write out every string in full." Hassfest validates `translations/en.json`.

### H6 one config entry per device since 2026.8 - CONFIRMED
- docs blog `2026-07-21-device-registry-single-config-entry.md`: "A device is now owned by a single config
  entry ... Devices are no longer merged across integrations: a physical device supported by several
  integrations is now represented by one device per config entry ... The changes land in Home Assistant Core
  2026.8." Identifiers and connections are "unique per config entry instead of globally unique".
- Relevance: registry-wise two integrations for one purifier no longer merge. It does not make parallel
  operation safe: the report's own 3.2 ("Eén abonnee per bron-IP") still applies.

### H7 `UpdateFailedUnreachable` in 2026.12 - CONFIRMED
- docs blog `2026-11-13-update-failed-unreachable.md`: "Home Assistant Core 2026.12 adds
  `UpdateFailedUnreachable` ... The coordinator logs the first failure at `info` level, instead of `error`".
- core-dev `helpers/update_coordinator.py:62-67` (class), `:547-551` (`if self.last_update_success: if
  log_failures and isinstance(err, UpdateFailedUnreachable): self.logger.info("%s is unavailable: %s", ...)`),
  `:614` (`"Fetching %s data recovered"` at info).
- core-tag `2026.11.2`: zero occurrences of `UpdateFailedUnreachable`. An integration whose minimum is 2026.11
  needs a guarded import.

### H8 `async_set_updated_data()` re-arms the refresh timer - CONFIRMED, with three caveats
- core-dev `update_coordinator.py:658-673` (identical at tag 2026.11.2): docstring "Manually update data,
  notify listeners and reset refresh interval."; body calls `self._async_unsub_refresh()`, sets
  `last_update_success = True`, then `if self._listeners: self._schedule_refresh()`.
- docs `core/integrations/fetching-data.md`, "Push with a coordinator": "If the coordinator also polls, this
  resets the time until the next poll."
- Core precedent: `wiz/coordinator.py:51` `update_interval=timedelta(seconds=15)` with
  `wiz/__init__.py:112` `coordinator.async_set_updated_data(...)` from the push callback.
- Caveat 1: the same doc section recommends the opposite default for push: "Leave out `update_interval`, so it
  never polls".
- Caveat 2: `_schedule_refresh()` returns early when `self.config_entry.pref_disable_polling` is set
  (`update_coordinator.py:287-288`). A user who switches off "polling for changes" on the entry silently
  disables a watchdog that lives in `update_interval`.
- Caveat 3: raising `UpdateFailed` sets `last_update_success = False` on the first failure, and
  `CoordinatorEntity.available` is exactly that flag (`:750-752`). `async_set_update_error()` logs at error
  level (`:647-653`).

### H9 `test-before-setup` and offline devices - PARTLY CONFIRMED
- docs `core/quality-scale/test-before-setup.md`, "Devices that are often offline": "Some devices are offline
  on purpose, like a solar inverter at night or a TV in standby. Raising `ConfigEntryNotReady` ... is usually
  still the simplest approach. But you can also finish the setup without reaching the device. Refresh the
  coordinator with `await coordinator.async_refresh()`, which does not raise, and the entities stay unavailable
  until the device answers. ... Until then, `coordinator.data` is still `None`, so code that reads it while
  setting up the platforms has to handle that."
- What is not there: the word "silent". The text is about devices that are offline on purpose. A purifier that
  answers sync but sends no status is not offline; setup that does a sync and raises `ConfigEntryNotReady` when
  the sync fails satisfies the main rule without needing this exception at all.
- Also on that page: hassfest only accepts the rule as `done` when `async_setup_entry` awaits
  `async_config_entry_first_refresh`/`async_ensure_token_valid` or the integration raises a `ConfigEntry*`
  exception somewhere. And (Marketplace guide) "The integration quality scale has no tiers for custom
  integrations".

### H10 fan documentation - CONFIRMED
- docs `core/entities/fan.mdx`, "Preset modes": "A preset is a mode where the fan controls its own speed, or
  does something else on its own. ... When no preset is active, `preset_mode` must be `None`. Named manual
  speeds are not presets: represent them as percentages. Setting a speed by hand must end the active preset. If
  the device lets you set a speed while a preset stays active, represent that preset with a separate switch
  instead." The page names "an air purifier fan" as a fan-entity use case.

### H11 unit constants and climate names - CONFIRMED
- core-dev `const.py:836-838`: `_DEPRECATED_CONCENTRATION_MICROGRAMS_PER_CUBIC_METER =
  DeprecatedConstantEnum(UnitOfDensity.MICROGRAMS_PER_CUBIC_METER, "2027.8")`; same for the other
  `CONCENTRATION_*` (ppm/ppb -> `UnitOfRatio`). `PERCENTAGE = UnitOfRatio.PERCENTAGE.value` (`:851`).
- docs blog `2026-06-30-new-unit-enumerators.md`: deprecated "As of Home Assistant Core 2026.7"; `PERCENTAGE`
  "also deprecated when used as a unit of measurement".
- docs blog `2026-10-08-climate-native-temperature.md`: `current_temperature`, `target_temperature`,
  `target_temperature_high/low`, `temperature_unit` renamed with `native_` prefix in 2026.11; "Support for the
  old names will be removed in Home Assistant Core 2027.11."
- `UnitOfDensity` does not exist before 2026.7, another floor for the minimum HA version.

### H12 DeviceInfo dataclass - CONFIRMED (deprecation dates come from two later posts)
- docs blog `2026-10-13-device-info-class.md`: "`DeviceInfo` and `ChildDeviceInfo` are no longer `TypedDict`s.
  They are dataclasses ... included in Home Assistant Core 2026.11." Dict access "still works for now".
- docs blog `2026-11-10-device-info-constants.md`: `ATTR_IDENTIFIERS`, `ATTR_MANUFACTURER`, `ATTR_MODEL`,
  `ATTR_SW_VERSION` ... deprecated in 2026.12, removed 2027.12. core-dev `const.py:388-401` matches.
- docs blog `2026-11-19-device-info-mapping.md`: dict-style use deprecated in 2026.12, stops working 2027.12.
- core-dev `helpers/device_registry.py:348-350`: `@dataclass(eq=False, repr=False, slots=True) class DeviceInfo`.
- `DeviceInfo(identifiers=..., name=...)` with keyword arguments is unchanged and works on old and new versions.

### H13 cryptography direct, aiocoap transitive - CONFIRMED
- core-dev `requirements.txt` and `pyproject.toml:60`: `cryptography==50.0.2` (direct core requirement).
- `aiocoap`: zero hits in `requirements.txt`, `requirements_all.txt`, `pyproject.toml`,
  `package_constraints.txt`. It arrives through `pytradfri[async]==15.0.0` (`requirements_all.txt:2937`; PyPI:
  `aiocoap~=0.4.5; extra == "async"`) and `aiohomekit==4.0.1` (`requirements_all.txt:314`; PyPI:
  `aiocoap>=0.4.5`).
- docs `marketplace/guides/integrations.md`: "Only list `requirements` that are not already requirements of
  Home Assistant itself." So `requirements: []` is right for an integration that only needs `cryptography`.
- Extra check: `pyca/cryptography` CHANGELOG up to 50.0.2 moves only CFB/OFB/CFB8 (47.0.0) and some legacy
  ciphers to `decrepit`; AES-CBC is untouched. MD5/SHA-256 can come from `hashlib`.

### H14 return None / pass config_entry - PARTLY CONFIRMED (both are requirements for core only)
- docs blog `2026-10-23-config-entry-methods-return-none.md`: "Starting with Home Assistant 2026.11.0, core
  integrations must follow the new pattern. Custom integrations can keep returning a boolean." and "Nothing
  breaks for custom integrations, and there is no deprecation."
- core-dev `update_coordinator.py:110-121`: omitting `config_entry` is reported with
  `core_behavior=ERROR`, `custom_integration_behavior=frame.ReportBehavior.IGNORE`, comment "It is not planned
  to enforce this for custom integrations."
- Practical: pass `config_entry=entry` anyway; return `None` only if the minimum HA version is 2026.11 or newer
  (the blog post dates the new contract to 2026.11; do not ship `-> None` to older versions).

### H15 catalog and free domains - CONFIRMED
- `hacs/default` `integration` list line 3559: `mrverrall/philips-heater-coap`; `data.json`: domain
  `philips_heater_coap`, last version v1.9.1, updated 2026-11-05.
- `data.json` domains containing "philips": `philips_airplus` (Ka3seBr0t), `philips_airpurifier_coap`
  (kongo09, v0.37, 2026-07-26), `philips_ambilight_hue`, `philips_android_tv`, `philips_heater_coap`,
  `philips_home_access`, `philips_homeid`, `philips_pet_series`, `philips_shaver`, `philips_sonicare_ble`,
  `xiaomi_miio_philipslight`. Neither `philips_pureprotect` nor `philips_air_local` is present.
- core-dev `homeassistant/generated/integrations.json`: only `philips`, `philips_infrared`, `philips_js`;
  `components/philips_pureprotect/manifest.json` and `components/philips_air_local/manifest.json` -> 404.
- tinkerologie's `philips_airpurifier` domain (cloned manifest) is not in the catalog
  (`tinkerologie/ha-philips-airpurifier` absent from the list), matching the report's 4.2.

## 3. Issues in the report (section 6.7 and the distribution/testing advice), most damaging first

### R1 (medium) Two owners for the reachability watchdog
Report 6.7: "`DataUpdateCoordinator` in push-modus; het interval dient alleen als bewaking na stilte".
Report 6.2/6.3 put the same job in the HA-independent session layer ("Sessielaag: toestandsmachine: sync,
abonnement, bereikbaarheidscontrole, herstel"; "Na 60 seconden zonder enig contact een sync"; "Elke 10 seconden
opnieuw; na 3 missers OFFLINE"; TWIJFEL = "Ongewijzigd").
The mechanism in 6.7 is real (H8) but cannot implement 6.3: a failed coordinator refresh flips
`last_update_success` and therefore availability on the first miss (no TWIJFEL), the timer stops when the user
disables polling for the entry (`pref_disable_polling`), and the official push recipe is "Leave out
`update_interval`". Built literally, the plan yields two timers probing the same device or an availability
model that differs from 6.3.
Fix: make the session layer the only owner of liveness. Coordinator without `update_interval`; push via
`async_set_updated_data`; availability from the session state (override `available` in the base entity, or map
session OFFLINE/recovered to the coordinator explicitly and log the two info lines yourself, since
`async_set_update_error` logs at error level). If the coordinator-interval variant is preferred instead, say
so in 6.3, put the whole retry budget inside one `_async_update_data` call and document the
`pref_disable_polling` hole.

### R2 (medium) "Only create entities for reported keys" versus "do not wait for a status"
Report 6.6: "Entiteiten worden alleen aangemaakt voor sleutels die het apparaat werkelijk meldt"; 6.7:
"beschrijvingen met een functie die bepaalt of de sleutel bestaat"; 6.7/6.5: "Niet wachten op een
statusbericht" / "Een statusbericht is geen voorwaarde"; 6.3: "Tot dan zijn de entiteiten beschikbaar met
onbekende waarden".
At platform setup there is then no status, so the exists-function has nothing to look at. The rule page the
report cites says so itself: "Until then, `coordinator.data` is still `None`, so code that reads it while
setting up the platforms has to handle that."
Fix: specify the mechanism. Persist the observed key set (plus model/firmware) in the config entry or a Store
at first status and create entities from that at startup; add entities from a coordinator listener when a new
key first appears; decide what exists before the very first status (for example only the fan).

### R3 (medium) Test tooling and minimum version are not named, and the floor is higher than the report implies
Report 6.7: "tests tegen de minimale, de huidige en de bètaversie van Home Assistant"; section 9: "Minimale
Home Assistant-versie | De versie die je nu draait of nieuwer".
The only supported test package is `pytest-homeassistant`, which exists from 2026.11.0b4 only (H3); PHACC calls
itself broken and stops at 2026.10.4. Other floors verified here: Marketplace 2026.11 (H2), DeviceInfo
dataclass and `-> None` contract 2026.11 (H12/H14), `UnitOfDensity` 2026.7 (H11), `brand/` 2026.3 (H4),
`UpdateFailedUnreachable` 2026.12 (H7).
Fix: name `pytest-homeassistant` (matching version per CI job, `--pre` for the beta job), and set the minimum
to 2026.11.0 in `hacs.json` (`"homeassistant": "2026.11.0"`), with a guarded import if
`UpdateFailedUnreachable` is used.

### R4 (medium) Distribution advice uses the pre-2026.11 picture
Report 6.7: "Eerst als eigen repository via HACS; na de eerste stabiele versie aanmelden voor de
standaardcatalogus"; section 8 step 5: "Eerste release via HACS".
Since 2026.11 the installer is the built-in Marketplace and HACS is removed on the first start after the update
(H2). What the builder needs and the report omits: a `brand/` folder with `icon.png` inside the integration
(H4, also a catalog check), `hacs.json`, manifest `version`/`issue_tracker`/`codeowners`/`documentation`, a
published GitHub release (a tag is not enough), HACS action without ignores plus hassfest; link-added
repositories need the user to connect GitHub and are checked for updates every 48 hours; catalog review takes
months, so the link is the distribution channel for a long time.
Fix: rewrite the row accordingly and give the README badge (`hacs_repository` My link works before and after
2026.11; `marketplace_repository` is 2026.11+).

### R5 (low-medium) Translation format not stated
Report 6.7: "Vertalingen | Nederlands en Engels" and "vertaalsleutels".
A builder copying core (or kongo09/tinkerologie, which both carry `strings.json`) will use `strings.json` and
`[%key:...%]` references; in a custom integration users then see the raw reference text (H5).
Fix: "complete `translations/en.json` and `translations/nl.json`, every string written out, no `strings.json`,
no references".

### R6 (low-medium) The `test-before-setup` sentence over-reads the rule
Report 6.7: "Niet wachten op een statusbericht; de richtlijn `test-before-setup` staat dat toe voor apparaten
die vaak stil zijn".
The rule's exception is for devices that are "offline on purpose"; it says nothing about silent devices (H9).
The design is still compliant, for a different reason: setup tests the connection with a sync and raises
`ConfigEntryNotReady` when that fails; a status payload is simply not part of the test.
Fix: reword to that, and state which variant is chosen (retry via `ConfigEntryNotReady`, or finish setup with
`async_refresh()` and unavailable entities).

### R7 (low-medium) Fan presets deviate from the current fan documentation without saying so
Report 6.6: "Voorkeuzestanden | `auto`, `sleep`, `medium`, `turbo`".
Fan docs (H10): "Named manual speeds are not presets: represent them as percentages." Medium and Turbo are
fixed speeds. Note 10 section 4.1 presented this as variant A (recommended) against variant B (strict); the
report kept A and dropped the caveat.
Fix: keep A if wanted (not enforced for custom integrations; core precedent VeSync `turbo`), but add the
sentence that this deviates from the docs, keep the mode table data-driven, and state that `preset_mode` is
`None` in manual speeds 1-5 and that setting a percentage leaves the preset.

### R8 (low) 6.7 announces 2026 changes and a second check, but shows neither
Report 6.7: "meldt een aantal wijzigingen in Home Assistant uit 2026 die het plan raken ... een tweede,
onafhankelijke controle staat in bijlage B"; appendix B: "zie de uitkomst in `docs/research/13-review.md`".
The table that follows names none of the changes (docs move, Marketplace, `pytest-homeassistant`, `brand/`,
translations, unit enums, DeviceInfo dataclass, `UpdateFailedUnreachable`), and `docs/research/13-review.md`
does not exist at the time of this review.
Fix: add a short table "verified 2026 platform facts" (from section 2 above, with version numbers) and replace
the forward reference by the result: 15 claims checked against primary sources on 2026-11-22, none refuted.

### R9 (low) PM2.5 unit constant
Report 6.6: "Fijnstof PM2.5 (µg/m³) | `D03221`".
Add: use `UnitOfDensity.MICROGRAMS_PER_CUBIC_METER` and `UnitOfRatio.PERCENTAGE`; the
`CONCENTRATION_*` constants that both existing integrations import are removed in 2027.8 (H11).

## 4. Checked and correct in the report

- 6.2: "`cryptography` ..., dat Home Assistant al meelevert" and "Home Assistant levert het [aiocoap] alleen
  indirect mee" (H13).
- 6.7: "`philips_pureprotect` en `philips_air_local`" are free in core and in the catalog (H15).
- 6.7: typed `entry.runtime_data`, translated `HomeAssistantError`, hassfest plus HACS validation: all still
  the documented practice (Marketplace integration guide, quality-scale pages).
- 4.1/4.2: kongo09 last release v0.37 with catalog timestamp 2026-07-26; tinkerologie not in the default
  catalog (hacs data).
- 6.3 "Logboek | Eén regel bij verlies, één bij herstel": matches `log-when-unavailable` as quoted in the
  2026-11-13 blog post.

## 5. Not checked

- Whether hassfest for custom integrations validates `quality_scale.yaml` (note 10 section 2.3).
- The remaining rows of note 10 section 9 (step_id, show_advanced_options, Probatio, entity lifecycle hooks).
- The aiocoap version inside an official HA image.

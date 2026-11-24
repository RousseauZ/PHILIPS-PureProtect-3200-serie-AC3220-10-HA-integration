# 04 - GitHub issues, PRs and discussions: real-world failure reports and root causes

Research date: 2026-11-22. Angle: what users and maintainers actually report in the issue trackers of the Philips air purifier CoAP ecosystem, why the HACS integrations are unreliable, and what is still unsolved. Target device: Philips PureProtect 3200 series AC3220/10.

## 0. Method, sources, and how far each claim was verified

`api.github.com` and plain `curl` to `github.com` are blocked in this environment (HTTP 403 from the session proxy), and the GitHub MCP server is scoped to the user's own repository only. All issue/PR pages were therefore read with **WebFetch**, which returns a summary written by a small model, not the raw page. Consequences:

- Wording of quotes is second-hand. Numbers, model names, firmware strings, log lines and issue numbers are as relayed by that summary. I cross-checked the load-bearing ones against a second page whenever two pages cite each other (for example #396 vs aioairctrl#14 vs philips-airctrl#44), and against the cloned source where a claim is about code.
- Long threads are partly hidden behind "Load more" (noted per issue where it happened: kongo09 #160, #83; aioairctrl PR #9).
- Nothing was reproduced on hardware. No third-party code was executed.

Verification tags used below:

| Tag | Meaning |
|---|---|
| **[WF]** | Read through WebFetch from the given GitHub URL (second-hand wording, first-hand facts as relayed). |
| **[V-code]** | Verified by reading the cloned source (path relative to `scratchpad/src`, line given). |
| **[V-git]** | Verified from git history/tags of the clone (`git log`, `git tag --contains`). |
| **[I]** | My inference. |

Clones used (already present): `kongo09_philips-airpurifier-coap` (master `964ef21`, 2026-07-26, tag `v0.37`; all PR heads available as `pr/<n>`), `kongo09_aioairctrl` (`cc28046`, 0.3.1, 2026-03-01), `tinkerologie_ha-philips-airpurifier` (`550c88a`, 2026-11-19, manifest version 2026.11.1), `tinkerologie_philips-airctrl` (`b28ee4a`, 2026-11-17, tag v1.5.1).

Repo naming: `ruaan-deysel/ha-philips-airpurifier` is the former location of `tinkerologie/ha-philips-airpurifier` (same project; ruaan-deysel is the active collaborator). Issue numbers below for that project use the tinkerologie URL.

## 1. Executive summary

1. **The single most important root cause in the trackers is a firmware behaviour, not a transport bug: "push on change".** Devices with the newer Wi-Fi module firmware (`WifiVersion` `AWS_Philips_AIR_Combo@86`, also `AWS_Philips_AIR@86.1` and at least one `@91.1` unit) do not answer a `GET /sys/dev/status` (with or without Observe) until some reported value changes, and send no heartbeat. Every design that (a) waits for an immediate answer to a status read, or (b) treats N seconds of silence as "disconnected", or (c) expects a re-registration/renewal GET to be answered, breaks on them. This is documented for AMF870/15, CX7550/01, CX3550/01, CX5120/11, HU1509/HU1510/HU4209, and, most relevant here, for the **AC2210 (fw 0.2.3, Wi-Fi 86), AC2220/10 (`@86`) and AC4221/11 (fw 0.2.3, `@86`)**, i.e. the direct siblings of the AC3220 (sections 3 F1, 4, 5).
2. **Both HACS integrations currently mishandle exactly this for the AC22xx/AC32xx/AC42xx family.** kongo09 v0.37 tears the whole CoAP client down every 180 s of silence (hundreds of reconnects per day on an idle device) and every such reconnect can be lost or hang. tinkerologie 2026.10.3 to 2026.11.1 renews the observation every 60 s with a 10 s answer deadline, which a push-on-change device usually misses; one AC2220/10 user measured 56 unavailable periods in 30 h on tinkerologie 2026.11.1 versus 5 in 8.5 days on kongo09 v0.37 (reported 2026-11-22, the day of this research). The "status nudge" fix that tinkerologie built exists only for AMF870, CX7550, CX5120 and HU15xx/HU4209, not for the AC3220 family (**[V-code]**).
3. **Four more independent, well-evidenced defects stack on top**: reconnect syncs and commands silently lost because the device ignores broadcast ARP while in Wi-Fi power save (packet capture, kongo09 #396/#363); firmware emits occasional corrupted notifications (two NUL bytes in the hex ciphertext, valid digest) that kill the observe task; NUL-padded sync keys that break all commands until the next sync; and double shutdown of the aiocoap context that leaves the kongo09 config entry in `failed_unload` until HA is restarted (reported on an **AC3210/12**, #397).
4. **kongo09/philips-airpurifier-coap is effectively unmaintained since 2026-07-26.** No commit on master since then; 14 open PRs; the reliability PRs (#387, #388, #389) were closed unmerged on 2026-11-07 when their author deleted his fork; #364 and #365 were closed by the stale bot; the stale bot also closes unanswered bug reports (#376, #379, #380, #386). The maintainer has said repeatedly since 2022 that he cannot fix the "connectivity problem" (README warning, label `connectivity` = "with all likelyhood will not be fixed").
5. **No GitHub evidence that a firmware update removed local CoAP from an AC32xx/AC22xx/AC42xx device.** Every "new firmware broke it" report for these models that was followed up turned out to be something else (guest Wi-Fi, HA too old for the integration release, retry worked) or is explained by push-on-change (sync answered, status read silent). Models that truly have no local CoAP are a different hardware generation (AC0650/AC0651, AC0720: ESP32/Versuni, UDP 5683 closed).
6. An unmerged, same-day-closed PR (kongo09 #384) contains code for a **second encryption mode** ("TLS" key exchange on `/sys/dev/info/tls`, RSA-1024 + AES-GCM, advertised by bit 6 of a discovery `option` field) said to be reverse-engineered from the Air+ app. It is unverified against any device, but it is the only concrete lead in the trackers for "firmware that no longer accepts the classic handshake" and is cheap to test on the AC3220 (section 6.3).

## 2. State of the trackers on 2026-11-22

| Repo | Open issues | Closed issues | Open PRs | Closed PRs | Last maintainer code activity |
|---|---|---|---|---|---|
| kongo09/philips-airpurifier-coap | 18 | 268 | 14 | 114 | master `964ef21` 2026-07-26 = v0.37 (+ `v0.37.1-beta.1`, same day) **[V-git]** |
| kongo09/aioairctrl | 0 | 2 | 2 (#13, #14) | 10 | 0.3.1, 2026-03-01 **[V-git]** |
| tinkerologie/ha-philips-airpurifier | 6 | 40 | 0 | 171 | v2026.11.1 (2026-11-13); main `550c88a` 2026-11-19 **[V-git]** |
| tinkerologie/philips-airctrl | 0 | 7 | 0 | 40 | v1.5.1 (fix #44), 2026-11-15/16 **[V-git]** |
| betaboon/philips-airpurifier-coap | archived 2022-12-14 (43 issues) | | | | 2021 |
| rgerganov/py-air-control | CoAP issues mostly open, maintainer has no CoAP device | | | | 2021 |

Counts from the issue/PR list pages **[WF]**:
https://github.com/kongo09/philips-airpurifier-coap/issues?q=is%3Aissue+is%3Aopen , `...is%3Aclosed` (11 pages), https://github.com/kongo09/philips-airpurifier-coap/pulls , https://github.com/tinkerologie/ha-philips-airpurifier/issues?q=is%3Aissue , https://github.com/tinkerologie/philips-airctrl/issues?q=is%3Aissue , https://github.com/kongo09/aioairctrl/pulls?q=is%3Apr .
GitHub Discussions are not enabled on kongo09/philips-airpurifier-coap (`/discussions` returns 404).

How the two projects handle reports:

- **kongo09**: one hobbyist maintainer who states he is "a little bit out of my depth" on CoAP (#323) and has "little experience with CoAP" (#322). Connection problems get the label `connectivity` (label description: "Philips connectivity problem - with all likelyhood will not be fixed") and are closed, often the same day (#349, #303, #293, #318). A stale bot closes anything without activity for 60+7 days, including real bugs nobody answered (#376 NUL-padded key, #379, #380, #386) and reviewed-but-unmerged PRs (#364, #365).
- **tinkerologie**: very active, heavily AI-driven (CodeRabbit "coding plans" on every issue, Copilot/Claude-authored PRs). Fixes land fast but several were regressions shipped without hardware coverage of the affected firmware (2026.10.3 renewal, see F7). Issues are sometimes closed "completed" with no linked change (#6, #8, #58).

The one consistently rigorous source in both trackers is the user **mbreitkreuz** (AMF870/15, `AWS_Philips_AIR_Combo@86`, device software 0.9.1), who ran 10 to 16 days of packet captures on the HA host in October/November 2026 and filed kongo09 #394, #396, comments on #363/#388/#389/#393, aioairctrl#14, tinkerologie #132/#197/#210/#217, philips-airctrl #36/#44. Most quantitative statements below come from those reports.

## 3. Catalogue of failure modes

Model flags: **[SIB]** = reported on an AC3220 sibling (AC3210, AC3221, AC22xx, AC4220/AC4221, PureProtect 3200/4200); **[GEN]** = reported on another device of the same "NEW2"/Gen3 datapoint generation (D0xxxx keys) or with the same `@86` Wi-Fi firmware; **[OLD]** = older-generation devices only.

Overview:

| ID | Symptom as the user sees it | Root cause (diagnosed / suspected) | Sibling evidence | Status Nov 2026 |
|---|---|---|---|---|
| F1 | "Cannot connect", setup timeout, `status` stage `TimeoutError`, `sync` works but status never arrives | Firmware only pushes status on value change; status/observe GET is not answered until then | AC2210, AC2220, AC4221 **[SIB]** | Unfixed for AC22xx/32xx/42xx in both integrations |
| F2 | Entities flap unavailable/available in standby or at night; reconnect every 3 min | Silence watchdog (3 x Max-Age 60 s = 180 s) cannot tell a quiet device from a dead one | AC2210, AC2220 **[SIB]** | kongo09: open; tinkerologie: per-device threshold only |
| F3 | Integration "deaf" for 3 to 12 min, commands hang or fail with `LibraryShutdown`, nothing logged | Reconnect sync / command never leaves the HA host: device ignores broadcast ARP in Wi-Fi power save; no timeout on `CoAPClient.create()` or control writes | not model-specific **[GEN]** | Open (#396, #363) |
| F4 | Values freeze up to 3 min, sometimes after a command | Firmware sends a notification with NUL bytes in the hex payload (digest valid); decrypt raises, observe task dies silently | AC2210 **[SIB]** | Fixed only in philips-airctrl 1.5.1, which the HA integration does not yet ship (#217) |
| F5 | Every command fails for minutes with `invalid literal for int() with base 16: '27AA\x00\x00\x00\x00'` | Device returns a NUL-padded sync key; libraries accept it | **[GEN]** | Unfixed in both libraries **[V-code]** |
| F6 | Entry stuck in `failed_unload`, device unavailable, only HA restart helps | aiocoap context shut down twice (`'NoneType' object has no attribute 'values'`) | **AC3210/12 [SIB]** | kongo09 open (#397, PR #393); fixed in philips-airctrl 1.5.0 |
| F7 | (tinkerologie >= 2026.10.3) device goes unavailable dozens of times per day | Observation renewal every 60 s with 10 s deadline is not answered by push-on-change firmware | AC2210, AC2220 **[SIB]** | Open (#172, #214); fixed only for "nudge" models |
| F8 | Wrong state for ~3 min after every HA start; a CLI test "steals" updates | Device keeps one observer per client IP, newest GET wins; DHCP-discovery probe registers a second observer | **[GEN]** (AMF870); AC2220 reportedly tolerates 2 clients | Open (PR #389 closed unmerged) |
| F9 | After restart entities show an old state as live (fan "on", old firmware) | kongo09 seeds entities from the status stored at config-entry creation | all models on kongo09 | Open (#394) |
| F10 | HA start blocked 90 s+, "Waiting on integrations", bootstrap timeout | First refresh / client create awaited during setup, per device | all | Mitigated by F9's cache in kongo09; partly open |
| F11 | "Too many open files", sockets accumulate while a device is offline | aiocoap context not shut down when init is cancelled | all | Fixed (aioairctrl 0.3.0, kongo09 v0.36.0) |
| F12 | `[Errno 97] Address family not supported by protocol` | aiocoap default `udp6` transport needs IPv6 enabled on the HA host | all | Fixed (aioairctrl 0.3.1 `simple6`), after a regression that broke IKEA Tradfri |
| F13 | Timeout on setup although ping and the app work | Device on guest Wi-Fi / other VLAN / client isolation / multicast-to-unicast | AC4220 **[SIB]** | User-side; undocumented |
| F14 | Device lost after IP change; devices merged | Entry keyed on host; MAC lookup returns `00:00:00:00:00:00` | AC3210 **[SIB]** (tinkerologie #8) | kongo09 fixed (v0.36.2, v0.37); tinkerologie #8 closed "not planned" |
| F15 | Command acknowledged but nothing happens; power on fails, power off works | String-typed values are acked but ignored by NEW2 firmware; also `{"status":"failed"}` when the session counter is out of sync | AC4221 **[SIB]** | Library behaviour; lamp writes on AC4221 open (#416) |
| F16 | Device stops answering CoAP until it is power-cycled | Device CoAP stack wedges after many session re-creations / nudges | **[GEN]** CX5120; **[OLD]** 2020 reports | Device bug; avoid churn |
| F17 | `Data must be padded to 16 byte boundary in CBC mode` after adding more devices | Unknown; reporter fixed it by disabling push notifications in the Philips app | AC3421 **[GEN]** | Unverified single report |
| F18 | Integration stops loading after an HA update | HA API removals handled late (kongo09) | all | Next deadlines HA 2027.8 / 2027.11 open (#378, #415) |
| F19 | Database bloat (10k+ rows/day/device) | `runtime` attribute and PM2.5 change on every push | all | Open (#395) |
| F20 | Model simply has no local API | Different hardware (ESP32, cloud only) | not the AC3220 family | wontfix |
| F21 | Preset/speed reads back `None` | Preset matching includes D0310D, which the device rewrites | AC3420/AC3421 only; AC22xx/AC32xx match on D03102+D0310C only **[V-code]** | Open for AC3420 (#371) |

### F1. Push-on-change firmware: status reads are not answered until a value changes

What happens on the device side (all **[WF]**, measured on one AMF870/15, `AWS_Philips_AIR_Combo@86`, software 0.9.1, Air+ app not signed in; tinkerologie #132, https://github.com/tinkerologie/ha-philips-airpurifier/issues/132):

- `GET /sys/dev/status` without Observe (NON or CON) or with `Observe: 1` is never answered. With `Observe: 0` it is answered only by the next push: 0.1 to 4 s while the unit is running, and not at all in standby until something changes.
- There is no periodic notification / heartbeat. 99.8 % of ~34,000 notifications changed at least one exposed value (almost always temperature at 0.1 degC resolution). Quiet periods of 12 min to ~2 h occurred about 18 times a day; in 73 of 75 the temperature before/after differed by at most one 0.1 degC step. RSSI changes (up to 13 dB) do not trigger a push.
- During quiet periods `/sys/dev/sync` keeps answering and control writes work (4 of 4 power-on POSTs answered `{"status":"success"}` in 109 to 211 ms).
- Writing a value that actually changes state forces a full status push within 0.1 to 0.8 s; writing the value the device already has is acknowledged but produces no push.

Same behaviour reported elsewhere:

| Device | Firmware | Evidence | Source |
|---|---|---|---|
| CX3550/01 | `AWS_Philips_AIR_Combo@86`, FW 0.1.7 | "silently ignores the initial CoAP GET /sys/dev/status observe=0 and never sends the first status push"; pushes after any encrypted control POST | kongo09 PR #365 https://github.com/kongo09/philips-airpurifier-coap/pull/365 ; also #178, #205 (2024, FW `@2.5`: manual button presses not reported) |
| CX7550/01 | `AWS_Philips_AIR_Combo@86`, FW 0.2.9 | status GET times out after 30 s; a manual state change inside the window forces the push | tinkerologie #82 ; ioBroker.philips-air #377 https://github.com/iobroker-community-adapters/ioBroker.philips-air/issues/377 (one push in 4.5 h of log; adapter 2.1.0 "stop tearing down quiet CoAP sessions and back off failed retries") |
| CX5120/11 | `AWS_Philips_AIR@86.1`, D01S12 0.4.9 | answers plaintext `sys/dev/info` and the sync handshake, never answers status reads; one push per button press | tinkerologie #203 https://github.com/tinkerologie/ha-philips-airpurifier/issues/203 |
| HU1509/HU1510/HU4209 | "newer firmware" | never answers a plain read, only pushes on real changes | tinkerologie release notes v2026.9.1 https://github.com/tinkerologie/ha-philips-airpurifier/releases |
| **AC4221/11 [SIB]** | `AWS_Philips_AIR_Combo@86`, device FW 0.2.3, MAC `67:79:C4:59...` as typed by the reporter | `aioairctrl -H ... --debug status-observe`: `synced: 0E361EE9`, then the observe GET is sent "and after that I get nothing"; Philips app still controls the unit with its internet access blocked at the firewall | kongo09 #293 https://github.com/kongo09/philips-airpurifier-coap/issues/293 and #328 https://github.com/kongo09/philips-airpurifier-coap/issues/328 (closed wontfix / stale, maintainer: "If you don't get an answer, there is nothing I can do") |
| **AC2210 [SIB]** | device 0.2.3, Wi-Fi 86 | one-shot status requests: 683 of 885 timed out (77 %); successful ones took median 10.7 s, p90 24.9 s | tinkerologie #172 https://github.com/tinkerologie/ha-philips-airpurifier/issues/172 |
| **AC2220/10 [SIB]** | `AWS_Philips_AIR_Combo@86` | renewal GET unanswered for 10 s, then status GET unanswered for 30 s, 2 s after the last push | tinkerologie #214 comment 2026-11-22 https://github.com/tinkerologie/ha-philips-airpurifier/issues/214 |
| AC2729/10 [OLD] | `AWS_Philips_AIR@91.1`, 0.3.2 | sync answered in ~10 ms, status GET silent; one reply arrived 18 s after the request | tinkerologie #172 comment 2026-11-18 |
| AC0850 | `@86` | push-on-change | cited in tinkerologie #132 from atdr/homebridge-philipsair-platform (not read by me) |
| AC2220 | `@86` | push-on-change | cited in tinkerologie #132 from chayuto/seeed-XIAO-ESP32-C6 (not read by me; a web search did not find it) |

The oldest description of the same thing is rgerganov/py-air-control #93 (https://github.com/rgerganov/py-air-control/issues/93): on 2021-07-05 AC2889/10 units auto-updated from Wi-Fi firmware 62.1 to `AWS_Philips_AIR@64.3`, after which status requests timed out ("sync timeout", ~1 in 20 calls succeeded) while control commands still worked. User Setcover (2021-08-31): the update "is a bugfix. The purifier sends a new message only when values change", so with stable air quality a request/response client times out, and an observing client works. Later comments in the same thread: status hangs until the Clean Home+ app is opened (2022-06-09); sending any control command from another terminal forces a status message (2022-09-17).

How this surfaces in the integrations:

- kongo09 config flow: `Timeout, host <ip> doesn't answer, aborting` (`config_flow.py:225`/`:232`) after 30 s, "Cannot connect to device". Seen in #295 (AC4220), #300/#313 (AC0951), #184, #173, #135 and many `connectivity` issues. A device in standby with stable readings cannot be added at all unless something changes during the 30 s window. The users in #345 ("suddenly worked the next day after multiple tries", AC2220/10 fw 0.2.1 `@86`) and #40 ("it only finishes loading after the user changes the device's mode or turns it on or off") describe exactly this without knowing the cause **[I]**.
- tinkerologie: `Reconnect to <ip> failed at the status stage (TimeoutError: )`, `Observation of <ip> registered but no initial response after 30 seconds`, diagnostics `last_reconnect_error: {stage: status, type: TimeoutError}`.

Fixes and where they shipped:

- tinkerologie "status nudge": register the observation, then write a harmless setting to a transient value and back (display backlight) so the device pushes a full status. Models: CX7550 (PR #67), HU1509/HU1510/HU4209 (v2026.9.1), AMF870 `D0312D` 0 then 100 (PR #153, v2026.10.1), CX5120 `D03105` 0 then 100 (PR #204, v2026.11.0). **Not declared for `_CONFIG_AC3210` (AC3210/AC3220/AC3221), `_CONFIG_AC2221` (AC2210/AC2220/AC2221) or `_CONFIG_AC4220`** (**[V-code]** `tinkerologie_ha-philips-airpurifier/custom_components/philips_airpurifier/device_models.py:619-634`, `:601`, `:666`; the only `status_nudge=` entries are at `:733/:753` HU1509, `:1422` AMF870, `:1538` CX5120, `:1721` CX7550).
- kongo09: PR #365 (ccoreilly, 2026-06-19; on timeout write beep `D03130=0`, if still nothing toggle `1` then `0`) was reviewed once ("this sounds quite sophisticated. I wonder what other devices might benefit from the same idea"), updated, then closed by the stale bot on 2026-10-09. PR #408 (tugkan98, 2026-10-25, open, unreviewed) does a similar beep-mute nudge but only for AMF870 and AC3420. Nothing merged.
- Side effects of nudging that were found afterwards: the first push after the nudge can still carry the transient value, so the entity shows "display off" until the next real change (tinkerologie #197, 1 in 14 nudges, once for 51 s); the nudge writes had no timeout (#197, fixed PR #207 with 5 s per write); the display turned back on after every HA restart (#155, fixed v2026.10.2 by persisting `last_nudge_values`); the nudge beeps on a CX5120 (PR #208); a nudge waits 24 s on a dead observation when the registration response itself is corrupted (#210, open).

### F2. The silence watchdog treats a quiet device as a dead one

- Mechanism (kongo09): a timer of 3 x Max-Age (Max-Age is 60 s, so 180 s) is reset by every notification; when it fires the coordinator shuts the client down and builds a new one (new UDP socket, new `/sys/dev/sync`, new observe). Introduced as the "reconnect fix" by mhetzi (PR #5, first tag v0.9.3-beta.1, 2022-04-09; released in v0.10.0 on 2022-05-03) **[V-git]**; discussion in #17 https://github.com/kongo09/philips-airpurifier-coap/issues/17 .
- Measured on an idle, healthy AMF870/15 with kongo09 v0.37: "Calling timeout callback" then "syncing" then "synced" then "observing status" every 180 s; **283 full reconnects in one day**; "hundreds of full reconnects (new socket + NON sync) per day for a device that's working fine" (comment on PR #388, https://github.com/kongo09/philips-airpurifier-coap/pull/388 ). Re-registering does not help either: the fresh observe GET is "almost always answered only by the next change" (only ~1 to 2 % answered within 5 s).
- Each reconnect is a chance to hit F3 (lost sync), F5 (bad key), F6 (double shutdown) and F8 (observer displacement), and is the kind of session churn that F16 says can wedge a device.
- User-visible reports: #40 (AC4236, 2022: "timeout callbacks and reconnect attempts every ~3 minutes (`Timer 180s`)"; maintainer: "This is normal"), #38 (state wrong for the first 180 s after a restart, 2022), tinkerologie #92 (AC3039: unavailable after ~9 min in standby, back ~11 min later; opening the Air+ app brings it back), #172 (AC2210 **[SIB]**: 49 of 63 watchdog events between 00:00 and 08:00, about 12 per night; ping stayed at zero loss throughout; cloud app kept working during outages), kongo09 #379 "Aggressive poll rate" (CX3120 `@86`, closed by stale bot unanswered).
- Fix attempts: kongo09 PR #388 "refresh observation without reconnecting client" (beyildirim, 2026-09-04; closed unmerged 2026-11-07 when the author deleted the fork); kongo09 #129 "Make timeout configurable" (2024, closed stale, never implemented); aioairctrl PR #13 "add timeout for observe_status" (open since 2026-06-20, no review). tinkerologie: per-device `missed_package_count` option, range 1 to 20, default 3 (v2026.9.1, #92; **[V-code]** `const.py:58-65`), and a fixed 1800 s watchdog for nudge models (`coordinator.py:41`, `:462`). For non-nudge models such as AC3220 the watchdog is still `Max-Age x missed_package_count`.
- Proposed but not implemented anywhere: a CoAP empty CON ping (code 0.00) every 30 to 60 s as a real liveness probe; the AMF870 answered 2 of 2 pings with RST in under 0.1 s (kongo09 #396 section 3). Note aiocoap 0.4.17 has no public ping API.

### F3. Lost reconnect syncs and lost commands: the device ignores broadcast ARP

Source: kongo09 #396 https://github.com/kongo09/philips-airpurifier-coap/issues/396 (open, opened 2026-10-12, no maintainer reply) and #363 https://github.com/kongo09/philips-airpurifier-coap/issues/363 (open, `enhancement`). Environment: AMF870/15 `@86`, 2.4 GHz UniFi network with DTIM 1, HA 2026.10 in a container with host networking, integration v0.37, aioairctrl 0.3.1, aiocoap 0.4.17; ~50 h and later 13 to 16 days of packet capture on the HA host.

- 32 of 403 reconnect syncs (7.9 %) got no reply; over 13 days 119 of 2,991 (4.0 %, daily 0 to 10 %). **31 of the 32 never left the HA host**: the kernel had no ARP entry for the purifier, sent 3 broadcast ARP requests, got no answer, and dropped the queued UDP packet. The purifier answered unicast ARP 340 of 341 times (99.7 %) but broadcast ARP only 56 of 92 times (61 %), "even seconds after the device had notified HA". Diagnosis: Wi-Fi power save; the device sleeps through DTIM beacons. All failures occurred with the fan off; no Wi-Fi roam/reconnect events on the AP.
- Because `CoAPClient.create()` sends the sync as NON with no timeout and kongo09's `_reconnect()` awaits it with no timeout, the reconnect task hangs until the next 180 s watchdog tick cancels it, and the `CancelledError` is swallowed without logging (**[V-code]** `kongo09_philips-airpurifier-coap/custom_components/philips_airpurifier_coap/coordinator.py:77-93`). Meanwhile `self.client` is the already shut-down client: commands raise `aiocoap.error.LibraryShutdown`, no status arrives, nothing is logged at WARNING. Failures chain (up to 4 in a row, about 12 min; in total about 96 min of deafness in ~50 h).
- Control writes are hit the same way: `POST /sys/dev/control` queued behind a failed ARP lookup is dropped; with no request timeout one call "waited over 7 min", the original #363 report (AC0950/10 `@86`, v0.36.2) hung 1 h 46 min and ended with `LibraryShutdown` at the next HA restart. Flagged Zigbee-button test: 7 presses produced 6 failed-command events, all from this ARP mechanism.
- Diagnostic trick from #396: the `syncing` to `synced` delay tells the ARP retry count (under 0.5 s normal; 0.9 to 1.5 s = answered on 2nd broadcast; 1.5 to 2.5 s = 3rd; no `synced` = packet very likely never sent).
- Proposed fixes (none merged): `asyncio.wait_for(CoAPClient.create(host), 5..10 s)` with a few retries a few seconds apart (each retry triggers a new ARP lookup; two retries would cut 7.9 % to about 1 %); per-attempt timeout plus 2 to 3 resends for control writes; do not use CON blindly ("an aiocoap exchange ends only on ACK or RST, so CON retransmissions could error every pending request to the device, including the observation"; the device answers a CON sync with a NON response reusing the MID rather than an ACK). kongo09 PR #364 (wrap all 28 command call sites in `wait_for` + reconnect + retry once) got one maintainer comment ("I wonder if aioairctrl library wouldn't be a better place") and was closed by the stale bot on 2026-10-02. A static ARP entry on the HA host "would probably mask the problem" (untested). Regular traffic (for example a ping every 30 to 60 s) would keep the neighbour entry warm; an entry expired less than 110 s after an answered probe (tinkerologie #197).
- tinkerologie bounds coordinator CoAP calls with `COAP_CALL_TIMEOUT = 30` (**[V-code]** `coordinator.py:48`, `:221`) and nudge writes with 5 s (PR #207), but `async_set_control_values` ignores a `False` result and there are no resends (tinkerologie #132 comment 2026-10-14).

### F4. Firmware emits corrupted notifications that kill the observe task

- Observation (**[WF]** aioairctrl PR #14 https://github.com/kongo09/aioairctrl/pull/14 , philips-airctrl #44 https://github.com/tinkerologie/philips-airctrl/issues/44 , kongo09 #396): occasionally a status notification's hex ciphertext contains two NUL bytes in place of one byte's hex pair (13 cases) or a single NUL (3 cases), at varying offsets (392 to 2179 of a 2280-character payload). The trailing SHA-256 digest matches the corrupted string and the UDP checksum is valid, so the device computed the digest over already-corrupted data: a firmware bug, not transmission damage. The next push (67 to 78 ms later in two captured cases) is clean.
- Rates: 16 of 85,122 notifications (about 1 in 5,300, ~1.5/day) on the AMF870/15 over 2026-10-11..21; 18 of 87,981 on 10-15..26; 9 of 16,245 in 48 h in November. Also reported on an AC0850 (PR #14 author), on an **AC2210 [SIB]** (2 x `ValueError: non-hexadecimal number found in fromhex()` in 24 h, tinkerologie #172), on a CX3550/01 (`... arg at position 488`, kongo09 #205, 2024-12) and, in 2021, on an AC2729 (`... at position 1069`, py-air-control #73 https://github.com/rgerganov/py-air-control/issues/73 ). So this is long-standing and cross-model.
- Effect with aioairctrl 0.3.1: `bytes.fromhex()` raises `ValueError` (**[V-code]** `kongo09_aioairctrl/aioairctrl/coap/encryption.py:77`), the async generator ends, its `finally` cancels the observation, aiocoap then logs every further notification as "could not be matched to any request" at INFO (invisible by default), kongo09's `_async_observe_status` task ends without logging, entities stay "available" with frozen values until the 180 s watchdog (median 174 s without updates, 293 notifications lost over the 15 cases).
- Effect with philips-airctrl 1.5.0: stream ends, reconnect + resync + nudge (~2 s, invisible) when a notification is hit; when the corrupted packet is the registration response during a nudge, 24 s wait then ~7 s unavailable (tinkerologie #210, open).
- Fix: philips-airctrl PR #45 "skip unreadable observed statuses" (merged 2026-11-15, released 1.5.1). **But `custom_components/philips_airpurifier/manifest.json` on main still pins `philips-airctrl==1.5.0`** (**[V-code]** line 37 at `550c88a`; tinkerologie #217, open, opened 2026-11-20): Dependabot only bumped `pyproject.toml`/`uv.lock`. kongo09/aioairctrl PR #14 is open since 2026-09-16 with no maintainer response and does not cover a corrupted first response.

### F5. NUL-padded sync key

- Twice in 1,317 sync replies in 8 days and once in ~2,000 in another capture the device answered `/sys/dev/sync` with a short key padded with NULs, logged as `synced: 31\0\0\0\0\0\0` / `33\0\0\0\0\0\0` (aioairctrl PR #14 comments 2026-10-12 and 10-21). Notifications still decode (each carries its own key) but `encrypt()` raises before sending, so every command fails until the next sync (9 min in the observed case).
- Independent user report with the tell-tale error: kongo09 #376 https://github.com/kongo09/philips-airpurifier-coap/issues/376 (AMF870/15, 2026-07-28): `Failed to perform the action fan/set_preset_mode. invalid literal for int() with base 16: '27AA\x00\x00\x00\x00'`. The reporter blamed v0.37 and downgraded; the stale bot closed it on 2026-10-04 with no human reply. **[I]** it is this firmware quirk, not a v0.37 regression.
- Neither library validates the key: aioairctrl `encryption.py:39` `int(self._client_key, 16)`, philips-airctrl `src/philips_airctrl/coap/encryption.py:29-35` (**[V-code]**). Proposed: reject a key that is not exactly 8 hex characters and re-sync immediately.

### F6. Double shutdown of the aiocoap context

- Traceback (identical in all reports): `aiocoap/messagemanager.py`, line 78, in `shutdown`: `for messageerror_monitor, cancellable in self._active_exchanges.values()` raising `AttributeError: 'NoneType' object has no attribute 'values'`.
- kongo09 #397 https://github.com/kongo09/philips-airpurifier-coap/issues/397 (**AC3210/12 [SIB]**, fixed IP, v0.37, HA 2026.10.1, Python 3.14; opened 2026-10-14, open, no reply): unload during a nightly HA restart/backup fails at `__init__.py:201` -> `coordinator.py:61` `await self.client.shutdown()`; the entry is left in `failed_unload`, the device is unavailable, "Reload" is not offered, reconfiguring gives `options flow: timeout connecting to host`, only a full HA restart recovers. Code matches (**[V-code]** `coordinator.py:51-61`: the client shutdown in `shutdown()` is not suppressed, while `_reconnect()` suppresses it at `:80-81`).
- Root cause per PR #393 https://github.com/kongo09/philips-airpurifier-coap/pull/393 (ovflowd, 2026-09-19, open, no review): `_reconnect()` shuts the old client down, `CoAPClient.create()` then hangs or fails (F3), `self.client` keeps pointing at the torn-down context, and the later `shutdown()` raises. Because `shutdown()` cancels the reconnect task and the timer before it crashes, "the coordinator never retries on its own". Also `Timer.cancel()` raises `CallbackRunningException` when called mid-callback. Confirmed by a second user on an AMF870 ("status updates stopped silently, entities stayed available with frozen values for about an hour ... reloading gave `failed_unload`"). Duplicate PR #398 by the AC3210 owner was withdrawn in favour of #393 on 2026-10-18. Same traceback in older issues #27 (2022), #127 (2024), #291 (2026-02).
- tinkerologie: the same double shutdown produced `Task exception was never retrieved` 304 times in 8 h on a CX5120 (#198); fixed by making `CoAPClient.shutdown()` idempotent (philips-airctrl #36 / PR #40, release 1.5.0) and by PR #199 "shut each CoAP client down exactly once" (v2026.11.1). A follow-up, #209 (HU1509, 2026.11.0: service calls fail with "Client not initialised or already shut down"), is open.

### F7. Observation renewal regression (tinkerologie 2026.10.3 and later)

- Trigger: philips-airctrl #34 https://github.com/tinkerologie/philips-airctrl/issues/34 (2026-10-27): on an **AC4220/12 [SIB]** with firmware 0.2.3, `observe_status()` went silent ~2.5 min after registration (last push at 2m42s and 2m31s in two sessions) although the device reported `Max-Age: 60`, pushed every 1 to 5 s before, and answered a fresh sync in ~100 ms. Interpretation: the device drops an observation that is not re-registered. (Whether this is a true expiry or the push-on-change quietness was not separated; "whether the lifetime differs at night (AC2210) or between models" is listed as unresolved in the issue.)
- Change: philips-airctrl 1.4.0 (PR #35, 2026-10-28) re-registers with a new token every Max-Age (60 s) on the same session and raises if the renewal GET is not answered within `RENEWAL_TIMEOUT = 10.0` s (**[V-code]** `tinkerologie_philips-airctrl/src/philips_airctrl/coap/client.py:29`, `:273-335`). Validated on the AC4220 only while it was actively pushing (106 pushes in 270 s). Shipped in integration 2026.10.3.
- Result on push-on-change devices: the renewal GET is answered only if a value changes within 10 s, otherwise the stream ends with `TimeoutError`, the coordinator reconnects, and the reconnect's status read (30 s) fails for the same reason.
  - **AC2210 [SIB]** (tinkerologie #172): 118 outages / 10 h 22 min unavailable in 24 h on 2026.10.3 versus 14 outages / 3 h 21 min on 2026.10.2. In a 24 h debug log: 414 renewals, 196 (47 %) unanswered within 10 s; "after >= 50 s silence, 88 % of renewals failed"; 103 of 107 outages followed a failed renewal.
  - **AC2220/10 [SIB]** `@86` (tinkerologie #214, comment 2026-11-22): 5 unavailable periods in 8.5 days on kongo09 v0.37 versus 56 in 30 h on tinkerologie 2026.11.1 (5 to 40 s each).
  - AMF870/15: 35 of 51 renewals failed in 1 h of standby; 0 reconnects in the same hour on 2026.10.2.
  - CX5120/11: a reconnect plus display nudge plus beep every minute; "after a few dozen rounds its CoAP stack stalled until a power cycle" (PR #208).
  - AC3033/14 (Wi-Fi 73.1), AC1715 (Wi-Fi 91.1), AC2729/10 (`@91.1`): same `status`-stage timeouts (#214, #172).
- Partial fix: PR #208 (v2026.11.1) passes `renew_interval=1800` only when the model has a `status_nudge`; all other models keep the 60 s default (**[V-code]** `coordinator.py:424`). So on tinkerologie 2026.11.1 an AC3220 with `@86` firmware gets the worst case: no nudge, 60 s renewals with a 10 s deadline, 180 s watchdog.
- Workarounds reported: roll back to 2026.10.2 (philips-airctrl 1.3.0, no renewal); raise `missed_package_count`. Requests still open: keep the old observation when a renewal is not answered, make renewal optional per device, longer/retrying status read.

### F8. One observer per client IP: a second client steals the notifications

- Twice on the AMF870 a second client on the same host (HA's DHCP-discovery config-flow probe at startup) fetched status shortly after the coordinator had started observing; the next push answered only the second client's GET and the coordinator's observation received nothing until the 180 s watchdog rebuilt its client (tinkerologie #132 item 6; kongo09 PR #389 comment with timestamps: coordinator observe at 21:32:49.464, DHCP step at 21:33:14.976, probe got status at 21:33:28.280, watchdog at 21:35:49.465).
- kongo09's DHCP flow probes the device before it checks whether the host is already configured, so this happens on every HA start for an already configured device; a timed-out probe also leaves a UDP socket behind. This is the 2022 issue #38 ("status wrong for the first 180 s after a restart") and the endless `Timeout, host ... looks like a Philips AirPurifier but doesn't answer, aborting` warnings for configured devices (#39, #135).
- Debugging trap: running `aioairctrl status-observe` or `coap-client` on the HA host takes the stream away from the integration for up to 3 min (#396 debugging note).
- Counter-evidence: "someone running two clients on an AC2220 `@86` reported both working, so behaviour may vary by model" (tinkerologie #132). Whether the limit is per source IP or per device is not established for the AC3220.
- Fix: kongo09 PR #389 "prevent duplicate discovery observers" (abort discovery before connecting when the host is already configured; one shared probe helper; always close the probe client) was closed unmerged on 2026-11-07. tinkerologie's planned repair flow was criticised for the same reason (opening a temporary client while the observer runs, #214 bot analysis).

### F9. Stale cached status presented as live after every restart (kongo09)

- kongo09 `async_setup_entry` seeds the coordinator with `entry.data[CONF_STATUS]`, the status captured when the config entry was created (**[V-code]** `__init__.py:156-171`). Introduced to stop setup from blocking (see F10; "store the last device readings ... and use that data at startup, rather than querying devices", #199, v0.25.0, 2024-11-23). The stored status is written once and never refreshed.
- #394 https://github.com/kongo09/philips-airpurifier-coap/issues/394 (open, 2026-10-09): after each of four loads entities showed "fan on, preset auto, firmware 0.8.9 / `@1.2`" (entry created 2024-09-29) while the device was off on firmware 0.9.1 / `@86`, for 3:01 to 4:11 min on HA starts and until a forced change on reload. In standby it could last up to ~2 h. Automations and HomeKit act on the stale state.
- Also #394: in 4 of ~43 commands the existing observation got 0 to 1 notifications afterwards and the next value arrived 120 to 222 s later, after the watchdog reconnect; twice the power change itself was not pushed. Cause not established (observation dropped vs firmware withholding).

### F10. Setup blocking and slow startup

- kongo09 #25 (2022): first refresh blocked HA start for 3 min when the device did not answer; #76 and #199 (2024): 92.2 s startup with three devices because of a per-device `asyncio.wait_for(CoAPClient.create(host), timeout=25)`; "Waiting on integrations to complete setup: philips_airpurifier_coap" (#83). Mitigated by the cache of F9 (PR #186 v0.22.0, PR #204 v0.25.0 **[V-git]**). #25 comment 2024-11-12: "still hangs for ages" when devices are off.
- tinkerologie #6/#8: "CancelledError: Global task timeout: Bootstrap stage 2 timeout" cancelling setup.

### F11. Socket / file-descriptor leak while a device is unreachable

- kongo09 #323 https://github.com/kongo09/philips-airpurifier-coap/issues/323 : open socket FDs accumulate while a configured device is unreachable; the 25 s setup timeout cancels `CoAPClient.create()` during `_sync()`, and `except Exception` did not catch `asyncio.CancelledError`, so the aiocoap context was never shut down. Fixed in aioairctrl PR #9 (0.3.0, `except BaseException`; **[V-code]** `client.py:52`) and shipped in kongo09 v0.36.0 (PR #325, 2026-03-01 **[V-git]**). Same class of problem in 2022: chrysn/aiocoap #296 ("OSError: [Errno 24] Too many open files" from `udp6.create_client_transport_endpoint`; chrysn: usually means too many contexts are created, one should suffice).
- aioairctrl PR #9 also removed a stale monkeypatch that had disabled aiocoap message deduplication, made `set_control_values` re-sync at most once, cancels the observation when the generator is closed, and fixed a counter overflow at `0xFFFFFFFF`.

### F12. IPv6 disabled on the HA host

- `OSError: [Errno 97] Address family not supported by protocol` from `aiocoap/transports/udp6.py:356` (`socket.socket(family=AF_INET6, ...)`): kongo09 #162 (AC2729/10, fix = re-enable IPv6 in GRUB), #256, #129; upstream chrysn/aiocoap #222 (wontfix: "aiocoap is not ever expected to work on a system where IPv6 is turned off"; advice: firewall IPv6 instead of disabling it).
- Fix history **[V-git]**: commit `3eb702e` (2026-01-31, v0.35.0) set `AIOCOAP_CLIENT_TRANSPORT`/`AIOCOAP_SERVER_TRANSPORT=simple6` process-wide from `config_flow.py`; this broke the core IKEA Tradfri integration (`NoRequestInterface()`, "Failed to register with provided code", #322) because the env var applies to every aiocoap user in the HA process; commit `36b186e` (2026-03-01, v0.36.2) removed it and aioairctrl 0.3.1 passes `transports=["simple6"]` to its own context only (**[V-code]** `kongo09_aioairctrl/aioairctrl/coap/client.py:48`). The same conflict existed in 2021 (betaboon/philips-airpurifier-coap #64, #70).
- Lesson: never touch process-global aiocoap state from an integration; aiocoap is shared with other HA integrations.

### F13. Network segmentation

All closed as `connectivity`/`invalid`; the resolution was always on the user's network:

| Issue | Device | What it was |
|---|---|---|
| kongo09 #295 https://github.com/kongo09/philips-airpurifier-coap/issues/295 | **AC4220/10, fw 0.2.3 [SIB]** | on guest Wi-Fi; worked after moving to the main network (reporter first suspected "Philips disabled local access in recent firmware") |
| #300 comment | AC0950/10 | not reachable across VLANs |
| #83 | AC2889/10 | routing/firewall on a UDM Pro; another user: OpenWrt "Multi To Unicast" ON stopped the disconnects |
| #345 | **AC2220/10, fw 0.2.1 `@86` [SIB]** | HAOS VM on TrueNAS; "suddenly worked" next day (more likely F1 **[I]**) |
| #264 | n/a | HA with two NICs; DNS/internet missing on the IoT side |

### F14. IP changes and device identity

- kongo09: #112 (2024): no way to change the IP; v0.18.3 re-adding at the new IP updates the entry; reconfigure flow added in v0.36.2 (PR #335) **[V-git]**; MAC obtained via `getmac`/ARP is unreliable, and #370 (2026-07): the MAC was sometimes `00:00:00:00:00:00`, which made HA merge three purifiers into two devices; fixed in v0.37 (PR #373).
- tinkerologie #8 (**AC3210 [SIB]**, 2026-03): after the purifier got a new IP the integration went into an error state and discovery did not repair it (bot analysis: DHCP flow times out on the new IP and aborts with `model_unsupported`); closed "not planned" 2026-06-17.

### F15. Commands acknowledged but not executed

- **Typed values.** On NEW2 devices a control value sent as a JSON string is acknowledged with `{"status":"success"}` but ignored, except that `"0"` works as off. kongo09 #326 (CX3120/01): "Commands for D03 keys only take effect when sent as integer"; kongo09 #247 and philips-airctrl #1 (**AC4221/11 [SIB]**): `set D03102=1` fails, `set D03102=0` works; `philips-airctrl set -H <ip> -I D03102=1` works. So "status: success" is not proof of execution, and CLI tests without the integer flag produce false negatives.
- kongo09 #416 https://github.com/kongo09/philips-airpurifier-coap/issues/416 (**AC4221/11 PureProtect Pro 4200, fw 0.2.3 `@86` [SIB]**, open, 2026-11-14): lamp can be turned off locally but not on, scenes cannot be changed; every "on" attempt (`D03105=101`, `D03135=1`, `D03135=2 D03137=2`, ...) left or turned the lamp off, while power/mode/child-lock writes worked. The app changes `D03105` and `D03135` together and `StatusType` switches from "status" to "control" after some app commands. Unanswered. **[I]** the pattern "non-zero values behave like 0" looks like the string-typing artefact above (the report used `aioairctrl ... set` and does not say whether `-I` was used), so it must be re-tested with integer values before concluding the lamp is cloud-only.
- **Session counter.** kongo09 #40 log: `RESPONSE: b'{"status":"failed"}'` -> `set_control_value failed. resyncing...` -> `synced: 161A0377` -> retry -> success. The library handles it; before aioairctrl 0.3.0 it re-synced on every retry recursively.
- **Half-dead device.** 2022 reports (#17, #18, #39, #40, #62, betaboon #74): "the device keeps broadcasting but doesn't accept any direct calls via CoAP", or controls work without status updates; switch flips back to off after a few seconds; a power-on took effect 180 s later after the reconnect. Opening the AirMatters / Clean Home+ / Air+ app made the device respond again (#40; py-air-control #93; tinkerologie #92). In hindsight most of this is F1+F2+F3, but the "app wakes it up" observation is unexplained (candidates: the app's own control write forces a push, or it wakes the Wi-Fi module so ARP resolves **[I]**).

### F16. Device stops answering CoAP until it is power-cycled

- 2020, py-air-control #58 https://github.com/rgerganov/py-air-control/issues/58 (AC3829/10, AC1214): polling every 2 min with a new session each time worked for under an hour, then the device stopped answering (the Air Matters app too) until power-cycled. Analysis in the thread: every request set the Observe option and observations were never cancelled; frequent handshakes "may crash the device's network stack"; theory of a fixed session limit without cleanup.
- 2026, tinkerologie PR #208 (CX5120/11 `@86.1`): one reconnect + nudge per minute; the device's CoAP stack stalled twice within ~20 min and needed a power cycle; with a 30 min cycle, no stalls in 24 h.
- kongo09 README (since 2022-04-02, **[V-git]** commit `331834a`; **[V-code]** `README.md:20`): "Due to a bug in the Philips devices, this integration is rather instable ... Sometimes, a power cycle of the Philips device helps. Sometimes, only a power cycle and a Home Assistant restart together help."
- Design consequence: keep one long-lived session and one observation per device; make reconnects rare and backed off.

### F17. CBC padding error after adding more devices

- kongo09 #305 (2026-01, AC3737 + AC0951 + AC3421): first device stopped working when two more joined; `Failed to connect: Data must be padded to 16 byte boundary in CBC mode`; reporter closed it with "PUSH Notifications must be disabled in the management app for all devices". No maintainer analysis. Unverified; possibly a truncated/corrupted payload (F4 class) **[I]**.

### F18. Breakage from Home Assistant API changes (maintenance lag)

| When | Issue(s) | Cause | Fixed in |
|---|---|---|---|
| 2022-08, 2022-12 | kongo09 #46, #47, #50 (titles only: "Stopped working since 2022.8.2", "Broken in new home-assistant version") | HA core changes (not read in detail) | n/a |
| 2024-10, 2024-12 | #156, #235 (titles only: "not working after update to HA 2024.10.1", "Problem after update HAss to 2024.12.5") | not read in detail | n/a |
| 2025 | #245, #260, #272 | `DhcpServiceInfo` import deprecated | v0.34.3 (2025-09-07, PR #275) |
| 2025-10 | #282 (AC0850/11) | v0.34.3 no longer imports on HA 2024.11 ("Platform ... config_flow not found"); user first blamed a firmware update to `@86`, then found that downgrading the integration fixed it | n/a (min HA version in `hacs.json` is wrong) |
| 2026-01/02 | #290, #308, #321 | `ListingView` object has no attribute `hass` (fixed v0.35.0); `module 'homeassistant.components.dhcp' has no attribute 'DhcpServiceInfo'` on HA 2026.2.1 (#321; the import had been fixed in v0.34.3, so affected users were on older releases) | v0.34.3 / v0.35.0 |
| 2026-03-01 | #330, #331, #333, #334 | v0.36.0 shipped `"aioairctrl=0.3.0"` (single `=`), config flow 500 | v0.36.1 same day |
| 2026-08 | #386 | all auto-derived entity icons in HA disappear when the integration is enabled (suspected: the custom `pap:` icon set) | closed by stale bot, uninvestigated |
| 2027-08 / 2027-11 | #378, #415 (open) | `CONCENTRATION_MICROGRAMS_PER_CUBIC_METER` removed in HA 2027.8 (module-level import: integration will not load), `_attr_temperature_unit` in 2027.11 | PRs #377 (closed stale), #401 (open) |

tinkerologie had its own import breakage (#151 `ImportError: cannot import name 'HumidifierDeviceClass'`, v2026.10.0, fixed 2026.10.1) and now runs CI against HA dev.

### F19. Recorder load

- kongo09 #395 (open, 2026-10-10; three AC3421/13): the fan entity's `runtime` attribute changes with every push: about 11,600 to 16,200 state rows per device per day against 14 to 22 real state changes per week; ~500 MB/month for three devices. Request: mark `runtime` as an unrecorded attribute.
- #304 (2026-01): `sensor.*_pm2_5` 11,723 rows in 24 h ("over 7 times a minute"). Maintainer: the integration is push-based, there is no polling interval.
- tinkerologie v2026.10.3 disables RSSI, runtime and speed diagnostics for new installs.

### F20. Models without local CoAP

- AC0650/AC0651 (600 series): many requests, all `wontfix` ("nobody has found a way to talk to the AC0651", kongo09 #318; tinkerologie #1: connection refused).
- AC0720/10 "PureProtect Lite 700": MAC vendor Versuni (`E4:BC:96`), hostname `espressif`, device firmware 0.2.3, Wi-Fi firmware 1.8.0; UDP 5683 and 5684 closed, no open TCP port (tinkerologie #215, open, 2026-11-19).
- kongo09 #303 (AC3259): maintainer: "the same model number can have different firmware, with some versions working and others not".
- These are a different Wi-Fi platform from the AC3220 (`AWS_Philips_AIR_Combo`, MXCHIP). Note that "PureProtect" is a marketing family that spans both platforms, so the name alone proves nothing; `WifiVersion`/open UDP 5683 does.

### F21. Preset read-back on NEW2 devices

- kongo09 #371 (open; AC3420/10 fw 0.2.3 `@86`): `preset_mode`/`percentage` are `None` because the match patterns include `D0310D` (NEW2_MODE_C), which the humidifier rewrites. Not applicable to the AC3220: `PhilipsAC22xx` (parent of `PhilipsAC3210` -> `PhilipsAC3220`) matches on `D03102` and `D0310C` only (**[V-code]** `philips.py:799-843`, `:1173-1184`). Worth knowing anyway because `D0310D` is not a stable mode identifier on the siblings either (section 4.2).

## 4. Everything specific to the AC3220 and its siblings

"Siblings" here: AC3210/AC3220/AC3221 (PureProtect 3200), AC4220/AC4221 (PureProtect Pro 4200), AC2210/AC2220/AC2221 (PureProtect Quiet 2200). They share the D0xxxx datapoint generation and, in kongo09, one class family: `PhilipsAC3220 -> PhilipsAC3210 -> PhilipsAC22xx -> PhilipsNew2GenericFan`, `PhilipsAC4221 -> PhilipsAC4220 -> PhilipsAC22xx` (**[V-code]** `philips.py:799`, `:1173-1184`, `:1612-1619`). The AC4231/10 is **not** a sibling despite the number: it reports old-generation keys (`pwr`, `mode`, `WifiVersion AWS_Philips_AIR@91.1`) and was mapped to the AC4236 (kongo09 #357, PR #358, v0.37).

### 4.1 Support history

| Date | Event | Source |
|---|---|---|
| 2024-10-11 | AC4221/11 support requested; 48 comments of bring-up (fw 0.1.9, `AWS_Philips_AIR_Combo@3.0`) | kongo09 #160 https://github.com/kongo09/philips-airpurifier-coap/issues/160 (only ~31 of 48 comments visible to me) |
| 2024-11-02 | AC4220/AC4221 merged (PR #176), **v0.20.0** | **[V-git]** |
| 2024-11-02 | AC3220/AC3221 requested: "from same series as AC4220/AC4221, just smaller and without gas sensor" | kongo09 #181 https://github.com/kongo09/philips-airpurifier-coap/issues/181 |
| 2024-11-04 | PR #183 "add new models AC3210, AC3220, AC3221", **v0.21.0**. Tester: "Works, with a little strange behavior of display backlight" (never detailed; issue closed) | **[V-git]**, #181 |
| 2024-11-03 | README gains the note "Some of these models seem to have a newer firmware that does not allow local connections anymore..." in the same commit that added AC3210/AC3220/AC3221 (`2a8bc9b`) | **[V-git]**, **[V-code]** `README.md:62` |
| 2026-01-31 | AC2210/AC2220/AC2221 (PR #311: "applying the 32xx family parameters to the 2200 model"), **v0.35.0** | kongo09 #306, #288, #307; **[V-git]** |
| 2026-02..06 | tinkerologie: AC3210 ambient-light issue (#6), AC2221/13 (#26), AC2210/10 (#58) | tinkerologie tracker |
| 2026-10-02 | tinkerologie PR #125 adds AC2220 (fw 0.2.3, `@86`), mapped to `_CONFIG_AC2221` | https://github.com/tinkerologie/ha-philips-airpurifier/pull/125 |

### 4.2 Status dumps posted in issues (primary data for mapping)

**AC3220/10** (kongo09 #181, 2024-11-02; "Auto mode, light off, 1 PM2.5, 1 IAI, 47% humidity, 21.2 degC"):

```
D01102 0   D01S03 "Salon"  D01S04 "Unicorn"  D01S05 "AC3220/10"  D01107 0  D01108 3  D01109 3
D0110A 0   D0110C 19  D01S0D "688001001384"  D0110F 3  D01S12 "0.1.9"  D01213 0
ProductId "<product_id A>"  DeviceId "<device_id A>"
otacheck false  Runtime 317641004  rssi -49  wifilog false  blelog false  free_memory 154416
WifiVersion "AWS_Philips_AIR_Combo@3.0"  StatusType "status"  ConnectType "Online"
D03102 1   D03103 0   D03105 0   D03106 1   D0310A 2   D0310C 0   D0310D 1   D03110 0   D03211 0
D03115 0   D0311F 0   D03120 1   D03221 1   D03224 212 D03125 47  D0312A 1   D0312B 1   D0312C 4
D03130 100 D03134 0   D03135 0   D03136 0   D03240 0   D03180 0   D03182 1   D03R81 "AAEBAQIBAgID\n"
aqit_ext 0 D05102 3   D05207 720 D05408 9600  D0520D 621  D0540E 9501
```

**AC2210/10** (kongo09 #306, 2026-01-08; fw 0.2.1, `@86`, `D01S04 "Cobra"`): same key set minus `D03224`/`D03125`/`D03115` (no temperature/humidity keys in the dump as relayed to me), plus `D03104 0`, `D03112 0`, `D0313B 20`, `D03137 3`, `D0110B 0`, `blelog -1`, `free_memory 94512`, `D05408 19200`. A second AC2210/10 dump (tinkerologie #58, fw 0.2.3 `@86`, bought June 2026): `D03105 101, D0310A 2, D0310C 0, D0310D 2, D03120 4, D03221 17, D03130 100, D03134 1, D03135 2, D03137 1, D03180 1, D05207 720, D05408 19200, D0520D 708, D0540E 19188`.

Datapoint meanings established in the threads (kongo09 #160, #181, #306, #416; tinkerologie #58; constants in kongo09 `const.py:456-496` **[V-code]**):

| Key | Meaning | Values seen on siblings |
|---|---|---|
| D01S03 / D01S05 / D01S12 | name / model / device firmware | "AC3220/10", "0.1.9" |
| D01S04 | platform codename | "Unicorn" (AC3220, AC4221), "Cobra" (AC2210) |
| D03102 | power | 0/1 (must be written as integer, F15) |
| D03103 | child lock | 0/1 |
| D03105 | display brightness | 0 off, 115 low, 123 bright, 101 auto (AC4221; "stays at 101 when off or in sleep") |
| D0310C | mode | 0 auto, 1..5 manual speed, 17 sleep, 18 turbo, 19 medium; reads -16 when powered off (AC4221, #416) |
| D0310D | actual speed level | follows D0310C for 1..4, 18 for speed 5 and turbo, 3 for medium; 0, 1 or 2 seen in auto (so it floats with the auto algorithm: do not match presets on it) |
| D03110 / D03211 | timer step / timer minutes | 0 off, 2 = 1 h, 3 = 2 h / 60, 120 (a 30-minute preset set from HA "did nothing" on the AC4221, #160) |
| D03120 | indoor allergen index | 1..12 |
| D03221 | PM2.5 | ug/m3 |
| D03122 | gas level | AC4221 only (the AC3220 has no gas sensor) |
| D03125 / D03224 | humidity % / temperature x10 | 47 / 212 (present in the AC3220 dump) |
| D03130 | beep | 100 on, 0 off |
| D03134 | "standby sensors" | 0/1 |
| D03135 | lamp function | 0 off, 1 air-quality, 2 ambient colour |
| D03137 | ambient scene | 1 warm, 2 dawn, 3 soft, 4 cool |
| D03180 | Auto Plus (AI) | 0/1 |
| D05207 / D0520D | pre-filter total / remaining hours | 720 / 621 |
| D05408 / D0540E | filter total / remaining hours | 9600 / 9501 (AC3220), 19200 (AC2210) |
| D0312A, D0312B, D0312C, D0313B, D03R81 (base64), D03106, D03182, D03136, D03240 | not identified in any issue | |
| StatusType | "status", sometimes "control" after app commands | |

### 4.3 Feature gaps, wrong mappings, model-specific bugs

- **kongo09 drops the lamp and timer selects for the 3200 series.** `PhilipsAC3210.AVAILABLE_SELECTS = [PhilipsApi.NEW_PREFERRED_INDEX]` replaces the parent's `[NEW2_TIMER2, NEW2_LAMP_MODE, NEW2_PREFERRED_INDEX]`, so AC3210/AC3220/AC3221 get no lamp-mode (D03135), no ambient-scene (D03137) and no timer entity (**[V-code]** `philips.py:1173-1176` vs `:849-853`). The one select that remains points at `NEW_PREFERRED_INDEX = "D03-42"` (`const.py:451`), a key that does not occur in the AC3220/10 dump of #181; the dump has `D0312A`, which is `NEW2_PREFERRED_INDEX = "D0312A#1"` (`const.py:497`). So the preferred-index select is most likely mis-mapped for the AC3220 as well **[I]** (the 2024 tester did not report on it). tinkerologie's `_CONFIG_AC3210` uses the same `NEW_PREFERRED_INDEX = "D03-42"` constant (`const.py:428`, `device_models.py:630`). tinkerologie's `_CONFIG_AC3210` has `NEW_PREFERRED_INDEX`, `NEW2_LAMP_MODE`, `NEW2_AMBIENT_LIGHT_MODE` but no timer (**[V-code]** `device_models.py:619-634`).
- **Ambient light on the AC3210** (tinkerologie #6, 2026-02): the Air+ app lets the user pick the lamp colour/scene; HA showed an ambient-light entity whose only option was "Auto". Closed "completed" on 2026-06-07 with no linked change; the reporter's follow-up was never answered. Treat as unresolved.
- **Display backlight** (kongo09 #160, #181): the device's "Auto" brightness (101, uses a light sensor) has no clean HA light representation; on v0.20.0-beta.10 the backlight switch sometimes stayed on after the light was turned off, and changing brightness from Auto left an intermediate level until reload. Maintainer: "this is as good as it gets".
- **Lamp writes on the AC4221/11** (kongo09 #416, open): see F15.
- **Gas level D03122 received but not exposed** on the AC4221/11 (kongo09 #380, closed by stale bot unanswered).
- **Pre-filter percentage**: integration showed 0 % and "clean pre-filter" while the purifier itself did not ask for cleaning and could not be reset; cause: remaining hours / total hours rounded to 0 (kongo09 #413, open; model not stated).
- **Unload crash on the AC3210/12** (kongo09 #397, F6).
- **IP change not followed** on an AC3210 (tinkerologie #8, F14).
- **Power on via CLI without integer flag fails** on the AC4221/11 (F15).
- **Connectivity on new firmware**: AC4221/11 0.2.3 `@86` never added successfully in kongo09 #293/#328; AC2220/10 0.2.1 `@86` only "after multiple tries" (#345); AC2210/AC2220 flapping in tinkerologie #172/#214 (F1, F2, F7).

### 4.4 Firmware seen on sibling devices

| Model | Device FW (D01S12) | WifiVersion | Reported | Source |
|---|---|---|---|---|
| AC4221/11 | 0.1.9 | `AWS_Philips_AIR_Combo@3.0` | 2024-10 | kongo09 #160 |
| **AC3220/10** | 0.1.9 | `AWS_Philips_AIR_Combo@3.0` | 2024-11 | kongo09 #181 |
| AC4220/10 | 0.2.3 | not given | 2025-12 | kongo09 #295 |
| AC2210/10 | 0.2.1 | `AWS_Philips_AIR_Combo@86` | 2026-01 | kongo09 #306 |
| AC4221/11 | 0.2.3 | `AWS_Philips_AIR_Combo@86` | 2026-02 | kongo09 #293, #328 |
| AC2220/10 | 0.2.1 | `AWS_Philips_AIR_Combo@86` | 2026-03 | kongo09 #345 |
| AC2210/10 | 0.2.3 | `AWS_Philips_AIR_Combo@86` | 2026-06 (new purchase) | tinkerologie #58 |
| AC2220 | 0.2.3 | `AWS_Philips_AIR_Combo@86` | 2026-10 | tinkerologie PR #125 |
| AC4220/12 | 0.2.3 | not given | 2026-10 | philips-airctrl #34 |
| AC2210 | 0.2.3 | "86" | 2026-10 | tinkerologie #172 |
| AC4221/11 | 0.2.3 | `AWS_Philips_AIR_Combo@86` | 2026-11 | kongo09 #416 |
| AC2220/10 | not given | `AWS_Philips_AIR_Combo@86` | 2026-11-22 | tinkerologie #214 |

**[I]** Every sibling reported since January 2026 runs Wi-Fi firmware `@86` with device firmware 0.2.1 or 0.2.3. An AC3220/10 bought in the Netherlands in 2026 should be expected to report the same (or to update to it once it has been online with the Air+ app), which puts it in the push-on-change population. No issue contains a 2026 dump from an AC3220 itself, so this is an expectation, not a fact. The `@3.0` units of 2024 were added and tested without any report of the F1 symptoms in the threads I could read, which is weak evidence that `@3.0` answered status reads normally.

Other `WifiVersion` strings seen for the wider population, for a firmware matrix: `AWS_Philips_AIR@62.1`, `@64.3`, `@67.5`, `@68.3`, `@69.1`, `@73.1`, `@86.1`, `@91.1` (older MXCHIP generation, old `pwr`/`mode` keys or mixed); `AWS_Philips_AIR_Combo@1.2`, `@2.5`, `@3.0`, `@86` (Combo generation). Version numbers are not ordered across the two families.

## 5. The claimed "device firmware bug": what the evidence actually is

What the maintainers say:

- kongo09 README since 2022-04-02: "Due to a bug in the Philips devices, this integration is rather instable. It might or might not work. Even if it seems ok at first, it might stop working after a while. ... Do not report this as an issue here. Nobody can help right now." (**[V-code]** `README.md:20`).
- kongo09, 2022-04-22 (#17): the device "used to work well in the past" but "got very instable after a forced firmware update"; Philips did not reply to him; he is "not an engineer enough to debug this on protocol level". 2022-05 (#39, #40): "the connectivity problem that bugs us all", "It's beyond me to fix this". 2022-12 (betaboon #74): the problem exists "since a firmware update over a year ago".
- kongo09, 2022-03-28 (py-air-control #93): a capture shows "the device sometimes stops sending CoAP while still talking to Amazon servers"; firmware 67.5, later 69.1/68.3 on his AC2889/AC2729.

What was actually demonstrated, by whom, and how reproducible it is:

| Phenomenon | Evidence quality | Reproducible? |
|---|---|---|
| Status is only pushed on value change; reads are not answered until then (F1) | Packet captures + debug logs over days on one AMF870/15 (mbreitkreuz); independent confirmation on CX3550 (ccoreilly), CX5120 (arminfauland), CX7550 (DavidV98), AC2210 (Luke2105-Loft59), 2021 analysis by Setcover on AC2889 fw 64.3 | Yes, deterministically: leave the device idle and read; or write a changed value and watch the push arrive in 0.1 to 0.8 s |
| No heartbeat; quiet periods up to ~2 h in standby | Same captures; 75 quiet periods analysed | Yes |
| Device answers broadcast ARP unreliably (61 %) while answering unicast ARP (99.7 %) | 50 h to 16 days of capture on the HA host, UniFi AP, DTIM 1 | Statistically; probably AP/DTIM dependent. Only one site measured |
| Corrupted notifications with valid digest (F4) | Captures with offsets and digests; four independent users over 5 years | Not on demand; ~1 in 2,000 to 5,000 pushes; can be simulated by injecting NULs and re-signing |
| NUL-padded sync key (F5) | Log lines + one independent user error | Not on demand; ~1 in 700 to 2,000 syncs |
| Observation lapses ~150 s after registration unless renewed (F7) | One live test on an AC4220/12 fw 0.2.3 (ruaan-deysel) | Unclear; contradicted in spirit by the AMF870 data, where observations stayed alive for long active periods under kongo09 without renewal. May be model-specific |
| One observer per client IP, newest wins (F8) | Three HA-start timelines on the AMF870 | Yes on that unit; an AC2220 `@86` reportedly served two clients |
| CoAP stack wedges under session churn until power cycle (F16) | Anecdotal: 2020 py-air-control users, 2026 CX5120 PR author | Not systematically |
| "Device keeps broadcasting but ignores commands"; "opening the app revives it" | Anecdotal 2022 reports | Not analysed at packet level |

**[I]** The 2022 "connectivity problem" that the kongo09 README still describes was never analysed at protocol level by the maintainer. The 2026 captures show that most of it decomposes into (a) a deliberate firmware behaviour (push on change, introduced with Wi-Fi firmware 64.3 in July 2021 on the old generation and present on `@86` Combo units) that request/response-minded clients mishandle, (b) client-side defects (no timeouts, silent task death, churn), and (c) two genuine but rare firmware data-corruption bugs. There are no packet captures in the trackers showing a healthy, correctly handled session on an `@86` device being dropped by the device for no reason.

## 6. Firmware versions that disabled or changed local CoAP access

### 6.1 Changed behaviour (documented)

| When | Models | From -> to | What changed | Source |
|---|---|---|---|---|
| 2021-07-05 (automatic OTA) | AC2889/10, AC2939/10, AC3829, AC1214/10 | `AWS_Philips_AIR@62.1` -> `@64.3` (device 1.0.7) | Status requests no longer answered on demand ("sync timeout"); status sent only on change; control still works. Timeouts of 10 to 60 s helped some users, not others; an observing client (aioairctrl) works | py-air-control #93 |
| 2021-12 .. 2022-03 | AC2889, AC2729 | `@67.5`, `@68.3`, `@69.1` | kongo09: "both still mostly fail"; commands sometimes hang | py-air-control #93 |
| 2025-12 | AC2889/10 | `@62.1` -> `@91.1` | A user who had kept 62.1 upgraded; local access via aioairctrl and HACS still works; WPA2+WPA3 mixed mode started working (on 62.1 the device needed WPA2-only) | py-air-control #93, last comment |
| by 2026 | `@86` observed on AMF870/15, CX3550, CX7550, AC0850, AC0950/AC0951, AC2210/AC2220, AC4221, AC3420, CX3120 | `AWS_Philips_AIR_Combo@1.2`/`@2.5`/`@3.0` -> `@86` | Push-on-change (F1) demonstrated on AMF870, CX3550, CX7550, AC2210/AC2220 (and AC0850 per an external repo); not tested on the others. The stale cache in #394 shows one AMF870 went from device 0.8.9 / `@1.2` (2024-09) to 0.9.1 / `@86` | kongo09 #394, #365, #300, #371, #379; tinkerologie #132, #172, #214 |
| 2026-10/11 | CX5120/11 | `AWS_Philips_AIR@86.1`, device 0.4.9 | Push-on-change; setup times out without a nudge | tinkerologie #203 |

### 6.2 Claims that local access was disabled (and what they turned out to be)

| Claim | Model / firmware | Outcome |
|---|---|---|
| "Philips may have disabled local access in recent firmware" | AC4220/10, fw 0.2.3 | Device was on a guest Wi-Fi; works on the main network (kongo09 #295, closed `invalid`) |
| "not working anymore after possible FW upgrade" | AC0850/11, `@1.2`(?) -> `@86`, device 0.1.3 | CLI still returned status on `@86`; the failure was integration v0.34.3 on HA 2024.11 (kongo09 #282) |
| "AC2210 firmware version 0.2.1 not working" | actually AC2220/10, 0.2.1, `@86` | aioairctrl returned status; HA setup succeeded next day after several tries (kongo09 #345) |
| "doesn't speak encrypted CoAP" (maintainer's guess) | AC4221/11, 0.2.3, `@86` | Sync answered (`synced: 0E361EE9`), observe GET silent: consistent with F1, never followed up (kongo09 #293, #328, closed wontfix/stale) |
| "uses unencrypted CoAP" (maintainer's guess) | AC0951/13, D01S12 0.3.3, `@86`, MAC `68:79:C4` (Shanghai MXCHIP) | Wrong: `aioairctrl status --json` returned full encrypted status; `/sys/dev/info` answers in plaintext (`modelid`, `swversion 0.0.0`); the device needed its own model class (kongo09 #300) |
| README: "Some of these models seem to have a newer firmware that does not allow local connections anymore" | unspecified | Added 2024-11-03 without a model/firmware reference (**[V-git]** `2a8bc9b`). I found no issue that backs it with a version number |
| "same model number can have different firmware, with some versions working and others not" | AC3259 | Maintainer statement, no data (kongo09 #303) |

Devices that really have no local CoAP are a different platform (F20: AC0650/AC0651, AC0720/10 with ESP32 and Wi-Fi firmware 1.8.0).

Conclusion from the trackers: for the Combo/MXCHIP family the documented firmware change is behavioural (push on change), not a lock-out. I could not find a single confirmed case of a `@86` unit whose UDP 5683 or sync handshake stopped working.

### 6.3 Unverified lead: a second ("TLS"/GCM) encryption mode

kongo09 PR #384 https://github.com/kongo09/philips-airpurifier-coap/pull/384 (foXaCe, opened and closed by the author on 2026-08-26, no discussion; a duplicate #382 the same day; earlier fork-modernisation PR #362). I read the code from the PR ref (**[V-code]** `pr/384:custom_components/philips_airpurifier_coap/aioairctrl/coap/encryption.py`, `.../client.py`, `.../helpers.py`). Its comments claim, "Reverse-engineered from the Philips Air+ app (com.gaoda.util.TSLKeyPairGenerator / defpackage.v80)":

- Multicast discovery: CoAP GET to group `224.0.1.187:5683`, path `/sys/dev/info` (legacy) or `/sys/dev/info/encryption` (encrypted models); replies are unicast JSON with `device_id` and an `option` field, or an encrypted `didt` field (AES-CBC, key/IV = halves of uppercase hex MD5 of `"JiangPan" + <client's local IP>`, plaintext `deviceId&deviceToken`).
- If bit 6 of `option` is set the device is "TLS-capable": the client POSTs `{"type":"config_encrypt","random2":<4 digits>,"pk":<RSA-1024 PEM>}` to `/sys/dev/info/tls`, the device answers `random1` and an RSA-encrypted `prekey`; secret = first 16 hex chars of SHA-256 over the little-endian 32-bit sum `random1 + random2 + prekey`; payloads are then AES-GCM (nonce = first 12 chars of the derived IV, AAD = key, 16-byte tag appended) instead of AES-CBC, with key/IV from `MD5(bytes.fromhex(secret) + client_key)`.
- Anti-replay: the app accepts message ids only within +1..+10 of the last one, counter wraps at 2,000,000,000.
- Sensor sentinels: 255 (tvoc) and 65535 (other readings) mean "not available".

None of this is validated in the PR (no device, firmware or capture named; tests are synthetic; the author closed it the same day). It is nevertheless the only concrete description in the trackers of a handshake that classic clients would not speak, and it matches the symptom "app works locally with internet blocked, classic client gets nothing" reported for the AC4221/11 in #293 only in the weakest sense (that symptom is already explained by F1). Cheap test on the AC3220: read `coap://<ip>/sys/dev/info` (plaintext, answered by the AC0951 in #300 and the CX5120 in tinkerologie #203) and look for an `option` field; if bit 6 is clear the classic `JiangPan` CBC scheme applies.

## 7. What is still open on 2026-11-22

kongo09/philips-airpurifier-coap (open issues relevant to reliability or to the AC3220 family):

| # | Title (short) | Opened | Maintainer response |
|---|---|---|---|
| 396 | Deaf for ~3 min (sometimes 12): lost reconnect syncs, dead observe task | 2026-10-12 | none |
| 394 | Cached status shown as live after every restart/reload | 2026-10-09 | none |
| 397 | `AttributeError` on unload -> `failed_unload` (**AC3210/12**) | 2026-10-14 | none (PR #393 open since 2026-09-19, unreviewed) |
| 363 | Control commands have no timeout | 2026-06-18 | label only |
| 416 | **AC4221/11** lamp cannot be turned on/changed locally | 2026-11-14 | none |
| 413 | Pre-filter shows 0 %, cannot be reset | 2026-11-05 | none |
| 395 | `runtime` attribute floods the recorder | 2026-10-10 | none |
| 415 / 378 | Deprecated constants: stops loading in HA 2027.8 | 2026-11-10 / 08-05 | none (PR #401 open) |
| 371 | AC3420 preset `None` (MODE_C) | 2026-07-26 | beta suggested, no follow-up |
| 205 | Polling/trigger for push-only CX3550 | 2024-11-24 | "help wanted" for two years |

Closed without a fix (so still real): #376 (NUL-padded key), #379, #380 (gas level AC4221), #386 (icons), #293/#328 (AC4221/11 `@86` cannot be added), PRs #364, #365, #387, #388, #389.

kongo09/aioairctrl: PR #14 (skip unreadable notifications) and PR #13 (observe timeout) open, unreviewed.

tinkerologie/ha-philips-airpurifier (all 6 open issues): #172 (**AC2210**: CoAP stops responding, mostly at night; renewal regression), #214 (status timeouts AC3033/AC1715, with the **AC2220/10** report), #210 (nudge waits on a dead observation), #217 (manifest pins philips-airctrl 1.5.0, so the corrupted-push fix is not installed), #215 (AC0720 has no local CoAP), #209 (service call on a shut-down client).

Not addressed by anyone, in either project: a real liveness probe (CoAP ping); short per-attempt timeouts with resends for sync and control; validation of the sync key; push-on-change handling for AC22xx/AC32xx/AC42xx; detection of push-on-change from `WifiVersion` instead of per-model tables; keeping the neighbour (ARP) entry warm.

## 8. Timeline

| Date | Event |
|---|---|
| 2020-08..2021-04 | py-air-control #58: devices stop answering after repeated sessions until power-cycled; observations never cancelled |
| 2021-01 | py-air-control #73: "non-hexadecimal number found in fromhex()" on an AC2729 (first corrupted-payload report) |
| 2021-07-05 | Automatic OTA 62.1 -> 64.3: status only on change (py-air-control #93) |
| 2021 | betaboon's observing integration works where request/response fails; betaboon #28 (no reconnect after power loss) |
| 2022-04-02 | kongo09 README "word of caution" |
| 2022-04/05 | mhetzi's 180 s reconnect timer (v0.9.3-beta.1 -> v0.10.0); #17, #18, #38, #39, #40 closed as unfixable "connectivity" |
| 2022-12 | betaboon repo archived; aiocoap 0.4.5 FD exhaustion (aiocoap #296) |
| 2024-11 | kongo09 v0.20.0 (AC4220/21), v0.21.0 (AC3210/20/21), v0.22.0 coordinator refactor, v0.25.0 cached status at startup |
| 2025-09 | v0.34.2/v0.34.3 after 8 months without release |
| 2026-01-31 | v0.35.0: AC22xx, global `simple6` (breaks Tradfri) |
| 2026-03-01 | aioairctrl 0.3.0/0.3.1; v0.36.0 (broken manifest), v0.36.1, v0.36.2 |
| 2026-06 | #363/#364 (command timeouts), #365 (CX3550 control trigger) |
| 2026-07-26 | v0.37; last commit on kongo09 master |
| 2026-09 | PRs #387/#388/#389/#393 (reliability), aioairctrl PR #14 |
| 2026-09-28 | tinkerologie v2026.9.1: status nudge for HU15xx/HU4209, 30 min watchdog, per-device missed-package count |
| 2026-10-09..28 | mbreitkreuz's capture-based reports (#394, #396, tinkerologie #132) |
| 2026-10-19 | tinkerologie v2026.10.1/.2: AMF870 push-only nudge, persisted backlight |
| 2026-10-28 | philips-airctrl 1.4.0 + tinkerologie v2026.10.3: 60 s observation renewal (regression on push-on-change devices, #172) |
| 2026-11-07 | kongo09 PRs #387/#388/#389 closed (author deleted fork) |
| 2026-11-10/13 | tinkerologie v2026.11.0 (CX5120 nudge, bounded nudge writes), v2026.11.1 (renewal at 1800 s for nudge models only, idempotent shutdown via philips-airctrl 1.5.0) |
| 2026-11-15 | philips-airctrl 1.5.1 (skip unreadable pushes); not yet pinned by the integration (#217) |
| 2026-11-22 | AC2220/10 `@86` report on tinkerologie #214: 56 unavailable periods in 30 h |

## 9. Design implications for a new integration (from the failure reports)

Protocol/session layer:

1. **Model the device as push-on-change from the start.** Never block setup, reconnect or availability on an answer to a status read. Register the observation, then obtain the first status actively. Treat "sync answered" as the proof of reachability and "status" as something that arrives when the device has news.
2. **Have an explicit, cheap way to force a status push**, used at setup, after reconnect and as an on-demand refresh: write a setting to a different value and back. Candidates proven on other models: display backlight (`D0312D` on AMF870; `D03105` on CX5120/CX7550) and beep (`D03130`, proposed in kongo09 #178/#205/#365). For the AC3220 this must be validated on the device (which key forces a push, whether writing the same value is a no-op, whether it beeps or flickers). Restore the user's real value, never publish the transient value (tinkerologie #197), persist the resting value across restarts (#155), and bound every nudge write with a short timeout (#197).
3. **Separate liveness from data freshness.** Silence is normal (up to ~2 h in standby). Use a real probe: CoAP empty CON ping (answered with RST in < 0.1 s on an AMF870) or a `/sys/dev/sync` round trip every 30 to 60 s; mark unavailable only after several missed probes. As a side effect regular traffic keeps the HA host's ARP entry warm (F3).
4. **Keep one long-lived client and one observation per device.** Refresh the observation on the existing client instead of rebuilding the client; reconnect rarely, with backoff (5 s -> 60 s is what tinkerologie uses) and never once per minute (F16: churn can wedge the device until power-cycled).
5. **Do not require an answer to an observation renewal.** If renewing at all (AC4220/12 evidence in philips-airctrl #34), register the new observation, keep the old one until the new one has delivered something, and do not treat an unanswered renewal GET as a failure (F7).
6. **Short per-attempt timeouts plus resends for everything sent to the device** (sync, control): about 2 to 5 s per attempt, 2 to 3 attempts a few seconds apart; a healthy round trip is ~0.05 to 0.25 s (p90 0.21 s). Log a warning when all attempts fail. Never leave a shut-down client assigned (F3, F6).
7. **Validate device data defensively**: skip a notification that fails hex decoding or the digest check (including the first response of an observation) and keep the observation; reject a sync key that is not exactly 8 hex characters and re-sync; make client shutdown idempotent (F4, F5, F6).
8. **Always send integers for D0xxxx values** and verify a write by the following status push, not by `{"status":"success"}` (F15). Handle `{"status":"failed"}` with one re-sync and one retry.
9. **Do not open a second client to a configured device** (config-flow probe, repair flow, diagnostics): match discovery against the configured host/unique id before touching the network, and route any re-read through the coordinator's client (F8). Document that CLI tests from the HA host disturb the integration.
10. **Do not touch process-global aiocoap state** (environment variables, monkeypatches); pass `transports=[...]` to your own context. aiocoap is shared with other integrations (F12). Decide consciously between `simple6` (works without IPv6, used by aioairctrl 0.3.1) and the default.

Home Assistant layer:

11. **No stale state after restart**: either keep entities unavailable until the first real status, or restore state marked as restored and force a push immediately (F9). Do not block HA startup on the device (F10): finish setup after sync and let the first status arrive asynchronously, or raise `ConfigEntryNotReady` quickly.
12. **Unload must never raise** (F6): suppress and log errors from client shutdown so the entry never ends in `failed_unload`.
13. **Follow the device across IP changes**: store the device id (`DeviceId` from status) as unique id and the MAC as a connection; DHCP discovery with `registered_devices` should update the host without probing; provide a reconfigure flow; never store an all-zero MAC (F14).
14. **Keep high-churn values out of the recorder**: no `runtime`/RSSI/raw counters as attributes of the fan entity; make them disabled-by-default diagnostic sensors; consider rounding/deduplicating PM2.5 updates (F19).
15. **Diagnostics that explain outages**: per-device counters for pushes, skipped corrupt pushes, sync retries, time since last push, last error stage, ARP/timeout hints (`syncing` -> `synced` delay); a repair issue only for sustained outages (tinkerologie #214 plan).
16. **Model table**: for the AC3220 expose power, modes (D0310C: 0/17/18/19, speeds 1..5 if the 3200 accepts them: to be verified), actual speed level (D0310D) as a sensor only, PM2.5, allergen index, temperature, humidity, display brightness incl. "auto" (a select fits better than a light), lamp function (D03135), ambient scene (D03137), child lock, beep, Auto Plus, timer, filter hours and percentages (never round a non-zero remainder down to 0 %, #413). The preferred-index key is `D0312A` in the dump, not `D03-42`.
17. **Capability detection over model tables**: decide "push-on-change" from behaviour at setup (no answer to the first observe GET within a few seconds -> nudge) or from `WifiVersion`, not only from the model string; firmware differs within one model number (#303) and changes by OTA.
18. **Keep pace with HA core**: CI against HA beta/dev; the kongo09 code base has two hard breakages scheduled (HA 2027.8, 2027.11).

## 10. Open questions (not answerable from the trackers)

1. What firmware does a 2026 AC3220/10 actually run (expected: device 0.2.x, `AWS_Philips_AIR_Combo@86`), and does it show push-on-change? No AC3220 report newer than November 2024 (0.1.9 / `@3.0`) exists.
2. Which write reliably forces a status push on the AC3220 without side effects (beep, visible flicker)? Is writing the current value really a no-op there too?
3. Does the AC3220 drop an un-renewed observation after ~150 s like the AC4220/12 in philips-airctrl #34, or keep it alive like the AMF870? Does it accept a second observer from the same IP, or from a different IP (Air+ app on the LAN plus HA)?
4. Is broadcast-ARP deafness a property of the MXCHIP module's power save in general (so every site is affected) or specific to the one UniFi/DTIM-1 network measured in #396?
5. Is the lamp of the 3200/4200 series writable locally with integer values (kongo09 #416), and which combination of D03105/D03135/D03137 does the app send?
6. Does any Combo `@86` unit advertise the "TLS"/GCM mode of PR #384 (`option` bit 6 in `/sys/dev/info`)? Is that mode mandatory on any firmware?
7. Why does opening the Air+ app "revive" a device (2022 and 2026 reports)? Does the app talk CoAP locally on newer firmware (suggested by #293: app works with the device's internet blocked)?
8. What are D0312B, D0312C, D0313B, D03106, D03182, D03136, D03240, D03R81 on the AC3220?
9. How often do corrupted notifications and NUL-padded sync keys occur on the AC3220 specifically (only measured on an AMF870)?
10. What was the "strange behavior of display backlight" seen by the AC3220 tester in 2024 (#181)? Never described.

## 11. Source index

kongo09/philips-airpurifier-coap (base `https://github.com/kongo09/philips-airpurifier-coap`):
- Issues read in detail: /issues/17, 18, 25, 38, 39, 40, 62, 83, 112, 129, 160, 162, 178, 179, 181, 199, 203, 205, 247, 254, 256, 264, 282, 289, 293, 295, 298, 300, 303, 304, 305, 306, 313, 318, 321, 322, 323, 326, 328, 331, 345, 349, 357, 363, 367, 369, 370, 371, 376, 379, 380, 386, 394, 395, 396, 397, 413, 415, 416.
- PRs read: /pull/337, 364, 365, 384, 387, 388, 389, 393, 398, 408; PR code/commit messages read from local refs `pr/384`, `pr/388`, `pr/389`, `pr/400`, `pr/408`, `pr/411`.
- Lists: /issues?q=is%3Aissue+is%3Aopen ; /issues?q=is%3Aissue+is%3Aclosed&page=1..11 ; /pulls?q=is%3Apr+is%3Aopen ; /pulls?q=is%3Apr+is%3Aclosed&page=1..2 (pages 3 to 5 of closed PRs not listed) ; model searches `?q=AC3220`, `?q=AC3210+OR+AC3221+OR+AC4220+OR+AC2220+OR+AC2221+OR+PureProtect`.

kongo09/aioairctrl: https://github.com/kongo09/aioairctrl/issues/6 , /pull/9 , /pull/13 , /pull/14 , issue and PR lists.

tinkerologie/ha-philips-airpurifier (base `https://github.com/tinkerologie/ha-philips-airpurifier`): /issues/1, 6, 8, 29, 51, 58, 82, 92, 132, 151, 155, 172, 197, 198, 203, 209, 210, 214, 215, 217 ; /pull/125, 208 ; /releases (page 1 of 3: v2026.9.0 to v2026.11.1) ; issue list pages 1 and 2 ; closed PR list page 1 of 7.

tinkerologie/philips-airctrl: https://github.com/tinkerologie/philips-airctrl/issues/1 , /issues/34 , /issues/36 , /issues/44 , /pull/35 , issue list, PR list page 1 of 2.

Others: https://github.com/betaboon/philips-airpurifier-coap/issues/28 , /issues/74 , issue list page 1 of 2 ; https://github.com/betaboon/aioairctrl/issues?q=is%3Aissue (one issue, "Question to aiocoap", not read) ; https://github.com/rgerganov/py-air-control/issues/58 , /issues/73 , /issues/93 , list `?q=is%3Aissue+coap` page 1 of 2 ; https://github.com/chrysn/aiocoap/issues/222 , /issues/296 (the only two "philips" hits besides the user survey) ; https://github.com/iobroker-community-adapters/ioBroker.philips-air/issues/377 .

Not covered (out of time or out of scope): kongo09 closed-PR pages 3 to 5; the hidden part of #160 and #83; tinkerologie releases pages 2 to 3 and PR pages 2 to 7; py-air-control issues not matching "coap"; aiocoap issues about Observe in general; atdr/homebridge-philipsair-platform and chayuto/seeed-XIAO-ESP32-C6 (cited second-hand in tinkerologie #132); Ka3seBr0t/HA_Philips_Air_Plus (cloud integration advertised in kongo09 #205: AWS IoT device shadow over MQTT, 30 s `shadow/get` poll since its v0.3.2; "physical button changes are not recognized" before that).

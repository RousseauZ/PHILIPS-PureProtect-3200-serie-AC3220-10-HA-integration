# 11 - Verification of the round-1 firmware / reliability claims (F1-F14)

Date: 2026-11-22. Role: skeptical verifier. Target device: Philips PureProtect 3200 AC3220/10.

## 0. Method and limits

- GitHub issue/PR pages can only be read through WebFetch (a small model answers a prompt about the page). I asked for
  exact quotations every time; the tool caps a quote at roughly 125 characters and marks paraphrase. Everything in
  double quotes below is a quotation as relayed by that tool, so it is "verbatim as relayed", one step short of a raw
  page. Where a number mattered I asked for it in a second, differently worded pass (done for #181).
- api.github.com, curl to github.com and the GitHub MCP server (scoped to the user's own repository) are not usable.
  I did not try third-party mirrors.
- PR code and commit dates are first-hand: read with git from the clones under `scratchpad/src` (PR heads are present
  as `pr/<n>` in `kongo09_philips-airpurifier-coap`). `git ls-remote` against GitHub worked and was used for live heads.
- New clone made this round (read only, nothing executed): `src/foXaCe_philips-airpurifier-coap` (the fork that
  PR #382/#384 came from), main `df1e53e`, 2026-11-20, manifest version 0.42.1.
- Tags: **[git]** verified in a clone, **[WF]** quotation relayed by WebFetch, **[I]** my inference.

## 1. Verdict table

| ID | Verdict | One-line reason |
|---|---|---|
| F1 | confirmed (sourcing corrected) | #132 quotes support every element; but only #132 is an AMF870 with tcpdump, #365 is a CX3550, #203 a CX5120 |
| F2 | partly confirmed | AC2210 and AC2220/10 show the timeout pattern; AC4221/11 evidence is one unanswered observe GET; push-on-change was never tested directly on any sibling |
| F3 | confirmed (version wording corrected) | all four numbers found verbatim; 118/14 is 2026.10.3 vs 2026.10.2 only; both issues open; no fix commit after v2026.11.1 |
| F4 | confirmed | #132/#203/#365 quotes plus code; no nudge for AC3210/AC3220/AC3221, AC22xx, AC42xx |
| F5 | confirmed | "56 of 92 lookups (61 %)" verbatim; one site, one AMF870/15 |
| F6 | confirmed (rate range widened) | rates seen are 1 in 1,800 to 1 in 18,000; NUL-padded keys 2 of 1,317 and 1 in ~2,000 |
| F7 | partly confirmed | only #326 (CX3120) states success-but-no-reaction; string "0" (power off) was accepted in two reports |
| F8 | confirmed (scope caveat) | verbatim in #396 and PR #389; code confirms probe-before-check; an AC2220 @86 report says two clients both worked |
| F9 | partly confirmed | two sessions on one AC4220/12; the issue itself says the cause is "Not confirmed" |
| F10 | confirmed | full dump obtained (56 keys), `D0312A: 1` present, no `D03-42` |
| F11 | partly confirmed | code exists, but the TLS branch is unreachable (no caller passes `option`), tests use a fake device, no device named |
| F12 | confirmed (absence claim) | nothing found; closest items are a README warning, one hearsay sentence, one maintainer guess |
| F13 | confirmed | master head 2026-07-26 by live ls-remote; none of the reliability PR heads is an ancestor of master |
| F14 | confirmed (with a caveat that may undo it) | issue exists, open, no comments; but the test used the aioairctrl CLI and the commands shown have no `--int` |

## 2. Per claim

### F1. Push-on-change on @86 firmware

Fetched: https://github.com/tinkerologie/ha-philips-airpurifier/issues/132 (two passes),
https://github.com/kongo09/philips-airpurifier-coap/pull/365 , https://github.com/tinkerologie/ha-philips-airpurifier/issues/203

#132 **[WF]**: title "AMF870 with `AWS_Philips_AIR_Combo@86` firmware is push-only (status only arrives on state changes)",
author mbreitkreuz, opened Oct 9, 2026, closed as completed in #153 on Oct 19, 2026.

- Device: "AMF870/15, WifiVersion `AWS_Philips_AIR_Combo@86`"; "The Air+ app isn't signed in."
- "`GET /sys/dev/status` without Observe (NON or CON), or with `Observe: 1`, is never answered, not even while the device is running."
- With Observe 0: "is answered only with the next push: 0.1 to 4 s while the device is active"; "in standby it stays unanswered until the next push."
- "and there is no heartbeat."; "99.8 % of ~34,000 notifications change at least one exposed value,"
- "pushes stop for anywhere from 12 min to ~2 h, about 18 times a day,"
- "while `/sys/dev/sync` keeps answering (rarely, sync also went unanswered for a few minutes)."
- "Control writes still work during a quiet period: 4 of 4 power-on POSTs that landed 16–48 min into one got" ... "within 109–211 ms"
- Evidence base: "raw CoAP from Home Assistant's host with `aiocoap`/`aioairctrl`, debug logs and tcpdump"; "All of this is from one unit and ~4 days of debug logs."
- Also in #132: "After a command, pushes sometimes stop for minutes:" (4 of ~40 commands) and "Either the observation was dropped or the firmware held the readings; I can't tell which."

PR #365 **[WF]**: author ccoreilly, opened Jun 19, 2026, closed Oct 9, 2026 by the github-actions bot (Stale label Oct 2).
Device is a **CX3550/01**, not an AMF870: "The CX3550/01 (firmware AWS_Philips_AIR_Combo@86, device FW 0.1.7) silently ignores the initial CoAP"
"GET /sys/dev/status observe=0 and never sends the first status push."; "GET /sys/dev/status observe=0 → no response, ever";
method: "Confirmed via direct aiocoap testing against the device:" (no packet capture mentioned).

#203 **[WF]**: author arminfauland, opened Nov 9, 2026, closed as completed in #204 on Nov 10, 2026. Device is a **CX5120/11**:
"Philips CX5120/11 heater, firmware `D01S12` = 0.4.9, Wi-Fi module `AWS_Philips_AIR@86.1`, local CoAP on port 5683."
"The device answers the plaintext `sys/dev/info` and the encrypted sync handshake," "but it never answers a `sys/dev/status` read";
"It only pushes the status resource to observers when the state actually changes." CLI tests, no captures.

Verdict: **confirmed**. Corrections: (1) only #132 is an AMF870/15 with tcpdump (one unit, about 4 days); #365 is a CX3550/01
tested with aiocoap, #203 a CX5120/11 tested with the CLI. (2) "does not answer until the next change" holds for an
Observe-0 GET; a GET without Observe or with Observe 1 is never answered at all. (3) Sync is not perfectly reliable
either ("rarely, sync also went unanswered for a few minutes").

### F2. Siblings AC2210, AC2220/10, AC4221/11 on 0.2.x / @86

Fetched: tinkerologie #172, #214; kongo09 #293, #328, #345.

- **AC2210** (#172 **[WF]**, open, author Luke2105-Loft59, opened Oct 27, 2026): "Philips AC2210, device firmware 0.2.3, Wi-Fi firmware 86 (Air+ app: up to date)".
  "885 attempts, 683 timed out (77 %)" (status requests); "Out of 414 renewals, 196 (47 %) got no push within 10 s";
  "if it had been silent for ≥ 50 s, 88 % failed"; ping: "zero packet loss during all 7 outages (453 pings, avg ~100 ms, same as in stable phases)".
- **AC2220/10** (#214 **[WF]**, comment by Karacostapannis, Nov 22, 2026): "Same symptom here on an AC2220/10 (firmware AWS_Philips_AIR_Combo@86), integration 2026.11.1, HA 2026.11.2 / HAOS 18.4."
  "On reconnect it answers the sync in 0.15 s, but the status GET then times out (IP and identifiers removed):". Device firmware number not given there.
  A separate AC2220/10 dump (#345, Mar 3, 2026) has `"D01S12": "0.2.1"` and `"WifiVersion": "AWS_Philips_AIR_Combo@86"`.
- **AC4221/11** (#293 **[WF]**, closed Feb 24, 2026, labels connectivity + wontfix; comment by ThomasCr): "My device is a Philips 4200 / AC4221/11",
  "Device-Firmware: 0.2.3", "WLAN-Firmware: AWS_Philips_AIR_Combo@86"; log shows `synced: 0E361EE9`, then `observing status`, then
  "And after that I get nothing..."; "Yesterday I blocked internet traffic from the Philips Device on my Firewall - and could also control the device with the app."
  #328 **[WF]** (same user, opened Feb 25, 2026, closed as not planned by github-actions May 4, 2026): the HA log excerpt ends after the sync POST is sent
  (no `synced` line shown); kongo09: "I assume the device doesn't speak encrypted CoAP."; user: "I made a tcpdump of my connection between my phone and the philips device and could see, that it also connects to port 5683."

Verdict: **partly confirmed**. The AC2210 statistics are strong and the AC2220/10 report matches. For the AC4221/11 the only
evidence is one CLI run where sync was answered and the observe GET was not; nobody tested whether a change produces a
push, and nobody in any sibling thread ran the decisive test (register, then write a changed value, expect a push).
"Push only on change" for the AC22xx/AC42xx family is therefore an inference from timeout statistics, although a well
supported one. No AC3210/AC3220/AC3221 on @86 appears in any of these threads.

### F3. Measured flapping

#172 **[WF]** (comment Oct 30, 2026): "I ran v2026.10.3 for 24 hours, then rolled back to v2026.10.2 and ran that for another 24 hours to compare."
Table rows: "Outages (unavailable periods)" 118 (v2026.10.3) and 14 (v2026.10.2); "Total time unavailable" "10 h 22 min" and "3 h 21 min".
A second 24 h on v2026.10.3 with debug logs (Oct 31): 107 outages, "12 h 26 min"; "103 of the 107 outages are a direct consequence of a failed renewal."
State: Open, labels bug + needs-triage.

#214 **[WF]**: title "[Bug]: Recurring CoAP status timeouts on Philips AC3033/14 and AC1715", author Yesbox-star, opened Nov 17, 2026, Open,
"No branches or pull requests." The AC2220/10 numbers are in a third-party comment of Nov 22, 2026:
"Before migrating from kongo09 v0.37 (8.5 days): 5 unavailable periods." / "After (this integration, 30 hours): 56 unavailable periods, 5 to 40 s each."

**[git]** renewal arrived with philips-airctrl 1.4.0: `tinkerologie_ha-philips-airpurifier_full` tag v2026.10.2 (2026-10-19) pins
`philips-airctrl==1.3.0`, v2026.10.3 (2026-10-28) pins `==1.4.0`; `tinkerologie_philips-airctrl` v1.3.0 has 0 lines matching "renew" in
`src/philips_airctrl/coap/client.py`, v1.4.0 has 19; `RENEWAL_TIMEOUT = 10.0` at `client.py:29`. Commits after v2026.11.1 up to main
`550c88a` (2026-11-19, equal to the live remote head) are dependency and CI changes only.

Verdict: **confirmed**. Corrections: 118 vs 14 was measured on 2026.10.3 vs 2026.10.2 (24 h each, one AC2210), not on "2026.10.3 to 2026.11.1".
The baseline without renewal was itself bad (14 outages and 3 h 21 min unavailable in 24 h), so removing the renewal does not make
that integration reliable on this family. #214 is filed for an AC3033/14 and an AC1715; the AC2220/10 data is a comment made today.

### F4. A changed write forces a push; nudge model list

Quotes **[WF]**: #132 "writing `D0312D` 100 → 0 got a full status push after 0.3 s, and 0 → 100 got one after 0.1 s." /
"Writing the value it already had (100 → 100) was acked, but no push came within 45 s." #203 "Manual nudge test on the same client (observe first, then write `D03105` = 0, then `D03105` = 100):"
"full status push after 0.3 s, display back at 100." PR #365 (CX3550): "registers the CoAP observe and sends D03130=0 (beep off) as a trigger", "toggles D03130=1 then immediately restores it to 0",
"device immediately pushes full status via the observe subscription".

Code **[git]** `tinkerologie_ha-philips-airpurifier/custom_components/philips_airpurifier/` at `550c88a`:

- `status_nudge=` occurs only at `device_models.py:733` and `:753` (`_CONFIG_HU1509`, used for HU1509 and HU1510 at `:1729-1730`; `_CONFIG_HU4209`),
  `:1422` (AMF870, `NEW2_DISPLAY_BACKLIGHT` = `D0312D`, 0 then 100), `:1538` (CX5120, `NEW2_DISPLAY_BACKLIGHT2` = `D03105`, 0 then 100),
  `:1721` (CX7550, `NEW2_DISPLAY_BACKLIGHT4` = `D03105#2`, 0 then 115). Key constants: `const.py:434-437`.
- `_CONFIG_AC3210` (`device_models.py:619-634`, mapped to AC3210/AC3220/AC3221 at `:1025-1027`) has no `status_nudge`; neither have
  `_CONFIG_AC2221` (`:601`) and `_CONFIG_AC4220` (`:666`). The CX3550 entry (`:1546`) has none either.
- Restore logic, `coordinator.py:251-293` (`_build_status_nudge`): the sequence is `[(key, transient), (key, resting)]`; `resting` is the value last
  seen on the observe stream (`_nudge_resting_values`, persisted), else `coordinator.data[key]`, else the model default; if `transient == resting`
  the other model value is used as the transient. Writes go out on the same client as the observation with a per-write deadline
  (`client.py:155-230`, `async_fetch_status_with_nudge`); the returned snapshot is patched with the resting value when the last write was acknowledged (`client.py:220-222`).
- Non-nudge models: `renew_interval = NUDGE_WATCHDOG_TIMEOUT if self._status_nudge_enabled else None` (`coordinator.py:424`), watchdog
  `self._timeout * self.missed_package_count` (`:462`); `NUDGE_WATCHDOG_TIMEOUT = 1800` (`:41`).
- The nudge is in the HA integration, not in the library: `grep -ri nudge tinkerologie_philips-airctrl/src` returns nothing.

Verdict: **confirmed**. Additions: the beep method (D03130) is from kongo09 PR #365 on a CX3550, tinkerologie only uses display backlight keys.
Nobody has tested a nudge on any AC32xx/AC22xx/AC42xx device; that a `D03105` toggle forces a push on an AC3220 is an untested expectation.
Known side effect (#132, comment Oct 14): "so after every HA restart the nudge ends on the model's resting value (turning the backlight back on if it was off)."

### F5. Broadcast ARP

kongo09 #396 **[WF]** (open, author mbreitkreuz, opened Oct 12, 2026, no labels, one comment by the author, no maintainer reply):
"Philips AMF870/15, `AWS_Philips_AIR_Combo@86`, software 0.9.1, 2.4 GHz Wi-Fi (UniFi, DTIM 1)";
"32 of 403 reconnect syncs (7.9 %) got no reply"; "31 of the 32 never left the HA host."; "119 of 2,991 lost (4.0 %)";
"The purifier answers **unicast** ARP 340/341 (99.7 %)"; "**broadcast** ARP in only 56 of 92 lookups (61 %)";
"It's in Wi-Fi power save and apparently sleeps through DTIM beacons".
kongo09 #363 **[WF]** (open, label enhancement, author villeparamio, Jun 18, 2026, AC0950/10 `AWS_Philips_AIR_Combo@86`, v0.36.2): "hangs for a very long time (~1h46m in the captured case)";
comment Oct 14: "sent three broadcast ARP requests 1 s apart, got no answer, and dropped the queued POST."; "this purifier misses ~39 % of those while answering unicast ARP 99.7 % of the time".
Note from the Oct 12 comment: "None of the 12 commands in that capture was lost, though".

Verdict: **confirmed**. Scope: one AMF870/15 on one UniFi network. The lost-sync link is measured (31 of 32); for control writes one case was captured end to end.

### F6. NUL bytes and NUL-padded sync keys

kongo09/aioairctrl PR #14 **[WF]** (open, author nathanhand, Sep 16, 2026, "No reviews"): "Observed an AC0850 sending malformed packets with two \x00 (NUL) characters middle of the packet."
mbreitkreuz Oct 12: "had two NUL bytes at positions 2166–2167 of its 2280-char hex payload"; "its SHA-256 digest matched"; "1 of 18,108 notifications over ~51 h.";
"2 of 1,317 `synced:` lines in my logs (8 days) were NUL-padded" "e.g. `synced: 31\0\0\0\0\0\0`"; "every command until the next sync would then fail in `int(key, 16)`".
Oct 21: "16 corrupted notifications out of 85,122 sent to Home Assistant, 2026-10-11 → 10-21: about 1 in 5,300, or ~1.5 a day."; "13 have two NULs in place of one byte's hex pair, 3 a single NUL.";
"the sync reply was `33\0\0\0\0\0\0`"; "It's the first in ~2,000 sync replies in the capture"; "Here that lasted 9 min, until the watchdog happened to re-sync;".
tinkerologie/philips-airctrl #44 **[WF]** (closed Nov 15, 2026 in commit 222bc5b): "The SHA-256 digest matches the string including the NULs, and the UDP checksum is valid.";
"Rate in that window: 9 corrupted of 16,245 pushes (~1 in 1,800)."; "A packet capture over 10 days in October found 16 in 85,122."
kongo09 #396: "18 corrupted notifications in 87,981 from 2026-10-15 → 10-26 (~1.7 a day)."
kongo09 #376 **[WF]** (AMF 870/15, opened Jul 28, 2026, closed as not planned by github-actions Oct 4, 2026, no human comment):
"Failed to perform the action fan/set_preset_mode. invalid literal for int() with base 16: '27AA\x00\x00\x00\x00'"; "After downgrade to version 0.36.2 I can set preset and fanspeed as before."

Verdict: **confirmed**. Correction: observed rates span 1 in 1,800 (9 of 16,245) to 1 in 5,300 (16 of 85,122), with 1 in 18,108 in the first 51 h, so
"1 in 2,000 to 5,000" is a fair middle but not the full range. The UDP-checksum statement is in philips-airctrl #44, not in PR #14. Devices: AMF870/15 and one AC0850;
#376 links the NUL-padded key to a user-visible error only by inference (the reporter blamed v0.37). **[git]** neither library validates the key
(`tinkerologie_philips-airctrl/src/philips_airctrl/coap/encryption.py:35` `int(self._client_key, 16)`).

### F7. String-typed control values

kongo09 #326 **[WF]** (CX3120/01, author Klaus-Cr, opened and closed Feb 22, 2026, label invalid): "Standard string values return 'success' but the device doesn't react.";
"returns {"status":"success"} but the device does not react (no relay click, no power on)."; "It only works when sending values as Integers.";
"Curiously, D03102=0 (Power Off) works even without --int, but D03102=1 (Power On) requires it."
kongo09 #247 **[WF]** (AC4221/11, opened Feb 11, 2025, closed by the stale bot May 2, 2025): commands "aioairctrl -H myipadress set D03102 = 1" / "= 0"; "only the power-off command works."; no reply text and no mention of value types.
philips-airctrl #1 **[WF]** (AC4221/11, opened Dec 21, 2025, closed Feb 19, 2026): `philips-airctrl set -H ... D03102=1` "doesn't switch on the device"; working command "$ philips-airctrl set -H 192.168.177.146 -I D03102=1"; "Its your documentation."
**[git]** `-I/--int` = "Encode value as integer" (`tinkerologie_philips-airctrl/src/philips_airctrl/cli.py:119-123`; `kongo09_aioairctrl/aioairctrl/cli.py:80-82`, `:116-126`); without it the CLI sends a JSON string.

Verdict: **partly confirmed**. The success-but-ignored reply is stated only in #326, on a CX3120/01. The two AC4221/11 threads are consistent with it but do not show the reply.
"Ignore string-typed values" is too broad: the string "0" for power-off worked in #326 and in #247; it is non-zero values sent as strings that had no effect. The design rule (always write integers) stands.

### F8. One observer per client IP

kongo09 #396 **[WF]**: "the device keeps one observer per source IP and the newest observe GET wins"; "running a CLI client (`aioairctrl`, `coap-client`) on the HA host takes over the integration's notifications".
kongo09 PR #389 **[WF]** (author beyildirim, Sep 4, 2026; "beyildirim closed this by deleting the head repository Nov 7, 2026"): "DHCP discovery probes a purifier before checking whether its host is already configured.";
"A timed-out probe also skips client shutdown and leaves a UDP socket behind." Comment by mbreitkreuz, Oct 9, 2026: "Real-world confirmation from an AMF870/15 (`AWS_Philips_AIR_Combo@86`, v0.37, HA 2026.10.0)";
rows "| 10-05 17:15 | 17:15:17.7 | 17:15:58 | none; watchdog at 17:18:17.7 (+180 s) |", "| 10-07 14:33 | 14:33:26.2 | timed out after 30 s | none; watchdog at 14:36:26.2 (+180 s) |",
"| 10-08 21:32 | 21:32:49.5 | 21:33:28 | none; watchdog at 21:35:49.5 (+180 s) |"; "So the probe took the notification both times it got one,".
**[git]** `kongo09_philips-airpurifier-coap/custom_components/philips_airpurifier_coap/config_flow.py:62-89`: `async_step_dhcp` calls `CoAPClient.create(self._host)` and `client.get_status()` first; nothing
before line 76 checks whether the host is already configured. `get_status()` is an Observe-0 GET in aioairctrl.
Counter-evidence, tinkerologie #132 **[WF]**: "Someone running two clients on an AC2220 `@86` reports they both worked, so it may differ by model."

Verdict: **confirmed** for the AMF870/15 (three HA starts, two takeovers plus one probe timeout). For the AC3220 family it is not established, and the only sibling data point says the opposite.

### F9. AC4220/12 stops notifying after about 150 s

philips-airctrl #34 **[WF]** (author ruaan-deysel, the maintainer; opened Oct 27, 2026; closed as completed in #35 on Oct 28, 2026): "Philips AC4220/12 (firmware 0.2.3, reproduced live)";
"`CoAPClient.observe_status()` stops yielding updates after about 2.5 minutes."; "delivered its last push at about 08:29:40 (≈2m42s after it started)."; "delivered its last push at about 08:35:29 (≈2m31s).";
"75 push(es) in this observation session", "47 push(es) in this observation session"; "The device reports `Max-Age: 60` on its responses"; "a fresh observation delivers pushes again within a second.";
"Not confirmed. The evidence points to the observation registration lapsing on the device because the client never renews it:";
"Unknowns to verify: whether the device needs a fresh token or accepts re-registration on the same token," "and whether the lifetime differs at night (the AC2210 report) or between models."
The page does not say what the device was doing during the two sessions, or that its values were still changing when the stream went quiet. Wi-Fi firmware not stated. No hardware validation of the fix is shown on the issue page.

Verdict: **partly confirmed**. Two sessions on one unit went quiet at 2m42s and 2m31s and a new registration got pushes again; that is real. "Unless the observation is re-registered" is the
maintainer's unconfirmed hypothesis, the alternative (the device simply had nothing new to report) was not excluded, and the fix built on it produced the #172 regression. On the AMF870/15
the tinkerologie integration runs with an 1800 s renewal interval (`coordinator.py:41`, `:424`), which implies observations that outlive 150 s there.

### F10. AC3220/10 status dump (kongo09 #181)

https://github.com/kongo09/philips-airpurifier-coap/issues/181 **[WF]**: title "Support for AC3220/AC3221", author tomasz-soltysik, opened Nov 2, 2024, closed as completed via PR #183 on Nov 4, 2024, no labels.
Body: "Model from same series as AC4220/AC4221 (see #160), just smaller and without gas sensor." / "Sample status json, with Auto mode, light off, 1 PM2.5, 1 IAI, 47% humidity, 21.2°C".
Tester comment Nov 4, 2024: "Tested. Works, with a little strange behavior of display backlight," "but I think this is the same thing that was discussed in #160."

Dump as relayed (pretty-printed JSON with double quotes on the page). A second pass with a different prompt returned "56 top-level keys", the same 26 `D03*` keys and values in the same order, no key containing
"-" or "#", and no `D03137`, `D03104`, `D03112`, `D0313B`, `D03122`, `D0110B`. It also matches round 1's independent rendering key for key. `DeviceId` and `D01S0D` belong to the reporter's unit.

```json
{
    "D01102": 0,
    "D01S03": "Salon",
    "D01S04": "Unicorn",
    "D01S05": "AC3220/10",
    "D01107": 0,
    "D01108": 3,
    "D01109": 3,
    "D0110A": 0,
    "D0110C": 19,
    "D01S0D": "688001001384",
    "D0110F": 3,
    "D01S12": "0.1.9",
    "D01213": 0,
    "ProductId": "768643a2b11811ee88c206d016384e4a",
    "DeviceId": "3924e2d9962b11efa71c0d1d273d48dd",
    "otacheck": false,
    "Runtime": 317641004,
    "rssi": -49,
    "wifilog": false,
    "blelog": false,
    "free_memory": 154416,
    "WifiVersion": "AWS_Philips_AIR_Combo@3.0",
    "StatusType": "status",
    "ConnectType": "Online",
    "D03102": 1,
    "D03103": 0,
    "D03105": 0,
    "D03106": 1,
    "D0310A": 2,
    "D0310C": 0,
    "D0310D": 1,
    "D03110": 0,
    "D03211": 0,
    "D03115": 0,
    "D0311F": 0,
    "D03120": 1,
    "D03221": 1,
    "D03224": 212,
    "D03125": 47,
    "D0312A": 1,
    "D0312B": 1,
    "D0312C": 4,
    "D03130": 100,
    "D03134": 0,
    "D03135": 0,
    "D03136": 0,
    "D03240": 0,
    "D03180": 0,
    "D03182": 1,
    "D03R81": "AAEBAQIBAgID\n",
    "aqit_ext": 0,
    "D05102": 3,
    "D05207": 720,
    "D05408": 9600,
    "D0520D": 621,
    "D0540E": 9501
}
```

Reading against the reporter's description: `D0310C` 0 = auto, `D03105` 0 = light off, `D03221` 1 = PM2.5, `D03120` 1 = IAI, `D03125` 47 = humidity, `D03224` 212 = 21.2 degC.

Verdict: **confirmed**. Small correction: the name field `D01S03` is "Salon"; "Unicorn" is `D01S04`. **[git]** both integrations map the AC3220 preferred-index select to `D03-42`
(`kongo09_.../philips.py:1176` with `const.py:451`; `tinkerologie_.../device_models.py:630` with `const.py:428`), a key this dump does not contain; the dump has `D0312A`.

For comparison, a sibling on newer firmware, AC2220/10 from kongo09 #345 **[WF]** (posted by Gren-95 on Mar 3, 2026; command "aioairctrl --host 192.168.0.36 status --json"; identifiers redacted by me):

```json
{"D01102": 0, "D01S03": "Bedroom", "D01S04": "Cobra", "D01S05": "AC2220/10", "D01107": 0, "D01108": 3, "D01109": 3, "D0110A": 0, "D0110B": 0, "D0110C": 18, "D01S0D": "<redacted>", "D0110F": 3, "D01S12": "0.2.1", "D01213": 0, "ProductId": "<redacted>", "DeviceId": "<redacted>", "otacheck": false, "Runtime": 1657866, "rssi": -34, "wifilog": false, "blelog": -1, "free_memory": 91712, "WifiVersion": "AWS_Philips_AIR_Combo@86", "StatusType": "status", "ConnectType": "Online", "D03102": 1, "D03103": 0, "D03104": 101, "D03105": 101, "D03106": 0, "D0310A": 2, "D0310C": 19, "D0310D": 3, "D03110": 0, "D03211": 0, "D03112": 0, "D0311F": 0, "D03120": 1, "D03221": 2, "D0312A": 1, "D0312B": 1, "D0312C": 4, "D03130": 100, "D03134": 0, "D03135": 1, "D03136": 0, "D03137": 1, "D03240": 0, "D03180": 0, "D03182": 1, "D0313B": 20, "D03R81": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\nAAAAAAAAAAAAAA==\n", "D05207": 720, "D05408": 19200, "D0520D": 719, "D0540E": 19196}
```

Differences to the 2024 AC3220 dump (single pass, not cross-checked): adds `D0110B`, `D03104` (101), `D03112`, `D03137`, `D0313B`; lacks `D03115`, `D03224`, `D03125`, `aqit_ext`, `D05102`; `blelog` is -1 instead of false.
Whether these come from the model (Cobra vs Unicorn) or from the firmware generation (0.2.1/@86 vs 0.1.9/@3.0) cannot be told from two dumps.

### F11. PR #384, RSA + AES-GCM handshake on /sys/dev/info/tls

Page https://github.com/kongo09/philips-airpurifier-coap/pull/384 **[WF]**: author foXaCe; "foXaCe closed this Aug 26, 2026."; "No reviews"; "1 participant"; description lines include
"TLS/GCM key exchange (RSA-1024, /sys/dev/info/tls) for option bit 6" and "38 tests pass, ruff clean". The page names no device, no firmware and no capture, and does not mention the Air+ app.

Code **[git]** (`kongo09_philips-airpurifier-coap`, ref `pr/384` = `9c51731`, 2026-08-26 16:15:41 +0200, 17 files, +1154/-12, not an ancestor of master):

- `custom_components/philips_airpurifier_coap/aioairctrl/coap/encryption.py:13-19`: "TLS-capable devices (discovery option bit 6 set) instead run a key exchange on /sys/dev/info/tls ... Reverse-engineered from the Philips Air+ app (com.gaoda.util.TSLKeyPairGenerator / defpackage.v80)."
- `.../coap/client.py:34-42` `is_tls_option()` returns `((value >> 6) & 1) == 1`; `:50` `def __init__(self, host, port=5683, option=None)`; `:79-80` `if self._tls: await self._tls_handshake()`;
  `:88-111` POST `{"type": "config_encrypt", "random2": <1000..9999>, "pk": <RSA-1024 PEM>}` to `/sys/dev/info/tls`, reply fields `random1` and `prekey`.
- `encryption.py:160-170` secret = first 16 hex chars of SHA-256 over the little-endian 32-bit sum `random1 + random2 + prekey_int`; `:87-93` AES-GCM with nonce = first 12 chars of the derived IV and the key as AAD; `:81` key material = `MD5(bytes.fromhex(secret) + key)`.
- **The TLS branch cannot run.** Every production call site omits `option`: `__init__.py:148`, `config_flow.py:87`, `:226`, `:335`, `coordinator.py:85`, `helpers.py:252` all call `CoAPClient.create(<host>)`.
  The discovery helper returns an `option` value (`helpers.py:189`) that nothing consumes; `scan_for_devices` has no caller inside `custom_components` in this PR.
- No test in `tests/test_helpers.py` touches TLS/GCM (grep for tls, gcm, prekey, random1 finds nothing). `aioairctrl/VENDORED.md` in the same commit says "No functional changes."
- The `option` comes from the multicast discovery reply (CoAP GET to `224.0.1.187:5683`, paths `/sys/dev/info` and `/sys/dev/info/encryption`, `helpers.py:32-38`, `:166-190`), not from a unicast `/sys/dev/info` read as the claim words it.

Fork today **[git]** (`foXaCe_philips-airpurifier-coap`, main `df1e53e`, 2026-11-20, version 0.42.1): the handshake code is still there (`.../coap/client.py:29`, `:36`, `:82`, `:90`), and the call sites still pass no option
(`__init__.py:177`, `helpers.py:246`, `config_flow.py:119`, `coordinator.py:311`). TLS tests exist now but against a stand-in: CHANGELOG "with a test suite driving the CoAP client against a fake device";
`tests/test_coap_client.py:89-115` uses `random1 = 4242`, `prekey = b"\x11\x22\x33\x44"`. CHANGELOG 0.41.0 claims "TLS/GCM encryption support for the devices that require it" without naming one.
A web search for "sys/dev/info/tls", "TSLKeyPairGenerator" and "config_encrypt" found no independent source.

Verdict: **partly confirmed**. The PR and the code exist as described and the author closed it unmerged the same day. Whether a real device speaks this handshake is unverified: no device, firmware or capture is named anywhere,
the tests play both sides, and in three months the fork never connected the code path to anything. Relevance to the AC3220: none shown. The classic `JiangPan` AES-CBC scheme works on the siblings' current firmware
(AC4221/11 0.2.3/@86 read and written with aioairctrl in #416, Nov 2026; AC2220/10 0.2.1/@86 in #345; AC2210 0.2.3 in #172). Treat it as a documented fallback to try only if sync or status decryption fails.

### F12. No GitHub evidence of a firmware update removing local CoAP on AC32xx/AC22xx/AC42xx

Searched **[WF]**: kongo09 issues for `AC3220 OR AC3210 OR AC3221 OR "3200"` (3 results: #397, #181, #160); kongo09 issues for firmware update/stopped/no longer/local (20 results, none about these models);
tinkerologie issues for the eight sibling model numbers (12 results: #214, #173, #172, #132, #122, #79, #73, #58, #26, #18, #8, #6). Read #293, #328, #295, #345.

Closest items:

- **[git]** README note added in commit `2a8bc9b` (2024-11-03, "add new models AC3210, AC3220, AC3221"): "Note: Some of these models seem to have a newer firmware that does not allow local connections anymore." It heads the whole supported-models list and names no model.
- #295 **[WF]** (AC4220/10, "The FW version on my AC4220 is 0.2.3."): "I read in a post on the HA community topic on this integration that Philips may have disable local access on recent FW's." Resolved the next day:
  "I initially set up my purifier on my guest network", "So then I tried it on my home netwerk wifi and it did give me data."
- #328 **[WF]** (AC4221/11 0.2.3/@86): kongo09 "I assume the device doesn't speak encrypted CoAP." Never followed up; but the same user's log in #293 shows the sync answered (`synced: 0E361EE9`), and #416 shows an AC4221/11 on the same firmware answering status and control.
- #345 **[WF]** (AC2220/10 0.2.1/@86): "After trying the next day it suddenly worked?"

Verdict: **confirmed** as an absence claim, limited to what GitHub search returned. No one reports "worked, then a firmware update, then local CoAP gone" for these models.

### F13. kongo09 repository activity

**[git]** `git ls-remote origin` today: `refs/heads/master` = `964ef214...`; `git log -1` = 2026-07-26 21:12:40 +0200. The only other branch head (`371-ac3420-...`) is 2026-07-26 21:29:04 +0200; tags v0.37 and v0.37.1-beta.1 are 2026-07-26.
`git merge-base --is-ancestor pr/<n> master` is false for 364, 365, 387, 388, 389, 393, 398, 408, 384, 382.
**[WF]** PR list (https://github.com/kongo09/philips-airpurifier-coap/pulls?q=is%3Apr+sort%3Aupdated-desc): "14 Open, 114 Closed"; #387, #388, #389 "closed Nov 7, 2026" (beyildirim); #365 "closed Oct 9, 2026"; #393 and #408 open.
kongo09/aioairctrl: clone head `cc28046` (2026-03-01) equals the live remote HEAD; PR #14 open with "No reviews".

Verdict: **confirmed**.

### F14. kongo09 #416

**[WF]**: title "AC4221/11 (PureProtect Pro 4200): light cannot be turned on or changed via local CoAP, fan/mode keys work", author theFabriZ, "opened on Nov 14, 2026", Open, no labels, no comments on the fetched page.
"Philips AC4221/11 (Air Purifier 4200 series)", "firmware 0.2.3 (D01S12)", "WifiVersion AWS_Philips_AIR_Combo@86"; "Local CoAP via aioairctrl (`aioairctrl --host <ip> status` / `set`), no cloud".
"`set D03105=0` or `set D03135=0`: lamp turns off (works)"; "`set D03105=101`, `set D03135=1`, or both: lamp stays off"; "`set D03135=2 D03137=2`: lamp turns OFF, D03105 and D03135 read 0, D03137 stays 1";
"The app changes D03105 and D03135 together; StatusType switches from "status" to "control" after some app commands."; "Fan, mode and child lock writes work normally over CoAP.";
"Is there a different key or sequence the app uses (cloud only?) to switch the lamp on and change the scene?"; `D0310C` "reads -16 when powered off".

Verdict: **confirmed** that the report exists and is open and unanswered. Caveat: none of the commands shown carries `-I`/`--int` and the issue never says how values were typed. The aioairctrl CLI sends strings unless
`--int` is given (`kongo09_aioairctrl/aioairctrl/cli.py:116-126`), and per F7 a string "0" is honoured while non-zero strings are not. That is exactly the pattern in #416 (off works, on does not), so the finding
may be a typing artefact. Against that, the reporter says fan and mode writes work, which per #326/#247 would need integers. It cannot be settled from the page; test on the device with integer writes.

## 3. New findings that matter for the design

1. **The fork's `PROTOCOL.md` describes how the Air+ app is said to detect and recover a lost device** (`foXaCe_philips-airpurifier-coap/PROTOCOL.md:103-113`, unverified, source is the fork author's reading of the app):
   "a watchdog thread sends a CoAP `ping` every 3 seconds with a 10-second timeout. When the device comes back it **re-runs the `sync`** before resuming". This matches the liveness-probe design, and #396 measured that the
   AMF870 "answers an empty CoAP ping (CON, code 0.00) with an RST in < 0.1 s" "(2 of 2, tested with the integration disabled)".
2. Same file, key meanings claimed from the app (`PROTOCOL.md:22-44`, `:58-76`, `:115-131`): `D0312A` = preferred index (new2 name of `ddp`/`D03-42`); `D0312C` = air-quality threshold (`aqit`);
   `D03104` = light brightness 0 to 100 and `D03105` = display backlight "written together with the brightness"; `D03240` error bit patterns `32781`/`32782` = no filter detected, `49408` = water tank;
   `D03115` "equals 1 when the sleep mode is the allergen variant"; `D01102` capability class, `D0110C` capability bitfield; `D03106`, `D0312E`, `D0312F` "backlight variants, depending on the model". All unverified leads.
3. **Do not copy the app's anti-replay window.** PR #384 added it (`encryption.py:146-157`), and the fork's CHANGELOG then lists fixes for "a failed first status read or ... missed updates" and "Stream never recovering after a device reboot"
   caused by it (`CHANGELOG.md:40-48`).
4. **`D03104` appears next to `D03105` on 0.2.1/@86 firmware** (AC2220/10 dump, #345: both 101). Together with item 2 and #416's "The app changes D03105 and D03135 together", a plausible reason for ignored light-on writes is that the
   firmware wants several keys in one write. **[I]**, to be tested on the AC3220.
5. **The Air+ app talks to the purifier locally on UDP 5683** on an AC4221/11 with 0.2.3/@86 (#328: "I made a tcpdump of my connection between my phone and the philips device and could see, that it also connects to port 5683.";
   #293: the app still controlled the unit with its internet access blocked). Local control is a live path on current firmware.
6. **Single observer is not established for the AC3220 family**: "Someone running two clients on an AC2220 `@86` reports they both worked, so it may differ by model." (#132). Design for one observer, but measure it.
7. **Removing the renewal is not enough**: on tinkerologie 2026.10.2 (no renewal) the AC2210 still had 14 outages and 3 h 21 min unavailable in 24 h (#172). The silence watchdog is the other half of the problem.
8. **After a write, pushes can stall**: "in 4 of ~40 commands, the existing observation got 0–1 pushes" and "the next change only arrived 2–4 min later after a reconnect." (#132). A write should be followed by a bounded wait for the echo and a re-registration if none comes.
9. **Sync is not a perfect liveness signal**: "(rarely, sync also went unanswered for a few minutes)" (#132), and about 1 in 700 to 2,000 sync replies carried a NUL-padded key (aioairctrl PR #14). Validate the key as exactly 8 hex characters.
10. "Unicorn" is a platform name, not an AC3220 name: the AC4221 reports it too (round 1), and round 1's forum note has an AC0951/13 in setup mode reporting `"type":"Unicorn"` with `"option":55` (bit 6 clear). AC2210/AC2220 report "Cobra".
11. tinkerologie main still ships `philips-airctrl==1.5.0` in `custom_components/philips_airpurifier/manifest.json:37` although the head commit is titled "bump philips-airctrl from 1.5.0 to 1.5.1 (#216)"; the NUL-skip fix (1.5.1) is therefore not what HACS users run.

## 4. Could not verify

- Whether #416 has maintainer replies hidden from the fetched page (none were shown).
- Round 1's statement that philips-airctrl PR #35 was validated with 106 pushes in 270 s (not on the issue page; PR page not fetched).
- Round 1's "7 presses produced 6 failed-command events" for #363; the fetched comments gave different counts ("Three times a command got no reply", "four presses in a row").
- Anything about an AC3220/AC3210/AC3221 on @86 firmware: no such report exists in the pages read.

# 13b - Design review of `docs/onderzoek.md` (protocol and reliability lens)

Reviewer lens: try to break chapter 6 (layers, session state machine, timings, commands, discovery/setup) and
the measurement plan in chapter 7. Date: 2026-11-22.

## 0. Method

- Read the report completely, then notes 01 (protocol), 08 (other ecosystems), 11 (verification), the relevant
  parts of 04, 07 and 10.
- Read the tool the measurement plan relies on: `src/kongo09_aioairctrl` at tag v0.3.1
  (`aioairctrl/cli.py`, `aioairctrl/coap/client.py`), aiocoap 0.4.17 `protocol.py:695-717` (reorder filter),
  `src/tinkerologie_philips-airctrl/src/philips_airctrl/cli.py` (has `device-info-raw` since v1.2.0, commit cc013a0).
- RFC 7641 text fetched to `scratchpad/dl13b/rfc7641.txt` (sections 3.3.1, 3.4, 3.5, 3.6, 4.1, 4.5); RFC 7252
  for NON/RST and multicast Leisure (5 s default).
- HA core checkout `src10/ha_core/homeassistant/helpers/service.py:411` (`if not entity.available: continue`).
- Nothing was executed against a device. Everything below is a paper walk-through.

Labels: **[R]** = report text, **[N01..N11]** = research note, **[code]** = read in cloned source, **[RFC]**.

## 1. Scenario walk-through (what the design as written does)

| Scenario | What the report's rules produce | Verdict |
|---|---|---|
| HA restart, purifier in standby, standby sensors off | Sync ok, registration sent, no frame. State "BEREIKBAAR, NOG GEEN STATUS". Report says entities are "beschikbaar met onbekende waarden", but 6.6 creates entities only from keys the device reports, and no frame has arrived, so there is nothing to create them from. With sensors off nothing changes, so the wait is not "even" but until somebody touches the device. | Breaks (issue 4) |
| Device power blip, module back before the first probe (60 s) | Probe answered, state stays ACTUEEL. Observer is gone on the device. `Runtime` rule cannot fire because it needs a frame. Only the periodic refresh repairs it, and 7.3 allows switching that off. | Breaks when refresh is "niet" (issue 2) |
| Device power cut > 90 s | OFFLINE, backoff, sync ok, registration. Returns through "NOG GEEN STATUS" = values unknown until the next change. AC0951: module-MCU link silent ~124 s after cold start [N07 1.5]; first minutes unspecified. | Works, with unknown-values cost; start-up window not designed |
| Router reboot 2 min at night, purifier in standby | OFFLINE after ~90 s, back after sync, then values unknown until the next change (possibly hours) although nothing changed on the device. | Regression against "keep last values" (issue 3) |
| IP change via DHCP | Relies on HA DHCP flow matching the MAC. Manual entries have no MAC ("MAC-adres alleen uit DHCP-gegevens"). No rediscovery from OFFLINE. Another purifier taking the old IP answers sync and is adopted silently. | Breaks for manual entries and two-purifier homes (issue 11) |
| Wi-Fi roaming of the purifier (seconds) | One or two probe misses at most; TWIJFEL; diagram has no edge back. | Underspecified (issue 3) |
| Burst of packet loss while the user switches the purifier off | The "off" frame (NON, 2 fragments, never retransmitted) is lost. Device goes quiet. Probes succeed. HA shows "on" for hours as current. | Breaks silently (issue 9) |
| Broadcast-ARP deafness | 60 s refresh and 60 s probe keep the neighbour entry in unicast revalidation; per-request deadlines and retries cover the rest. Holds only while refresh/probe are never disabled. | OK with caveat |
| IP fragments dropped between HA and device | Info and sync (small) work, setup succeeds, no frame ever arrives, "silence is never a fault": permanent unknown, no error, no repair hint. | Breaks silently (issue 10) |
| Malformed sync reply (NUL padded) | No validation rule in 6.3/6.4. Harmless for commands only because every command does its own sync; must still be validated there. | Underspecified (issue 16) |
| NUL-corrupted frame / valid digest but invalid JSON | "Overslaan en tellen". Stream survives. If it was the last change before a silence, state stays stale. | OK for the stream, see issue 9 |
| Sync unanswered for minutes, frames flowing | Depends on undefined "enig contact". If frames count, no probe is sent: fine. | OK if defined |
| Sync unanswered for minutes, device quiet (AMF870: "rarely ... a few minutes") | 3 misses in ~30 s: OFFLINE at ~90 s. Entities unavailable, HA drops actions on unavailable entities silently, return path sets values to unknown. | Breaks (issue 3) |
| Firmware that never answers sync | Registration is only sent after a successful sync. No frames, permanently OFFLINE, although observing needs no sync. | Breaks (issue 14) |
| Late answer to the registration | Same token: arrives as an ordinary frame. | OK |
| Same-token re-registration, fresh MID | RFC 7641 3.3.1 and 4.1 allow it (replace, not add). Measured without duplicates on an AC2220 only. | OK on paper, unmeasured on AC3220 and not measurable with aioairctrl (issue 5) |
| CON notification | ACK is in the listed CoAP subset. RST for unknown tokens and deregistration are not. | Partly (issue 13) |
| Duplicate / out-of-order Observe values | "Nooit op berichtnummer filteren" (MID) is right; no ordering rule at all is given. | Low risk gap (issue 15) |
| Newest observer per source IP wins; CLI or second integration on the HA host | Stream is stolen until the next refresh. With refresh "niet": forever. | Issue 2 |
| Air+ app or second HA instance (other IP) | Not evicted by the per-IP rule. Counter churn handled by sync-before-command and retry. Effect of our 60 s sync probes on the app's own commands is unknown and not measured. | Open (issue 14, omissions) |
| The ~150 s lapse | Default same-token refresh every 60 s gives two chances. Whether same-token works on the Unicorn platform is assumed [N08 5.4]. No detector for "refresh ineffective". | Issue 2, 5 |
| Device answers success but ignores the value | Step 4 would catch it, but its rule misfires (below). | Issue 1 |
| Confirming frame never comes (value already current) | AMF870: a write of the current value is acknowledged and produces no push [N04 F1]. Step 4 has no deadline: waits forever, lock held. | Breaks (issue 1) |
| Stale frame right after the command | Every frame is a full snapshot, so the "first frame containing the key" is simply the next frame, possibly generated before the MCU applied the write. False mismatch, resend, error. | Breaks (issue 1) |
| Two commands in quick succession / a scene with 5 entities | Serialised by the lock; each can take 10 s plus the unbounded wait. No coalescing although the protocol takes several keys per write. | Issue 12 |
| Command while OFFLINE | HA never delivers it: unavailable entities are skipped in `service.py:411`, without an error. | Raises the price of a false OFFLINE (issue 3) |
| Command while TWIJFEL / NOG GEEN STATUS | Not specified. Should proceed and count as a probe. | Omission |
| Info probe to a non-Philips host | One small NON GET; harmless. Needs strict reply validation and silent abort. | OK if specified (issue 17) |
| Multicast/broadcast from a container or multi-homed host | Not specified: per-interface send, unconnected socket, replies from unicast source, 3-5 repeats (39 % broadcast loss), listen window. | Issue 17 |
| DHCP event for a configured device | MAC compare first, no session: good. Manual entries have no stored MAC. | Issue 11 |

## 2. Issues, ranked by damage

### 1. Command confirmation (6.4 step 4) is unbounded and misfires on this firmware - HIGH

Quote: "Wachten op het eerstvolgende statusbericht dat de sleutel bevat. Wijkt de waarde af, dan één keer opnieuw
sturen en daarna een foutmelding in Home Assistant tonen."

- No deadline. The report's own advice 3 is "Elk verzoek een time-out". With `PARALLEL_UPDATES = 1` plus the
  command lock (recommended in N10 line 381-385), one command that never sees an echo blocks every later command
  on that platform: the same "hangt onbeperkt" class the report criticises in kongo09.
- Every frame is a full snapshot [R 3.1], so "het eerstvolgende statusbericht dat de sleutel bevat" is the next
  frame of any kind. The Wi-Fi module polls the MCU about once per second [R 2.1, N07 1.5]; a frame generated
  before the write reached the MCU carries the old value. openHAB sleeps 1 s after a command "otherwise we won't
  get the new value" [N01 6.2]. Result: false "wijkt af", needless resend, then an error for a command that
  worked.
- No-op writes get no echo: AMF870 `@86`, "writing the value the device already has is acknowledged but produces
  no push" [N04 F1]. `fan.turn_on` on a running unit, a scene that re-applies values, or any command while HA's
  state is stale all wait forever.
- Echo can be missing for other reasons: "in 4 of ~40 commands, the existing observation got 0-1 pushes" and the
  next change came 2-4 min later after a reconnect [N11 section 3 item 8]; AC0850: 8 of 9 echoes within ~1 s,
  one took 83 s [N08 5.4]. N11 states the design rule ("bounded wait for the echo and a re-registration if none
  comes"); the report dropped it.
- Equality is the wrong test: AC4220/12 "Writing 1 reads back 100" for `D03130`, `D03137` "writing 0 reads back
  1", `D03105` writes acknowledged and discarded [N08 section 4]; `D0310C` reads -16 while off [R appendix A].
- A resend on mismatch also overrides a person who pressed a button on the device at the same moment.

Fix:
1. Release the exchange lock after the control answer; confirmation is a per-key pending expectation, not a
   held lock.
2. Settle window: ignore non-matching frames for 2 s after the control answer. Accept as soon as a frame shows
   an accepted value (per-key accepted-read-back set, not equality). Prefer frames with `StatusType == "control"`.
3. Deadline 5 s (tunable after measuring the echo latency). On expiry: if the last known value already equalled
   the target, treat as success (no-op); otherwise send a same-token re-registration, wait 3 s more, then resend
   once, then raise a translated `HomeAssistantError` ("accepted but not confirmed").
4. Total budget per action call: 10 s hard, including lock wait.
5. Use every acknowledged-but-unechoed state-changing command as the oracle for "observation dead" (see issue 2).

### 2. A lost observation is only repaired by the periodic refresh, which the report makes optional - HIGH

Quotes: "| Herstart van het apparaat | Looptijd lager dan voorheen: opnieuw abonneren | Veld `Runtime` |";
"| Abonnement vernieuwen | Instelbaar: zelfde kenmerk, nieuw kenmerk, of niet. ...";
"| Abonnement verloopt niet | Vernieuwen kan uit of zeer spaarzaam |".

- The reboot rule is circular: `Runtime` is only seen in a status frame, and after a reboot "Observation and
  counter are gone on the device; client sees nothing" [N01 8.3]. No frame, no `Runtime`, no re-registration.
- With the refresh off, four failure classes become permanent, because sync keeps answering and "stilte is nooit
  een fout": (a) module restart shorter than the OFFLINE threshold; (b) eviction by a newer registration from
  the same IP, "takes over notifications until the watchdog re-registers" [N01 7.3, N11 F8]; (c) the ~150 s
  lapse appearing after a firmware update; (d) any other device-side observer loss (Wi-Fi re-association).
- N08 5.3 had "After a successful sync from OFFLINE or SUSPECT: send a fresh registration immediately". The
  report kept it only for the OFFLINE path ("Verbinden").
- There is no detector for "refresh mode X does not work on this firmware"; the mode is "instelbaar" by hand.

Fix: make re-registration mandatory, never "uit". Minimum cadence Max-Age + 5..15 s (RFC 7641 3.3.1; chayuto
uses 75 s) counted from the last registration; plus event triggers: first successful probe after any miss,
OFFLINE -> reachable, control answer `failed`, acknowledged command without echo, `Runtime` regression. Add an
escalation ladder driven by the command-echo oracle: same token -> new token (keep accepting the old one, then
deregister it) -> resync + new registration. Record the rung that worked in diagnostics. 7.3 row 1 should read
"refresh stays on at >= 60 s; only the token strategy is decided by measurement".

### 3. OFFLINE after ~90 s contradicts the report's own evidence, and the state machine is incomplete - HIGH

Quote: "| Gemiste controle | Elke 10 seconden opnieuw; na 3 missers OFFLINE | Ontwerpkeuze tussen de bestaande
waarden in |" (and the diagram in 6.3).

- [R 3.2] itself records "Op de AMF870 bleef sync een enkele keer een paar minuten onbeantwoord"; N11 section 3
  item 9: "Sync is not a perfect liveness signal". Three misses 10 s apart turn exactly that benign event into
  OFFLINE. On the same device 7.9 % of reconnect syncs (4.0 % over 13 days) got no reply [N11 F5].
- The price of a false OFFLINE is high in this design: (1) HA silently skips actions on unavailable entities
  (`helpers/service.py:411`), so a scheduled `fan.turn_on` is lost without an error; (2) the only path back is
  OFFLINE -> "BEREIKBAAR, NOG GEEN STATUS" = "waarden onbekend", so a healthy quiet device loses all values until
  its next change, possibly hours.
- The diagram has no edge out of TWIJFEL except to OFFLINE; N08 5.2 had "probe ok" edges back. Read literally,
  a quiet device enters TWIJFEL every 60 s and can only leave towards OFFLINE.
- "enig contact" is not defined (N08 5.1 defined it: any valid datagram from the device). Not stated: whether a
  corrupt frame, a control/info answer or a late reply counts; whether a frame received in TWIJFEL or OFFLINE
  moves the session to ACTUEEL; the probe deadline (5 s is given only for connecting).
- openHAB needs 120 s without contact; ioBroker probes after 300 s; nothing is lost by declaring a dead device
  unavailable after 3-5 minutes instead of 90 s.

Fix: replace the diagram by a transition table. Rules: any valid datagram from the device address (including a
frame that fails payload validation) is contact; a valid frame in any state -> ACTUEEL; probe = sync, deadline
3 s; TWIJFEL is entered on the first miss, not on the 60 s timer; OFFLINE only when (a) >= 3 consecutive misses
and (b) >= 180 s since last contact and (c) a second probe type (plaintext info GET or empty CON ping, both
side-effect free) also failed; OFFLINE -> reachable keeps the cached values (state ACTUEEL, flagged unconfirmed
internally) unless there was never a frame; a frame with lower `Runtime` or a foreign `DeviceId` replaces or
rejects them.

### 4. HA restart in standby: 6.6 and 6.3 contradict each other, and "unknown" can last indefinitely - HIGH

Quotes: "Entiteiten worden alleen aangemaakt voor sleutels die het apparaat werkelijk meldt, omdat de sleutelset
per firmware verschilt." versus "Tot dan zijn de entiteiten beschikbaar met onbekende waarden." and
"kan het na een herstart van Home Assistant even duren".

- Before the first frame the key set is unknown, so by 6.6 no entity can be created. After a restart the
  registry entries exist but are not provided ("restored", unavailable); on first setup the device page is
  empty. That is not "beschikbaar met onbekende waarden".
- With the purifier in standby and standby sensors off nothing changes, so no frame comes until a person or an
  automation acts. AMF870 with sensors active: quiet 12 min to ~2 h, about 18 times a day [N04 F1]. This is the
  everyday case (purifier off, HA updated), not an edge case. Conditions on the fan state fail (unknown, not
  off) while actions still work.
- Policy is inconsistent: at runtime values are kept "hoe oud ook", but the same values are thrown away over a
  30-second HA restart.
- The remedy named in 7.3 (write the current value) cannot work at start-up because the current value is the
  unknown (issue 7).

Fix: persist per config entry (a) the observed key set with firmware versions and (b) the last full frame with
a receive time. At start create entities from the persisted key set; restore the last frame as state (same
trust level as the runtime rule), replaced by the first live frame. For first setup add an optional flow step
"press a button on the purifier" that waits up to 60 s for a frame (also proves the fragment path, issue 10),
with a static AC32xx key table as fallback. Expose a throttled "laatste statusbericht" timestamp entity.

### 5. The measurement session cannot decide the choices it is said to decide - HIGH

Quote: "Deze sessie duurt ongeveer een uur en beslist de open ontwerpkeuzes."

- The pillar of the design, advice 1 (sync as reachability probe), is "[aanname]" for the AC3220 [R 3.2] and has
  no step. `aioairctrl` has no sync-only command; every invocation syncs once and then registers or writes
  [code `client.py:47-63`].
- The refresh strategy (same token / new token / none) cannot be tested: aioairctrl 0.3.1 never re-registers and
  aiocoap always assigns a new token [N01 5.3, 5.4]. 7.3 says "Vernieuwen met hetzelfde kenmerk testen" without a
  tool. N08 5.4 lists "Same-token refresh every 60 s prevents the ~150 s lapse" as assumed.
- Not asked although the capture would show it: NON or CON notifications, Max-Age, Observe sequence behaviour,
  MID behaviour, fragment count [N01 section 11 Q5/Q6].
- No power-cycle test (time to first sync answer, time to first frame, `Runtime` reset, does the observer
  survive) although 6.3 has a reboot rule; N07 section 10 Q9 proposed it.
- No test of one-observer-per-source-IP [N07 section 10 Q12], counter semantics with two clients [N01 section 11
  Q4], write-to-echo latency (needed for issue 1), or keys the report turns into switches without a measured
  write: `D03103`, `D03130`, `D03180`, plus `D03112`, `D0312C` and the filter resets.
- Time: step 4 (15 min) plus step 5 (2 x 30 min) already exceed the stated hour before step 6.

Fix: split step 0. 0a: 30-minute smoke test with existing CLIs (firmware, keys, first-answer behaviour, a few
writes). 0b: write the stdlib-only probe tool first (about 200 lines: raw UDP socket, fixed token, NON GET/POST,
ACK for CON, log every datagram with a monotonic timestamp) and run a scripted matrix: sync / info GET / empty CON
ping every 30 s for 2 h in standby; single registration with no refresh and a physical stimulus at 3, 5, 10 and
20 min; same-token refresh; new-token refresh; second client from the same host and from another host; power
cycle; each write with echo latency, including a write of the current value and of a discarded key.

### 6. "Met de huidige tools niet te testen" is wrong for the info request - MEDIUM

Quote: "| 8 | Antwoordt de info-aanvraag altijd? | Staat in de opname zodra de nieuwe protocollaag er is; met de
huidige tools niet te testen |"

- `philips-airctrl device-info-raw -H <ip>` reads plaintext `/sys/dev/info` without sync since v1.2.0
  [code `philips_airctrl/cli.py:190-205, 292-304`; commit cc013a0, 2026-07-02].
- libcoap `coap-client -m get coap://<ip>/sys/dev/info` was used on an AC0951 `@86` in kongo09 #300 [N07 3.1].
- The design makes this request a hard dependency: "Herkenning altijd via het onversleutelde GET /sys/dev/info",
  "Instellen slaagt zodra de info-aanvraag en een sync lukken". The evidence is one AC0950/10 [R 3.3]. If the
  AC3220 does not answer, there is no unique id and no setup path.

Fix: move it to step 1 of the session: unicast, subnet broadcast and 224.0.1.187, 20 probes each, running and in
standby; compare `device_id` with status `DeviceId`. Specify a fallback: unique id from the first status frame
when info is not answered.

### 7. The "write the current value" outcome has no measurement, is contradicted by the best evidence, and is circular at start-up - MEDIUM

Quote: "| Schrijfopdracht met de huidige waarde geeft een volledig statusbericht | Dat is een bijwerkingsvrije
manier om bij het opstarten de status op te halen |"

- No row in 7.2 writes an already-current value; row 6 only notes whether "de status de nieuwe waarde terugmeldt".
- AMF870 `@86`, tcpdump-backed: "writing the value the device already has is acknowledged but produces no push"
  [N04 F1]. The report does not mention this.
- At start-up the current value is what is missing. The trick needs a persisted last value (issue 4) or a key
  whose value is irrelevant.

Fix: add explicit steps: (a) write the current value of `D03103`, (b) write a discarded key (`D03105` on the
AC4220 pattern), (c) change and restore a setting with no physical effect (`D0312C`); log whether a frame
follows and with which `StatusType`. Change the 7.3 row to "only usable together with a persisted last frame".

### 8. Measurement steps 2, 3, 4, 5 and 7 mislead with aioairctrl 0.3.1 as proposed - MEDIUM

Quotes: "| 4 | ... Dezelfde opdracht 15 minuten laten lopen terwijl het apparaat draait. Stoppen de berichten
terwijl de fijnstofwaarde op het display nog verandert? |"; "| 7 | Stoort de Air+ app? | Open de app tijdens
meting 4 en bedien het apparaat. Loopt de stroom door? |"; row 2: "Blijft het hangen, verander dan iets op het
apparaat; dat is zelf al een antwoord op vraag 3."

- `status` is an Observe-0 registration that is never cancelled [code `client.py:88-108`; N01 7.3]. Each run
  leaves an observer on a dead port; on newest-wins firmware a `status` call while `status-observe` runs takes
  the stream and exits, which reads as "abonnement verlopen" in step 4.
- A hang in step 2 is ambiguous: `Client.create()` awaits the sync with no timeout [code `client.py:83`], so a
  lost sync, a blocked fragment path and a quiet device look identical without `-D`.
- Step 3 "terwijl het apparaat draait" cannot separate a direct answer from the next push (0.1-4 s on the
  AMF870). Only the standby run, repeated, with latency read from the capture, discriminates.
- Step 4 has no controlled stimulus. In clean air a running unit can be quiet for minutes; the display may show
  the allergen index (`D0312A` = 0), not PM2.5. N11 F9 notes exactly this gap in the AC4220 report. Step 5 has the
  same problem: silence after 150 s is either "nothing changed" or "observer lapsed".
- Step 7 inside step 4 destroys step 4: the app is a local CoAP client [R 3.4] and opening the older app forced
  pushes [N01 7.7]. The phone has another IP, so it does not test the per-IP eviction either. The app must also
  be force-closed during steps 2-6; "zodat er maar één client is" only covers the integration.
- A NUL-corrupted frame raises `ValueError` in `decrypt_status`, ends the generator and the CLI
  [code `client.py:113-139`, N01 7.5]. At 1 in 1,800-5,300 frames that is a few per cent per 15-minute run and
  must not be read as a lapse.
- A `set` from the same host as stimulus is not neutral either (unknown whether inbound packets refresh the
  observer; pushes stalled after 4 of ~40 commands on the AMF870).

Fix: one long-lived `status-observe` per run, never `status`; stimulus = a physical button press at fixed times
(3, 5, 10, 15 min) for steps 4 and 5; app closed until a separate final run; note every restart of the CLI;
power-cycle the purifier between runs that must start from a clean observer list.

### 9. Stale state after a lost or corrupt final frame; no reconciliation, no indicator - MEDIUM

Quotes: "| ACTUEEL | Beschikbaar; laatste waarden blijven staan, hoe oud ook | ..."; "| Beschadigd bericht |
Overslaan en tellen; ...".

- Notifications are NON as far as known, ~2 kB in two IP fragments, never retransmitted; "Notification lost
  (UDP): Unnoticed" [N01 8.3]. Corruption by the device: 1 in 1,800-5,300 [R 3.2]. Status cannot be fetched on
  demand [N08 2.6].
- If the missed frame was the last change before a quiet period, HA shows the wrong state as current for
  hours. This is the defect the report holds against kongo09 ("oude waarden als actueel"). RFC 7641 3.3.1: past
  Max-Age (60) "the client MUST NOT assume that the enclosed representation reflects the actual resource state".
- The Observe sequence number cannot detect the gap: on the AC2220 it advanced 41 -> 96 while no local client
  received anything [N08 2.6].
- The user has no staleness signal; "tijd sinds laatste bericht" exists only in the diagnostics download.

Fix: state the residual risk in the report. A frame dropped as corrupt is a known missed change: flag the state
as unconfirmed and trigger recovery (re-registration; nudge if measurement shows one exists). Measure whether a
re-registration is answered directly on the AC3220 (AC4220: renewals were answered within 10 s while running
[N08 5.4], which may only have been the next push; AC2220: not answered directly); if it is, the 60 s refresh
doubles as a poll. Offer an opt-in periodic refresh nudge if a side-effect-free
key is found. Add the throttled timestamp entity from issue 4.

### 10. A broken status path is undetectable by design - MEDIUM

Quote: "**Instellen slaagt** zodra de info-aanvraag en een sync lukken. Een statusbericht is geen voorwaarde."

- Info and sync are tens of bytes; the status datagram is ~1.9-2.1 kB and fragmented [R 3.1; measured as two
  fragments on an AC2220, N08 2.6]. N01 4.5: networks that drop fragments give "sync and control work, status
  never arrives".
- Setup succeeds, the session sits in "NOG GEEN STATUS", silence is never a fault: no error, no log line, no
  repair issue, ever.

Fix: use two oracles. (a) The optional "press a button" step at setup. (b) At runtime: after N (3) acknowledged
state-changing commands with no frame within 10 s each and no frame since start, raise a repair issue
("statusberichten komen niet aan: controleer IP-fragmenten/VLAN/firewall"). Add a diagnostics flag
"never received a frame".

### 11. Identity is checked once; a wrong device at the stored IP is adopted - MEDIUM

Quote: "Bij een DHCP-melding eerst het MAC-adres vergelijken zonder netwerkverkeer, en bij een nieuw IP-adres
alleen het adres bijwerken."

- Sync carries no identity. After a lease swap (router reset, two purifiers) the session attaches to whatever
  answers on the stored IP and shows and controls the other unit.
- `DeviceId` is in every frame and in the info reply [R 3.3], but no runtime rule uses it. N07 9.1 asked for
  "is this still the same device" checks; N10 3.3 cites the WiZ `unexpected_device` precedent.
- Manual entries have no MAC ("MAC-adres alleen uit DHCP-gegevens"), so the no-traffic MAC match cannot work for
  them; tinkerologie #8 (AC3210) is this failure [N07 3.3].
- No rediscovery when OFFLINE persists. N07 9.4 proposed a periodic broadcast info scan.

Fix: verify `DeviceId` on every decoded frame (drop and raise a repair issue on mismatch); do an info GET at
start and on every OFFLINE -> reachable transition; learn the MAC from the neighbour table after a successful
exchange (reject all-zero/broadcast) and register it as a device connection; after 5 minutes OFFLINE run the
broadcast/multicast info scan for the known `device_id` and update the host.

### 12. Command budget does not add up; lock scope and queuing undefined - MEDIUM

Quote: "`{"status":"success"}` verwachten binnen 3 seconden; hooguit twee herhalingen, elk met een nieuwe sync en
opnieuw versleuteld; totaal maximaal 10 seconden."

- Three attempts of (sync + 3 s control) fit in 10 s only if a sync deadline is <= 0.3 s. No sync deadline is
  given for commands; elsewhere it is 5 s. With 5 s, one failed attempt uses 8 s.
- Step 4 adds an unbounded wait on top (issue 1).
- A scene touching five entities queues five full exchanges on the lock. The protocol accepts several keys per
  write [N01 6.1] and step 5 uses that for one case only.
- Not specified: whether a command's sync counts as probe/contact, behaviour in TWIJFEL, cancellation when a newer
  command for the same key arrives (slider).

Fix: per attempt sync 1.5 s + control 2 s, three attempts, hard 10 s wall clock including lock wait; coalesce
commands that arrive within 100 ms or while the lock is held into one multi-key write (last value per key wins);
a command exchange updates contact and probe state.

### 13. "One socket for the whole lifetime" lacks rules for local failure, restart, unload and stray notifications - MEDIUM

Quote: "Eén socket en één abonnement per apparaat, voor de hele levensduur van de integratie. Niets afbreken op
een timer."

- A connected UDP socket pins the local address. If the HA host's address or interface changes, the socket is
  dead for good; the rule forbids replacing it.
- Every HA restart, entry reload or IP update creates a new source port, i.e. "a new client endpoint to the
  device" [N01 section 1]. If the firmware keeps several observers (AC2220: two clients worked), the old one
  keeps receiving 2 kB notifications "until its own expiry or until replaced" [N01 5.3]. Session churn has
  wedged older devices [N01 7.6]. Development means many restarts.
- The design never says to deregister (GET with Observe 1, same token) on unload, although the report faults
  aiocoap for not doing so and N10 line 120 lists it. It never says to answer notifications with an unknown
  token by RST (RFC 7641 3.5/3.6).

Fix: persist a local UDP port and the observation token per config entry so a restart re-attaches to the same
endpoint/token (RFC 7641 4.1: replace, not add); recreate the socket on local OS errors and on entering OFFLINE,
with the same port; best-effort deregistration (1 s) on unload and stop; RST for notifications with an unknown
token from the device address. Measure whether the device honours Observe 1 and RST.

### 14. Sync is the only probe and the only gate; alternatives were not evaluated - MEDIUM

Quote: "| Verbinden | Sync (3 pogingen, 5 seconden per poging), daarna de abonnementsaanvraag zonder op antwoord
te wachten | ..." and 6.8: "ICMP-ping of een statusaanvraag als bereikbaarheidscontrole".

- The registration is sent only after a successful sync, although reading status needs no sync [R 3.1]. A
  firmware or moment where sync is unanswered yields no data at all.
- N01 10.2 and N07 9.5 recommended `GET /sys/dev/info` or an empty CON ping (AMF870: RST in < 0.1 s, 2 of 2)
  as probes. Both are trivial in an own CoAP layer, do not change the counter, and info returns `device_id`
  (solves issue 11 for free). 6.8 rejects only ICMP and the status GET.
- A sync every 60 s changes the session counter. Whether the counter is global or per endpoint is unknown
  [N01 3.2]; if global, our probes may invalidate the Air+ app's local commands. Not in the measurement plan.

Fix: send the registration at connect regardless of the sync result; frames count as reachable; measure the
three probes side by side (issue 5) and prefer info GET if it answers during silence, with sync as fallback;
add a measurement "app commands while a script syncs every 10 s".

### 15. No ordering rule; `Runtime` rule has false positives; `Runtime` is both a sensor source and "niet tonen" - LOW

Quote: "| Dubbele berichten | Nooit op berichtnummer filteren | Apparaten hergebruiken berichtnummers |"

- Correct for MID, but then no ordering rule exists. The report rejects aiocoap's RFC 7641 3.4 filter; an older
  frame applied last would roll state back until the next change.
- "Looptijd lager dan voorheen" also fires on a reordered frame and, if the counter is 32-bit milliseconds,
  every 49.7 days (width unverified).
- 6.6 lists a "laatste herstart" sensor from `Runtime` and two lines later "Niet opslaan of tonen: `Runtime`".
  A boot time computed per frame jitters and changes on every frame.

Fix: order frames by `Runtime` within a boot epoch (drop a frame whose `Runtime` is lower by less than 10 s);
treat a drop to a small value as reboot; compute boot time once per epoch and update only when it moves by more
than 30 s.

### 16. Sync replies are not validated in the design; re-sync after bad frames cannot help - LOW

Quote: "| Beschadigd bericht | Overslaan en tellen; na meer dan 3 op rij opnieuw sync en abonnement | ioBroker,
openHAB |"

- [R 3.2] notes malformed sync replies (2 of 1,317 NUL-padded [N11 F6]) but 6.3/6.4 have no rule. N11 section 3
  item 9: "Validate the key as exactly 8 hex characters".
- Decoding does not depend on the client counter [R 3.1], so a new sync cannot repair undecodable frames.

Fix: sync reply must match `^[0-9A-Fa-f]{8}$`; a malformed reply is contact (device alive) but a failed attempt
for a command. After more than 3 bad frames in a row: re-register (escalate token), no sync.

### 17. Active discovery and discovery filtering are underspecified - LOW

Quote: "**Drie routes naar dezelfde instelstroom:** DHCP-herkenning op alle acht MXCHIP-voorvoegsels, een actieve
zoektocht via broadcast en multicast, en handmatige invoer van het IP-adres."

- Not stated: one send per enabled IPv4 adapter (HA `network` helper), an unconnected socket, replies arrive from
  the unicast address, 3-5 repeats 1 s apart (the AMF870 missed 39 % of broadcast ARP requests and broadcast
  CoAP travels the same way: N07 3.2, an inference), a listen window (RFC 7252 Leisure default is 5 s), no
  result in Docker bridge mode.
- MXCHIP OUIs are shared with other brands and with other Philips products [N07 3.3]. The reply must be 2.05 with
  JSON containing `device_id`, `product_id` and a `modelid` in the supported list; everything else aborts
  silently with a short deadline (2 tries, 2 s).
- Evidence for broadcast/multicast answers is one AC0950/10 [R 3.3].

### 18. Capture filter and log pipeline lose the data needed to explain failures - LOW

Quote: "sudo tcpdump -n -i <interface> -w ac3220.pcap 'host <ip-luchtreiniger> and (udp port 5683 or (ip[6:2] &
0x3fff != 0))'"

- The filter is correct for fragments but excludes ARP and ICMP. ARP is how "sync never left the host" was
  proven [N11 F5]; ICMP port-unreachable shows orphaned observers. `host <ip> or arp host <ip>` (no port clause)
  captures everything including fragments.
- `-D` writes to stderr with no timestamps [code `cli.py:9, 91-94`]; the pipeline timestamps stdout only, so the
  log has no t0 for "tijd tot het eerste bericht". Add `2>&1`.

## 3. Rules I tried to break and could not

- Lock, sync immediately before each write, counter + 1, re-encrypt on every retry. Survives the probe/command
  race, a NUL-padded stored key, a device reboot with a new counter and a foreign sync between our sync and
  write (answer `failed`, retry). Needs unique per-request tokens so a late sync reply cannot be matched to a
  newer request.
- Frame decoding independent of the session counter. A probe sync cannot break the stream (kongo09 test
  `test_decrypt_uses_key_embedded_in_payload`; 77 probes next to 1,599 notifications on the AC2220).
- Fire-and-forget registration and refresh with the same token. A late answer is just a frame; RFC 7641 3.3.1
  and 4.1 cover it; this removes the tinkerologie failure mode.
- Never filter on MID.
- Skip and count undecodable frames instead of ending the stream.
- ACK for incoming CON is in the CoAP subset.
- No ICMP ping and no status GET as probe.
- Regular unicast traffic (refresh + probe) keeps the neighbour entry in unicast revalidation, which is the
  right answer to the broadcast-ARP deafness, as long as neither is disabled.
- DHCP flow without a second session; the plaintext info request neither registers an observer nor touches the
  counter.
- Integers only for writes; composite power+mode in one write.
- Setup not waiting for a status frame (but see issues 4 and 10).
- CLI syntax in 7.2 is valid for aioairctrl 0.3.1 (`-H`/`-D` before the subcommand, `-I` after `set`); Python
  >= 3.12 matches `pyproject.toml`.

## 4. Questions the report does not address

1. Full transition table: events per state, definition of contact, probe deadline, which state a successful
   probe returns to.
2. Token and MID policy: fixed observation token, unique token per request, matching on (address, token),
   source-address filter, maximum datagram size.
3. Stop, unload, reload, remove: deregistration, RST policy, persistent port/token.
4. Sync failure at HA start: load the entry and retry inside the session, or `ConfigEntryNotReady` (N10 D2a/D2b).
   The second recreates the socket on every retry.
5. Commands in TWIJFEL and in NOG GEEN STATUS; command exchanges as probes; coalescing; superseding.
6. Per-key accepted read-back values.
7. The first 2-3 minutes after a power cut (AC0951: ~124 s without MCU link): validity of the first frame,
   command behaviour, start-up timeouts.
8. Non-2.xx responses, a response on the observation token without the Observe option (RFC 7641: observation
   over), Block2 or CON notifications if the capture shows them (no 7.3 row for either).
9. Coexistence: Air+ app local session, second HA instance, old HACS integration still enabled for the same host
   (detect and raise a repair issue).
10. Staleness shown to the user.
11. Who chooses the refresh mode and how (option, automatic ladder), and how an ineffective mode is detected.
12. What 7.3 decides for questions 3, 5 and 7 (no rows), although question 3 is named in chapter 1 as one of
    three properties that "bepalen het ontwerp".
13. Recovery from local network errors on the HA host.

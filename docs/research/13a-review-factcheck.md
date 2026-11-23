# 13a - Fact-check review of `docs/onderzoek.md`

Date: 2026-11-22. Role: independent reviewer, lens "fact-checker".
Checked: the full report (541 lines) against notes 01-12, against the clones under `scratchpad/src`,
and against three live sources (PyPI, `hacs/default`, `home-assistant/core` dev on raw.githubusercontent.com).
Nothing was executed from the clones. Paths below are relative to `scratchpad/` unless absolute.

Overall: the report is accurate on almost every number, key and code claim. I found no fabricated
figure. The problems are (a) later evidence in note 08 that never reached appendix A, (b) two wrong or
unsupported statements in the measurement plan, (c) a summary that states an inference as fact, and
(d) several design-relevant findings from notes 06, 07 and 11 that were dropped.

## 1. Issues, most damaging first

### M1. Appendix A write column ignores the AC4220/12 hardware-verified facts (medium)

Report, appendix A:
- "| `D03105` | Displayhelderheid | 0 uit, 101 automatisch, 115 laag, 123 fel | deels: 0 bevestigd |"
- "| `D03135` | Lampfunctie | 0 uit, 1 luchtkwaliteit, 2 sfeerlicht | deels: 0 bevestigd |"
- "| `D03130` | Pieptoon | 100 aan, 0 uit | ? |"
- legend: "**?** wordt door andere projecten geschreven maar is op deze familie niet bevestigd."

Evidence: `src/ruaan-deysel_homebridge-philips-airctrl/src/device/keys.ts:9-24` (quoted in note 08, lines
412-418), "hardware-verified on real AC4220/12 firmware":
1. "D03105 (DISPLAY_BACKLIGHT) is READ-ONLY: writes are ACKed and silently discarded ... The real writable
   light control is D03135 (LAMP_MODE), domain {0, 1, 2}."
2. "D03130 (BEEP) ... Writing 1 reads back 100." (so the write is accepted on this family)
3. "D0310C = 5 ... reports fan speed 18, i.e. speed 5 IS Turbo."
4. "D03137 (AMBIENT_LIGHT_MODE) is NOT writable: writing 0 reads back 1."

The table was taken from note 09 section 4 (which it matches exactly) and rests on kongo09 #416 (AC4221/11,
probably string-typed writes). Note 08 is the stronger source and says the opposite for `D03105` and
`D03135`. The report itself uses the AC4220/12 fact in 6.3 ("op een AC4220/12 werden schrijfopdrachten naar
de displaysleutel genegeerd"), so appendix A and 6.6 contradict 6.3. Consequence: 6.6 makes the display
brightness select a normal entity on a key that is probably read-only on this family, and treats the lamp
key as doubtful while it is the likely working control.

### M2. Measurement 8: "met de huidige tools niet te testen" is false (medium)

Report 7.2 row 8: "Antwoordt de info-aanvraag altijd? | Staat in de opname zodra de nieuwe protocollaag er
is; met de huidige tools niet te testen".

Evidence: `src/tinkerologie_philips-airctrl/src/philips_airctrl/cli.py:190-193` has the sub-command
`device-info-raw` ("Read plaintext /sys/dev/info resource (no encryption, suits push-only firmware)");
`philips-airctrl` 1.5.1 is on PyPI (checked today). Note 07 line 146: an AC0951/13 was read with
`coap-client -m get coap://<ip>/sys/dev/info` (kongo09 #300).

Why it matters: 6.5 builds identity and setup on this endpoint ("De `device_id` daaruit is de unieke
sleutel", "Instellen slaagt zodra de info-aanvraag en een sync lukken"). It is shown only on AC0950/AC0951,
not on any AC32xx. Note 07 section 8 lists it as measurements 2 and 3 (answers unicast/broadcast/multicast?
`device_id` == status `DeviceId`? value of `option`?). The report postpones the test until after the
protocol layer exists.

### M3. 7.3 has an outcome row without a measurement, and the existing evidence points the other way (medium)

Report 7.3: "Schrijfopdracht met de huidige waarde geeft een volledig statusbericht | Dat is een
bijwerkingsvrije manier om bij het opstarten de status op te halen".

- No row in 7.2 tests a same-value write (row 6 only asks whether "de status de nieuwe waarde terugmeldt").
- Note 11 F4, tinkerologie #132 (AMF870/15): "Writing the value it already had (100 -> 100) was acked, but no
  push came within 45 s." Only a changed value forced a push.

### M4. Cloud: "geen extra gegevens ... dezelfde stilte" drops the one thing the cloud does better (medium)

Report 3.4: "De cloud levert geen extra gegevens, meldt ook alleen bij verandering"; 6.8: "Geen extra
gegevens, dezelfde stilte, en een geheim uit de app nodig."

Note 06 line 41: "It does offer one thing local CoAP lacks: a shadow `get` makes an online device send a
fresh full report within 1 to 2 s (measured on an AC3737, not on an AC3220)"; line 228 (node-red: "An online
AC3737 answers a get with a fresh report within 1-2 s"); line 319: "Open, and worth one experiment: whether
a cloud `shadow/get` also makes the device emit a local CoAP notification." Status on demand is exactly the
gap in 6.3 "Opstarten zonder status". Keeping the cloud out of the critical path still stands; the reason
given is too strong.

### M5. Summary states push-on-change as a fact about this firmware (medium)

Report 1: "De recente wifi-firmware (`AWS_Philips_AIR_Combo@86`) meldt de status alleen wanneer er een
waarde verandert. In stand-by is het apparaat stil, en een statusaanvraag wordt pas bij de volgende
verandering beantwoord."

- The report's own 3.2 labels both rows "[aanname], waarschijnlijk" for the AC3220, and appendix B says the
  behaviour is "afgeleid uit time-outstatistieken" for the 2200/4200 series.
- Note 11 F1 correction 2: "'does not answer until the next change' holds for an Observe-0 GET; a GET without
  Observe or with Observe 1 is never answered at all." The summary's "statusaanvraag" hides that.
- Same-series data the report never mentions: note 03 lines 477-483, PR #40 by an AC3221 owner: the device
  "can be reachable and return status snapshots while a fresh observe stream stays quiet or does not deliver
  an initial payload"; note 03 concludes "the evidence conflicts across models".

### L1. 4.1: a hung reconnect is not unbounded (low)

Report 4.1: "Eén verloren pakketje laat een commando of herverbinding onbeperkt hangen".
Code: `src/kongo09_philips-airpurifier-coap/custom_components/philips_airpurifier_coap/coordinator.py:44-49`
(auto-restart timer), `:66-70` (`reconnect()` cancels the previous `_reconnect_task`), `timer.py:33-58`.
Note 02 line 304: "the task hangs until the *next* watchdog tick cancels it". True for commands (issue #363,
1 h 46 min), not for reconnects (180 s per attempt).

### L2. 3.2 corruption rate range and attribution (low)

Report: "**[gemeten: AMF870/15 en AC0850]**: één op de 1.800 tot 5.300 statusberichten".
Note 11 F6: "rates seen are 1 in 1,800 to 1 in 18,000" (1 of 18,108 in the first 51 h); the AC0850 report
carries no rate at all, only the observation.

### L3. 3.2 row 2 mixes two different AC2220 measurements (low)

Report: "**[gemeten: AC2220/10]**: 6,5 seconden tot 14 minuten" for "abonnementsaanvraag wordt pas bij de
volgende verandering beantwoord". Note 08 section 2.6: first status "6.5-64 s after the GET across five
runs", 9 minutes after a power cut; "up to 14 min" is silence on a live subscription (already used in row 1).

### L4. 6.8: "De AC2220 negeert ping" is one of three data points (low)

Note 11 F2 (AC2210, 0.2.3/@86, tinkerologie #172): "zero packet loss during all 7 outages (453 pings, avg
~100 ms". Note 08 line 251 (AC0850/31): "ICMP replies in milliseconds throughout". Rejecting ICMP is still
right, but for most siblings the reason is the opposite: ping keeps answering while the application is
silent.

### L5. 3.1 still has the uncorrected "text values are ignored" (low)

Report 3.1: "Als tekst gestuurde waarden worden genegeerd". Appendix B of the same report: "'Tekstwaarden
worden genegeerd' is te breed: de tekst '0' voor uitzetten werkte wel." (note 11 F7).

### L6. 6.2: the aiocoap "128 s" reason is theoretical; 3.2 row 9 rests on a 2021 report (low)

Report 6.2: "aiocoap verwerpt statusberichten waarvan het volgnummer niet oploopt, tot 128 seconden lang."
Note 01 lines 331-335: "No evidence this happens; noted as a trap for custom clients." Note 08 section 2.6
(AC2220/10): "The Observe sequence number is the purifier's global count and keeps rising across sessions."
Report 3.2: "Berichtnummers van het apparaat zijn onbetrouwbaar | Meerdere modellen sturen steeds hetzelfde
nummer": source is betaboon/aioairctrl #3 from 2021-04-24 (note 01 line 64), older generation; note 01
lines 524-528 says current aiocoap no longer de-duplicates responses, which is why both forks removed the
patch. The other three reasons for an own CoAP codec stand.

### L7. 6.7 and appendix B claim a second check of the HA-2026 findings that does not exist (low)

Report 6.7: "een tweede, onafhankelijke controle staat in bijlage B"; appendix B: "door een tweede agent
gecontroleerd: zie de uitkomst in [`docs/research/13-review.md`]". `docs/research/` holds 01-12 and
README.md only; notes 11 and 12 do not cover note 10. Also the changes that "het plan raken" are never
named. Spot checks I did today: `homeassistant/components/marketplace/manifest.json` exists on core `dev`
(note 10's "Marketplace built into HA 2026.11" is plausible); `hacs/default` lists
`kongo09/philips-airpurifier-coap` and not `tinkerologie/ha-philips-airpurifier`; no core component
`philips_pureprotect` or `philips_air_local`.

### L8. Smaller wording/label points (low)

- 3.2 last paragraph: "(AC0650, AC0651, nieuwere AC1715) zijn een ander hardwareplatform met een
  ESP32-module" - for the AC1715 note 12 U5 says "Whether that is firmware or hardware is unknown" and an
  AC1715 on Wi-Fi 91.1 still speaks CoAP. The next sentence of the report half-retracts it.
- 3.3: "[gemeten: AC0950/10]" for broadcast and multicast: note 07 line 175 "The log cannot prove which."
- 2.2 table puts "Lampfunctie" under "Alleen in de app"; manual (note 09 section 1.2): "You can press the
  light function button to switch to lamp mode".
- 1 and 4.4: "Op verwante modellen" (plural) for figures that come from one AC2210 and one AC2220/10.
- 3.1: status size "vermoedelijk gefragmenteerd ... [aanname]" is understated: measured on an AC2220/10,
  "one ~2.1 KB datagram, which arrives as two IP fragments" (note 08 section 2.6).

## 2. Omissions that change a design decision or the measurement plan

1. After a write, the push stream can stall (note 11 section 3 item 8, #132: "in 4 of ~40 commands, the
   existing observation got 0-1 pushes", next change "2-4 min later after a reconnect"). 6.4 step 4 waits for
   "het eerstvolgende statusbericht" with no bound and no re-registration.
2. Sync replies must be validated as exactly 8 hex characters (note 11 item 9 and F6: NUL-padded key in
   about 1 of 700-2,000 sync replies; "every command until the next sync would then fail", once for 9 min).
   The report only says "Ook sync-antwoorden zijn soms misvormd"; its design uses sync as probe and before
   every command.
3. Consequence of the broadcast-ARP finding (note 11 F5: "31 of the 32 never left the HA host"; note 07 line
   385: unicast traffic every 30-60 s keeps the neighbour entry on unicast revalidation; line 182: send
   discovery probes 3-5 times). The report lists the fact and draws no design consequence.
4. kongo09 double shutdown -> config entry `failed_unload`, only an HA restart recovers: issue #397 on an
   AC3210/12 with v0.37 (note 02 line 311, note 04 line 161). Missing from 4.1 and relevant to the interim
   advice in 4.4, which recommends v0.37.
5. Lamp writes may need several keys in one request (note 11 section 3 items 2 and 4: "The app changes
   D03105 and D03135 together"; `D03104` appears next to `D03105` on 0.2.1/@86). Measurement 6 only lists
   single keys and does not ask whether `D03104` is present.
6. The Air+ app and the cloud can trigger pushes (note 04 line 230: opening the app "made the device respond
   again"; note 06 line 314). Measurements 3-5 need the app closed on all phones, and "does opening the app
   produce a local push" is itself worth one test.
7. Lighter probes were not considered for the measurement plan: empty CoAP ping (note 11 section 3 item 1:
   AMF870 "answers an empty CoAP ping (CON, code 0.00) with an RST in < 0.1 s"; said to be what the app
   does) and plaintext `GET /sys/dev/info` (note 07 line 385).
8. Speed 5 equals Turbo and speed 3 equals Medium at fan level (note 09 section 5.2; keys.ts fact 3). The
   fan entity in 6.6 offers both sets without saying so.
9. Homey reports for the AC3221/13 (note 05 section 2): control of power and speed works since the
   2026-08-01 test build. That is same-series evidence that local writes work; the report presents write
   acceptance on the series as wholly unknown.
10. HA 2026.11 replaced HACS by the built-in Marketplace and custom integrations ship their own `brand/`
    folder (note 10 lines 42-62). 6.7 still says "via HACS" and names neither.

## 3. Checked and correct (load-bearing)

1. Encryption: AES-128-CBC, key and IV = halves of upper-case hex MD5("JiangPan" + counter), counter in
   clear at the front, SHA-256 over counter + ciphertext at the end
   (`src/kongo09_aioairctrl/aioairctrl/coap/encryption.py`).
2. aioairctrl 0.3.1: every request NON, sent once, no timeout anywhere (`aioairctrl/coap/client.py`).
3. kongo09: watchdog 60 s x 3 = 180 s, full client rebuild; coordinator seeded from
   `entry.data[CONF_STATUS]`; `available` = "status is not None"; observe loop without try/except
   (`coordinator.py:42-49, 78-83, 133-141`, `__init__.py:158-171`, `philips.py:80-82`).
4. Wrong key `D03-42` for the AC3210/AC3220/AC3221 select in both integrations (`philips.py:1173-1176` +
   `const.py:451`; `device_models.py:618-634` + `const.py:428`); the #181 dump has `D0312A`.
5. tinkerologie: renewal every Max-Age, `RENEWAL_TIMEOUT = 10.0`; ciphertext computed once before the retry
   loop (`philips_airctrl/coap/client.py:29, 311-334, 369-386`); reconnect closes the client and needs a
   status within `COAP_CALL_TIMEOUT = 30` (`coordinator.py:48, 565-577`); `set_child_lock` writes `cl`,
   `filter_reset` knows only `fltsts*`/`D05-14` (`services.py:148, 173-176`); no `status_nudge` for
   `_CONFIG_AC3210`.
6. MAC prefixes: eight MXCHIP OUIs as listed; tinkerologie manifest has four and lacks `6879C4`; kongo09
   has five. tinkerologie is not in `hacs/default` (fetched today).
7. Flapping figures: 118 vs 14 outages, 10 h 22 min vs 3 h 21 min (one AC2210, 2026.10.3 vs 2026.10.2);
   56 vs 5 periods (AC2220/10, 30 h vs 8.5 days); 47 % of 414 renewals (note 11 F2/F3).
8. Appendix B tallies: 10 confirmed / 4 partly of 14 (note 11), 6 confirmed / 5 partly of 11 (note 12).
9. Appendix A meanings and values against note 09 section 4 and the #181 dump: `D0310C` 0, 1-5, 17, 18, 19,
   -16; `D03105` 0/101/115/123; `D03110` 0 and 2..13; `D03135` 0/1/2; `D0312A` 0/1; `D0312C` 1/4/7/10;
   `D03130` 100/0; `D03112` inverted; filters 9600/9501/720/621; `D01S0D` "688001001384".
10. Measurement commands: `aioairctrl==0.3.1` exists on PyPI and requires Python >= 3.12; `-H`, `-D`,
    `status -J`, `status-observe -J`, `set -I K=V` exist in `aioairctrl/cli.py`; the tcpdump fragment
    expression is correct.
11. ESP32 logger (AC2220/10, 0.2.3, `@86`): 14.8 h, 1,599 notifications, sync about 100 ms, same-token
    re-registration after Max-Age + 15 s, two clients at once (note 08 section 2.6).
12. openHAB (30 s / 60 s minimums, observe restarted only after a missed ping, sync before each command
    under a lock, Unicorn control unconfirmed) and ioBroker 2.4.1 (300 s, re-subscribe after each good probe,
    30/60/120 s) (notes 08 and 12).
13. NikGro: EU account, AC3220/10, type Unicorn, device firmware 0.2.3, "Wi-Fi firmware 86" (screenshot),
    read-only, controls not exercised (`src/NikGro_philips-air-plus-homeassistant/docs/ac3221-cloud-investigation.md:135-136, 238-263`).
14. kongo09 master last commit 2026-07-26 (`964ef21`); tinkerologie integration 7,164 lines, 64 model
    constants.

## 4. Not checked

- aiocoap internals (taken from notes 01/02 file references; aiocoap is not among the clones).
- GitHub issue pages (not reachable; I relied on notes 04 and 11).
- Note 10's Home Assistant rule texts beyond the three spot checks above.

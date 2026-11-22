# 08 - How the non-Python ecosystems handle reliability (read from source)

Round 2, 2026-11-22. Angle: actual implementations (ioBroker, openHAB, Homey, Homebridge x3, ESP32) instead of
forum summaries. Nothing was executed; all repositories were cloned read-only and only read.

Evidence tags: **[V-code]** read in a cloned source file (path relative to `scratchpad/src`, with line numbers),
**[V-git]** read in a commit message of the clone, **[V-doc]** read in a document inside a cloned repository
(a maintainer's own measurement log, so primary for "what they measured", not verified by me on hardware),
**[V-forum]** verbatim from the round 1 forum copies, **[I]** my inference, **[H]** hearsay (a source quoting
another source).

---

## 0. Bottom line

1. The "liveness probe" that ioBroker and openHAB adopted is in both cases the **same packet: `POST /sys/dev/sync`**.
   Nobody uses a CoAP empty-CON ping, and nobody polls `GET /sys/dev/status`. `GET /sys/dev/info` is used as probe
   only in older or model-gated code (phipsair 2022, ruaan-deysel's Homebridge plugin for the CX3550 only).
2. The best primary measurement for the AC3220's family is not in ioBroker or openHAB but in a small ESP32-C6
   project that runs against an **AC2220/10, firmware 0.2.3, `AWS_Philips_AIR_Combo@86`**: the device does not answer
   an Observe GET directly, pushes only on change (silent for up to 14 minutes on a live subscription), does not
   answer a plain status GET while quiet, and **answers sync in about 100 ms the whole time**. Its author's rule:
   "'Alive' is judged by sync, not by status".
3. The implementations disagree on what to do with the observation while the device is quiet, and the
   disagreement follows the hardware each author owns:
   openHAB leaves it alone (restarts it only after a missed probe), ioBroker re-subscribes after every successful
   probe (every 5 min of silence), the ESP32 client re-sends the same-token registration after 75 s of silence,
   ruaan-deysel's Homebridge plugin opens a new-token registration every Max-Age (60 s) and requires an answer within
   10 s, Homey tears everything down every 10 minutes and on every command.
   Only two of these are documented against `@86` siblings: same-token refresh on an AC2220 (works, no duplicates)
   and new-token renewal on an AC4220/12 (keeps pushes flowing; without it they stopped after about 150 s).
4. None of the non-Python projects implements a "nudge" for purifiers. The only nudge outside Home Assistant is
   in ruaan-deysel's Homebridge plugin, for the CX3550 fan only (`D0310A = 1`, twice at most, at 1.5 s and 65 s).
5. Homey - the platform where AC3220/10 owners report "niet stabiel" - has the weakest design of the set: a
   600 s observation window that is treated as an error if no frame arrived, an observation teardown plus two
   syncs for every command, one corrupt frame ends the observation, and a model-ID whitelist for commands.
   For a push-on-change device in clean air this guarantees gaps **[I]**.

---

## 1. Sources read

| Clone (under `scratchpad/src`) | Upstream | HEAD / version | Stack | Hardware evidence for `@86` Gen3 devices |
|---|---|---|---|---|
| `iobroker-community-adapters_ioBroker.philips-air` | github.com/iobroker-community-adapters/ioBroker.philips-air | ed9ebee, v2.4.1, 2026-11-17 | Node, `coap` (node-coap) ^1.6.0 | CX7550/01 and CX3550/01 on `Combo@86` (`docs/CX7550.md:57`, `docs/CX3550.md:44`); AC3221 register table from one owner's logs |
| `openhab_openhab-addons` (sparse: `bundles/org.openhab.binding.philipsair`) | github.com/openhab/openhab-addons | 6d7767c5 (repo), binding commits 9c5c36c6 2026-10-14 "[philipsair] Initial contribution (#21901)" and 4783cad9 2026-10-28 | Java, Eclipse Californium | read path confirmed on AC3210/12 (0.2.3, `Combo@86`) and AC0950/10 (0.3.3, `Combo@86`); commands unconfirmed (README.md:101) |
| `marcelrv_openhab-addons_philipsair` | marcelrv fork, branch `philipsair-52` | 32d2df55, 2026-09-26 | Java | older pre-rework code; superseded by the bundle above |
| `biemond_com.athom.philipsair` | github.com/biemond/com.athom.philipsair (Homey "Philips Air") | 614de40, v1.0.86, 2026-11-07 | Node, `node-coap-client` 2.1.0 | none documented in the repo; AC3220/10 is in the model whitelists |
| `atdr_homebridge-philipsair-platform` | github.com/atdr/homebridge-philipsair-platform | 24b5d69, v2.2.0, 2026-11-18 | Node shelling out to the `aioairctrl` CLI | extensive measurements on one **AC0850/31, `Combo@86`** (`.claude/skills/aioairctrl-and-device-protocol/SKILL.md:74-418`) |
| `ruaan-deysel_homebridge-philips-airctrl` | github.com/ruaan-deysel/homebridge-philips-airctrl (same author as the tinkerologie HA integration) | da54024, v1.0.0, 2026-11-17 | TypeScript, **own CoAP stack on `dgram`** | **AC4220/12, 0.2.3, `Combo@86`** (`test/fixtures/README.md`, `docs/research/2026-homebridge-coap-audit.md`) |
| `chayuto_seeed-XIAO-ESP32-C6` | github.com/chayuto/seeed-XIAO-ESP32-C6 | 9b74185, 2026-09-30 | C on ESP-IDF, own minimal CoAP | **AC2220/10, 0.2.3, `Combo@86`** (`docs/design/02_airpurifier_coap.md:107-172, 305-325`) |
| `MaddogWarner_homebridge-philips-air-purifier-complete` | github.com/MaddogWarner/... | 8b02baa, v4.2.0, 2026-11-21 | Node + Python daemon with a vendored betaboon-era `aioairctrl` | none for local CoAP; 2026 work is almost all on the Air+ cloud path |
| `mfrister_phipsair` | github.com/mfrister/phipsair | 2e0bb43, 0.5.0, 2022-05-10 | **Python** (not Go) | none (AC2889 era); covered in round 1 (`01-coap-protocol.md:377-391, 630`) |
| `hemtjanst_klimat` | github.com/hemtjanst/klimat | 1abe12f, 2022 | Go | none: 2020 HTTP-era client (`philips/device.go`), no CoAP session logic. Not useful. |
| `dl08/node-coap-client/package` | registry.npmjs.org node-coap-client 2.1.0 | - | - | read to check Homey's transport defaults |

Not found / not available: a Rust, C# or Go CoAP implementation for these devices (one web search, no hit);
the "ESPHome hacked air purifiers" Hackaday project returned by the search replaces the Wi-Fi module with an ESP32
and is a different (hardware) route - not read. The first clone attempts for `biemond/com.philips.air`,
`biemond/homey-philips-air` and `roldoe/domoticz-philips-air` failed (no such public repo under that name).

---

## 2. Per implementation

### 2.1 ioBroker.philips-air 2.4.1 (`lib/coap.js`, 612 lines)

**Request types and timeouts**
- Requests go through node-coap `coap.request(...)`. The POSTs (`/sys/dev/sync`, `/sys/dev/control`) do not set
  `confirmable`, so they are CON with node-coap's own retransmission (library default, not in this repo);
  the adapter adds its own deadline of `aliveTimeout` (default 30 000 ms) and then stops the retransmit timers
  with `req.sender.reset()` **[V-code]** `lib/coap.js:144-202`, `:101-112`. The comment explains why: an unanswered
  CON POST otherwise lives for "its full exchangeLifetime (~247s) and then emits a late 'error' ... crashed the whole
  adapter" (`:154-158`).
- The observation is `GET /sys/dev/status` with `observe: true, confirmable: false` (NON) **[V-code]** `:399-405`.

**Status acquisition**: observe only, no polling. Connect order is fixed: sync, mark connected, then subscribe -
"the device only starts pushing observe notifications on /sys/dev/status once the /sys/dev/sync handshake has
established the session" (`:249-252`).
A subscription that gets no first notification within `subscribeTimeout` (= `aliveTimeout`, 30 s) is **not** an
error: "Some CX3550/01 firmwares keep the observe stream quiet after a successful sync even though control commands
work. Treat that as a usable but quiet session and keep the observe request open" (`:374-397`). So the instance is
"connected" after a successful sync even with no data.

**Silence and the probe** (`_checkAlive`, `:284-335`)
- Watchdog: `staleTimeout = max(aliveTimeout * 10, 120000)` = **300 s** by default, re-armed by every valid frame
  (`:64`, `:342-357`, `:450-453`).
- When it fires: `await this.sync()` (a fresh random 8-hex nonce, `:125-135`).
  - probe fails (no answer within `aliveTimeout`, 30 s, CON retransmissions inside that window) -> `_reconnect()`,
    which immediately marks the connection lost (`:234-238`). So **one missed probe = offline**, about 330 s after the
    last frame.
  - probe succeeds -> stays connected, logs only at debug, and **re-subscribes** (closes the old request locally,
    opens a new observe GET with a new token) (`:319-334`).
- Rationale in the commit that introduced it **[V-git]** 4590b1a (2026-08-24): "His CX7550/01 sent a single status
  frame in 4.6 hours while answering all 26 /sys/dev/sync probes in the same log, so the adapter rebuilt a perfectly
  working session every staleTimeout - 25 'connection lost / connected' pairs in that window. Raising the timeout
  cannot fix this; it only stretches the cycle."
- Why it re-subscribes after a good probe **[V-git]** 830b868: "a device whose registration silently expired
  answers the probe but never delivers data again - something the unconditional reconnect used to repair as a side
  effect. The watchdog now re-subscribes quietly instead".
- Stated limitation: "Firmwares that never answer /sys/dev/sync (e.g. AC2889 fw 1.0.7) therefore behave as before"
  (`:291-292`) - i.e. the probe is designed so that a success can only prevent a reconnect.

**Reconnect and backoff** (`_reconnect`, `:230-281`)
- delay = `min(reconnectInterval * 2^(failures-1), 120000)` -> **30, 60, 120, 120 ... s** (`:264`, `:11`).
  (README.md:34 still says "up to five minutes"; the code was lowered to two minutes in 830b868: "a device that
  comes back must not wait that long to be noticed".)
- A safety timer of `aliveTimeout + subscribeTimeout + reconnectInterval` guards an attempt that never settles
  (`:246`); 4b3daca fixed a race where a shorter net discarded the backoff.
- Log damping: first 3 failures at error, later ones at debug (`:13`, `:268-271`); one power-cycle hint at the
  third failure: "Philips air devices can stop responding until restarted" (`:274-279`).
- Overlap guard: `reconnectInterval` is forced >= `aliveTimeout`, "otherwise overlapping /sys/dev/sync POSTs pile up
  against the device" (`:50-59`).

**Corrupted frames etc.**
- NULs are stripped before parsing: `encryptedData.toString('utf8').replace(/\0/g, '')`; then a hex check and a
  minimum length of 72; then the SHA-256 digest; any failure is a warning and the packet is dropped, the session
  stays (`:488-517`, `:421-429`, `:459-466`).
- node-coap hazard: `req.reset()` on an observe request "can throw 'Empty messages must be empty' (node-coap issue
  #175)", hence `_safeReset` (`:92-112`, `:367-372`).
- Counter increment uses `>>> 0` because `& 0xffffffff` "would yield a negative number for keys with the high bit
  set" (`:531-536`).
- No handling of duplicate MIDs or observe sequence numbers in the adapter (left to node-coap).

**Commands**: `{"state":{"desired":{"CommandType":"app","DeviceId":"","EnduserId":"", ...}}}` encrypted with the
key from the last sync (or last probe) + 1; no sync per command, no retry, no read-back (`:573-596`).

**Several devices / clients / app**: one adapter instance per device. Nothing about the Air+ app or a second
local client in README or code (not found).

**Nudge**: none. Timer writes are deliberately blocked on the CX3550 because "Local timer write payloads can make
the firmware set `D03102` to `0`, which switches the fan off" (README.md, CX3550 section).

### 2.2 openHAB Philips Air binding (official bundle, merged 2026-10-14)

Files: `openhab_openhab-addons/bundles/org.openhab.binding.philipsair/src/main/java/org/openhab/binding/philipsair/internal/`
`connection/PhilipsAirCoapAPIConnection.java` (548 lines), `PhilipsAirHandler.java`, `connection/CoapProfile.java`.

**Request types and timeouts**
- Californium endpoint with a private configuration: `DEDUPLICATOR = NO_DEDUPLICATOR`, `ACK_TIMEOUT = 20 s`,
  `EXCHANGE_LIFETIME = 65 s` **[V-code]** `PhilipsAirCoapAPIConnection.java:520-525`.
- Observe request is explicitly **CON**: `request.setType(Type.CON); request.setObserve();` (`:188-191`).
  POSTs use `Request.newPost()` (Californium default CON) (`:531-547`).
- Two clients on one endpoint: commands with `TIMEOUT = 25000` ms, pings with `PING_TIMEOUT = 5000` ms (`:68-69`,
  `:133-135`). With a 20 s ACK timeout a 5 s ping is effectively single-shot **[I]**.
- **MID workaround**: "Workaround for the deduplication of the device: once it sent a notification, the request
  continues after the highest MID seen, instead of the MID Californium would assign. A MID is never used twice."
  (`:192-200`); the highest MID is tracked with wrap-around (`:283-288`) and covered by eight unit tests
  (`.../connection/PhilipsAirCoapAPIConnectionTest.java:577-660`). The older fork had the same idea in a cruder form
  (`marcelrv_openhab-addons_philipsair/.../PhilipsAirCoapAPIConnection.java:149-154`). The claim that the *device*
  de-duplicates by MID is the maintainer's; I found no measurement for it.

**Status acquisition**: observe only (`isPushingStatus()` returns true, `:383-386`). No polling of status.

**The connection check** (`ensureConnected`, `:143-172`), called by the handler every `refreshInterval`
(default 60 s, `PhilipsAirHandler.java:397`, `:477-488`):
- `pingAfterMs = max(refreshInterval, 30 s)`, `staleAfterMs = max(2 * refreshInterval, 60 s)` (`:72-73`, `:123-125`).
- If the last contact is younger than `pingAfterMs`: nothing.
- Otherwise `pingDevice()`: **`POST /sys/dev/sync` with the current counter** (`:229-251`, `:259`); a valid 8-hex
  answer counts as contact and replaces the counter. Comment: "A device in standby only pushes changes and does not
  answer a status request, so the silence is only a failure if the device does not answer a ping either" (`:154-155`).
- Ping failed -> `deviceMissed = true`, nothing else (`:156-161`). The thing goes OFFLINE through the handler when the
  cached status is older than `staleAfterMs` (`:378-381`, `PhilipsAirHandler.java:599-603`): with defaults that is
  **two missed pings, 120 s after the last contact**.
- Ping succeeded and no ping was missed before -> **the observe relation is left untouched** (`:162-164`).
- Ping succeeded after a miss -> "the device may have lost the relation while it was away": proactive cancel
  (deregistration) and a new observe request (`:165-171`).
- No backoff: the check simply runs every `refreshInterval`.

**Key handling**
- A counter sync precedes a new relation only while `hasSync` is false (`:177-186`); more than 3 consecutive
  undecodable notifications clear `hasSync` so the next relation re-syncs (`:354-358`).
- **Every command does its own sync and then the control POST under one lock** (`exchangeLock`): "the synced counter
  is only valid until the next exchange" (`:85-87`, `:445-473`). The counter is taken from the sync answer, +1,
  masked to 32 bits (`:463`). The reply must be JSON with `"status":"success"` (`:480-488`), otherwise the command
  fails; no retry. `EnduserId` is `"1"` (`:495-497`).
- Commands are refused until the profile (register scheme) is known; the profile is persisted per host so commands
  work right after a restart (`:98`, `:435-438`, `PhilipsAirHandler.java:436-450`, `:665-680`).

**Weak spot [I]**: the thing only goes ONLINE after the first decoded status (`PhilipsAirHandler.java:587-603`).
A push-on-change device that is quiet when openHAB starts stays OFFLINE until its next push; the ping keeps
`lastContact` fresh but `lastStatus` is still null (`:378-381`). This matches the round 1 forum report "becomes online
after some time".

**Corrupted frames**: `content.trim()` (`:300`), then length, hash and JSON checks; invalid notifications are
ignored and counted (`PhilipsAirCoapCipher.java:47-62`, `:316-361`). Californium's own de-duplication is off.

**Several devices / clients / app**: one endpoint per thing. README only says commands "follow the Philips Air+
app"; nothing about the app interfering (not found).

**What is proven on `@86`**: reading an AC3210/12 and an AC0950/10 ("Reading the status of an AC3210/12, an
AC0950/10 and an AC2939/10 has been confirmed on a real device; the commands have not been confirmed on a device
yet, and neither has any other recent model", README.md:101). The only "answered the ping" log lines in the forum
copy are from the `@79` classic AC2939, not from the `@86` device **[V-forum]** (`forum/openhab/t170501_posts.json`,
post 24).

### 2.3 Homey "Philips Air" 1.0.86 (`drivers/philipsairCoap.js`, `drivers/air.js`)

- Library: `node-coap-client` 2.1.0; defaults `confirmable: true, retransmit: true`, `ackTimeout 2 s`,
  `ackRandomFactor 1.5`, `maxRetransmit 4` **[V-code]** `dl08/node-coap-client/package/build/CoapClient.js:67-69, 1042-1044`.
  The client is the library's **static** `CoapClient` class shared by all devices (`philipsairCoap.js:188`, `:320`).
- Session loop (`getCurrentDataCoap`, `philipsairCoap.js:186-316`): optional 60 s start delay (`:223`),
  `coap.reset(target)`, `tryToConnect` (for plain `coap:` this only creates the socket, it is not a ping -
  `CoapClient.js:865-880`), **sync as CON with retransmission** (`:231`), `setAvailable()` as soon as the sync
  answered (`:238`), then `observe(..., { confirmable: false, retransmit: false })` (`:309-312`).
- **Every observation is ended after 600 000 ms** (`:212-214`). If no frame arrived in that window the result is
  the error "No response received" (`:213`), which feeds the retry counter; otherwise the loop restarts after 1 s
  (`air.js:81-107`). Retry delay: `min(5000 * 2^min(n-1, 6), 300000)` -> **5, 10, 20, 40, 80, 160, 300 s**
  (`air.js:101`).
- **One bad frame ends the observation**: "Invalid message hash" and "Message corrupted 2" are thrown inside the
  notification callback and caught by `finish(error)` (`:262-284`, `:303-305`).
- Unavailable is only ever set for an invalid address (`air.js:94-98`); otherwise the device stays "available"
  with stale values.
- **Commands** (`setValueDataCoap`, `:318-380`): `stopObserving` (local only - node-coap-client just forgets the
  request, `CoapClient.js:531-540`), sync with up to 3 attempts x 10 s without library retransmission (`:133-166`),
  **`sleep(2000)`**, control with up to 3 attempts, then the interrupted observation is completed and restarted
  1 s later with another sync. One key per command; a second key means the whole sequence again.
- 2026-10/11 hardening: `coapPacketGuard.js` validates the datagram shape before the library parses it, because
  "The dependency throws on unsupported options ... request/observe promise catches cannot catch it" (`:44-46`);
  changelog 1.0.82 "fixing top cpu and retry loop", 1.0.76/1.0.77 "corrupted messages", "check valid json".
- Control whitelist by exact model string, e.g. `['AC3737/10', ..., 'AC3220/10', 'AC0950/10', 'AC3210/12',
  'AC0951/13', 'AC3221/13']` (`drivers/deviceCoap/device.ts:51, 133, 153, 187, 206, 265`).

**Why it is unstable on this family [I]**: (a) a push-on-change device that is quiet for 10 minutes produces an
"error" and a growing pause of up to 300 s during which no observation exists; (b) every command destroys and
rebuilds the observation with two syncs; (c) a single corrupt frame does the same; (d) the shared static client.

### 2.4 Homebridge, atdr/homebridge-philipsair-platform 2.2.0

Shells out to the `aioairctrl` CLI (`status-observe -J` as a long-running child, `set` as one-shot children), so
the wire behaviour is aioairctrl's (NON, no timeouts). What is valuable is the measurement log of one
**AC0850/31 on `AWS_Philips_AIR_Combo@86`** and the timing rules derived from it.

Constants **[V-code]** `src/accessories/accessories.handler.js:24-163`:

| Constant | Value | Stated reason |
|---|---|---|
| `STALL_TIMEOUT` | 300 s | idle timer, "a *fault* detector, not a poll" |
| `OFF_STALL_TIMEOUT` | 30 min | while the device reports itself off: "an AC0850 held on a single uninterrupted subscription answered nothing for 25 minutes and then resumed on its own, so no constant makes the short timeout right" |
| `REFRESH_INTERVAL` | 60 s floor, adaptive up to 300 s | re-subscribe to ask for a reading; "not derived from any device measurement" |
| `RESUBSCRIBE_GRACE` | 30 s | "A device back from a power cut answered fresh subscriptions in 17 s and 39 s, and one at startup in 38 s" |
| `SET_TIMEOUT` | 12 s | aioairctrl's handshake "has no timeout of its own ... no output and no exit at 180s and again at 900s" |
| `RESTART_DELAY` | 5 s | respawn of an ended stream |
| `FAILURE_ESCALATION_THRESHOLD` | 3 | "a single dropped stream is normal; a run of them is not" |
| `MAX_WRITE_RETRIES` | 1 | one resend of a write the device answered and did not apply |
| `WRITE_SETTLE` | 3 s | a push composed before the write "still carries the old value" |
| `WRITE_COALESCE_WINDOW` | 75 ms | "A purifier that received a power-on and a speed write a second apart applied the first and silently dropped the second three times in four (issue #82)" |
| `SPEED_DEBOUNCE_WINDOW` | 350 ms | slider drags; "every write makes the purifier beep" |

Measured behaviour of the AC0850/31 **[V-doc]** `.claude/skills/aioairctrl-and-device-protocol/SKILL.md`:
- "ICMP replies in milliseconds throughout, the signature of a combo WiFi module (`AWS_Philips_AIR_Combo@86`)
  answering ping in firmware while the application sleeps. **Never conclude the device is dead from a short
  timeout.** Allow at least 90 s." (`:93-98`)
- "**It pushes spontaneously only while values are changing.**" (`:100`); off-state bursts were all value changes
  (`pm25`, `rssi`, `free_memory`), "not protocol keepalives" (`:175-208`).
- "**On a stream left alone it pushes every ~9 s; re-subscribing is what costs.**" Table over one night, 1165
  readings: left alone median 9 s; after a refresh kill median **140 s** (p90 294 s, max 834 s); after a stall kill
  median **529 s** (`:117-138`). "Every long silence in the night follows a kill, and none occurs on a stream left
  untouched".
- "**Switched off, it answers only intermittently, and 25 minute silences are normal.**" The device "answers
  normally for the first ~11 minutes after switch-off" (`:145-173`, `:213-217`).
- Standing rule: "**never tear down a subscription on a timer unless something independent of that timer says the
  device is at fault.**" (`:265-270`)
- "**A write that lands is echoed immediately by a `"StatusType":"control"` push**": `set -I D03102=0` "produced a
  status within the same second, carrying the new value and `"StatusType":"control"` where every periodic push says
  `"status"`"; seven further writes "were all echoed within 1 s"; but one earlier write was answered 83 s later
  (`:369-381`).
- Write verification rules: "only a status that arrived after the write is evidence about it", "only a status that
  mentions the key is evidence about that key", "only a disagreement is evidence that it was lost" (`:383-391`).
- "**[unverified] The device serves one connection at a time.** A second `aioairctrl` ... completes the sync
  handshake and then simply receives nothing." (`:393-398`)
- Caveat by the author: "it is unknown whether the `sync` POST succeeded during the silent 25 minutes; it
  demonstrably did during an equivalent silence earlier the same day" (`:272-279`).

Recent behaviour changes **[V-git]**: 4f33b89 (2026-11-17) "show an unreachable device as No Response ... A device
that has reported itself switched off is exempt, since it answers only now and then"; 088cd14 (2026-11-17)
"re-subscribe as soon as a write proves a silent device is back ... one opened against a purifier that was off at the
mains is never answered. It sat until the stall timer, up to 300 s, even after a write had been answered ... Never on
a stream producing readings, where re-subscribing is the expensive operation (#71), nor on a device known to be off".

Caution: these are teardown-and-respawn costs (new process, new UDP source port, new sync, new token, the old
observer left orphaned on the device). They do not tell what a same-socket registration refresh costs **[I]**.

### 2.5 Homebridge, ruaan-deysel/homebridge-philips-airctrl 1.0.0 (own CoAP stack, AC4220/12)

- Transport **[V-code]** `src/airctrl/coap/socket.ts`: every request is **NON** (`:151`), default timeout 8 s
  (`:20`), no retransmission, responses matched "by TOKEN, not message ID. Observe notifications reuse the original
  request's token but carry fresh message IDs, so message-ID matching would drop every push" (`:58-60`), random
  4-byte token per request (`:185`, `:224`), random initial MID then +1 (`:79`, `:131-133`), **datagrams accepted only
  from the device's address** (`:81-86`), malformed datagrams ignored (`:126`), deregistration = same token with
  Observe=1 (`:237`).
- Observation renewal **[V-code]** `src/airctrl/client.ts:284-399`: a **new-token** registration every Max-Age
  (default 60 s, `:16`, `:365-371`) on the same socket and encryption session, must be answered within
  `RENEWAL_TIMEOUT_MS = 10 000` (`:17`), up to **3 attempts** on timeout (`:386-399`: "CoAP NON has no retransmission.
  Keep the current token while a bounded retry recovers one dropped registration, without a sync or control write"),
  then the old token is cancelled.
- Watchdog **[V-code]** `src/device/coordinator.ts:222-245`: `3 x Max-Age` (180 s) without a status -> unavailable
  and reconnect. Backoff `5 s` doubling to `60 s` (`:28`, `:146-147`).
- Quiet-device exception, **CX3550 only** (`src/device/models.ts:835-850`): `quietObserve`,
  `ignoreMalformedObservePushes`, `statusSilenceProbeMs: 10 min`, and the probe is **`GET /sys/dev/info`**
  (`coordinator.ts:247-270`: "This opt-in fan firmware only pushes changes. Reachability preserves its cached state;
  it does not advance telemetry freshness").
- **Nudge, CX3550 only**: `initialStatusNudge: { D0310A: 1 }` sent 1.5 s after the registration if no status came,
  and once more at 65 s; `retries: 0, resync: false, timeoutMs: 2000` (`coordinator.ts:176-213`,
  `models.ts:849`). Nothing is restored because the value written is the one the device has while on.
- Commands (`client.ts:470-545`): up to 5 retries with a resync between attempts, 2 s per request, 6 s total
  budget (kept inside HomeKit's ~10 s write limit).
- Field evidence **[V-doc]** `docs/research/2026-homebridge-coap-audit.md`: "The live AC4220/12 was running plugin
  0.2.0 ... Its current logs reproduced the recurring 180-second unavailable/reconnected cycle and initial Observe
  timeout."; upstream Python evidence quoted there: "AC4220 firmware 0.2.3, 270-second run, 106 pushes, four renewals
  at approximately 64/124/185/245 seconds, pushes continued through 269.6 seconds"; "A later live check exposed one
  lost renewal response after the initial clean 744-second window."
- Their own caveat: "Requiring an initial renewed response every minute would break models that deliberately never
  provide one".

### 2.6 ESP32-C6 logger, chayuto/seeed-XIAO-ESP32-C6 (AC2220/10, 0.2.3, `Combo@86`)

The closest independent hardware evidence to the AC3220. Its status fixture reports `"D01S04": "Cobra"`
(`components/philips_air/test/ac2220_status.json`), the AC4220 fixture reports `"Unicorn"`.

- Transport **[V-code]** `components/philips_air/philips_coap.c`: all requests **NON** (`:59`), one UDP socket
  `connect()`ed to the purifier, **one 4-byte token for the whole session** (`:41-42`), MID random start then +1
  (`:40`, `:58`), replies matched on the token (`:106`), Max-Age read from each reply with default 60 (`:159`).
- Loop **[V-code]** `projects/02_airpurifier_coap/main/main.c:372-388`, `:320-327`: after `max_age + 15 s` without a
  frame it re-sends the Observe GET with the same token ("Re-registering gets an immediate status back, or tells us
  it is gone"); after 3 unanswered re-registrations it does a sync; if the sync fails the device is "lost" and a
  sync is retried **every 10 s**; after 3 failed syncs it sweeps the /24 with sync probes (at most every 5 min).
  A repeated Observe sequence number is counted as a duplicate and dropped (`:361-363`).
- Measurements **[V-doc]** `docs/design/02_airpurifier_coap.md`:
  - "**The purifier doesn't answer an Observe GET directly.** It registers the client and sends at its next push:
    the first status came 6.5-64 s after the GET across five runs." (`:147-151`)
  - "**Pushes come on change.** While PM2.5 moves they arrive every 1-2 s; when nothing changes they can be over
    60 s apart. The Observe sequence number is the purifier's global count and keeps rising across sessions."
    (`:152-154`)
  - "**Re-registering with the same token doesn't duplicate notifications** (0 dups after a manual `g`), and **two
    clients at once work**: the Mac's aioairctrl observed while the XIAO was reading." (`:155-157`)
  - "**Status can't be fetched on demand.** Quiet for 6+ minutes (PM2.5 steady), the purifier pushed nothing to the
    XIAO or to the Mac's aioairctrl at the same time. A plain GET without Observe went unanswered too (2 x 15 s).
    Sync still answered in ~100 ms. So 'purifier alive' has to be judged by sync, not by status ... The re-sync after
    three silent re-registers is harmless but pointless when the purifier is just quiet. That time, the quiet spell
    lasted ~12.5 minutes. The Observe sequence number jumped 41 -> 96 across it, although neither local client
    received anything" (`:162-170`)
  - "The purifier ignores ping, and its MAC prefix isn't in the integration's DHCP list ... The sync probe is the
    reliable discovery method." (`:113-115`)
  - "The reply is one ~2.1 KB datagram, which arrives as two IP fragments" (`:144-146`); 2088 hex characters on the
    wire (`:111`).
  - Overnight: "14.8 h of unbroken uptime, 297 readings in a row with no gap (77 carried forward, 1,599
    notifications ...)" (`:306-309`). Each carried-forward 3-minute bucket was backed by an answered sync probe
    (`:217-221`), so 77 sync probes ran next to a live observation without disturbing it.
  - Power cut: "The purifier came back on by itself, in the same mode (sleep) ... the first sync was answered ...
    The first reading landed at 08:33 with no help ... The 9 minutes were normal purifier silence, not a fault ...
    the purifier stayed silent for up to 14 min even on a live subscription" (`:310-319`).
  - Still untested by the author: purifier switched off while the client stays up (`:335-340`).

### 2.7 MaddogWarner homebridge-philips-air-purifier-complete 4.2.0 (local path)

Vendored betaboon-era `aioairctrl` with the de-dup monkeypatch (`aioairctrl/coap/client.py`), an observe loop that
on any exception sleeps 5 s and reconnects (`philips_air_api.py:1117-1148`), no silence watchdog, no probe; the
Node side restarts a dead daemon after 5/10/30/60 s (`index.js:86`). Useful only for two command-timing constants:
`POWER_ON_SETTLE_MS = 1500` ("Hold any mode write this long after a power-on so the device has finished waking up")
and a mode re-send within 60 s if "a mode sent while the purifier is still powering on" did not stick
(`index.js:49-57`; written for the cloud AC1715). 2026 commits are almost entirely about the Air+ cloud path.

---

## 3. Comparison table

| | ioBroker 2.4.1 | openHAB (5.3) | Homey 1.0.86 | atdr Homebridge 2.2.0 | ruaan-deysel Homebridge 1.0.0 | ESP32 (chayuto) | kongo09 / tinkerologie HA (round 1) |
|---|---|---|---|---|---|---|---|
| Sync / control type | CON (node-coap), own 30 s deadline | CON (Californium), ACK timeout 20 s, 25 s / 5 s client timeouts | CON; sync at connect with retransmit, commands without, 10 s x 3 | NON via aioairctrl CLI, 12 s kill | NON, 2 s per try, 6 s budget | NON, configurable timeout | NON, no timeout in aiocoap |
| Observe GET type | NON | CON, MID follows device's highest MID | NON | NON | NON | NON | NON |
| First frame required to be "up" | no (30 s, then "quiet stream") | yes (thing offline until first status) | no (available after sync) | yes for "responding" | yes, except CX3550 | no (linked after sync) | yes |
| Registration renewal | new token after each good probe (every 300 s of silence) | none while pings are answered | whole session every 600 s and after every command | kill + respawn 60-300 s after a reading (adaptive) | new token every Max-Age (60 s), answer required in 10 s, 3 tries | same token after Max-Age + 15 s of silence, no answer required | kongo09 none; tinkerologie 60 s with 10 s deadline |
| Liveness probe | `POST /sys/dev/sync` | `POST /sys/dev/sync` | none | none (a write that is answered counts) | `GET /sys/dev/info`, CX3550 only | `POST /sys/dev/sync` | none (tinkerologie: info probe for push-only models) |
| Probe trigger | 300 s without a frame | 60 s without contact (min 30 s) | - | - | 10 min without a frame | per quiet 3-min bucket; every 10 s while lost | - |
| Offline criterion | 1 failed probe (30 s incl. retransmits) | no contact for 2 x interval (2 missed pings, 120 s) | never (only bad address) | 3 failed polls; exempt while device is off | 180 s silence, or failed info probe (CX3550) | 1 failed sync | 180 s silence / failed renewal |
| Backoff | 30, 60, 120 s cap; 3 loud then debug | none, fixed 60 s check | 5 s doubling to 300 s | 5 s respawn | 5 s doubling to 60 s | fixed 10 s, /24 sweep every 5 min | exponential (see 02/03) |
| Sync before each command | no | yes, under a lock | yes (+2 s sleep), tears down the observation | yes (new CLI process) | no, resync on failure | n/a (read-only) | no |
| Command confirmation | none | `"status":"success"` check | payload present | read-back on the stream, 1 resend | accepted flag, retries | n/a | optimistic |
| Bad frame | drop + warn, session kept | drop; > 3 in a row -> re-sync | **ends the observation** | CLI's problem | fatal by default, tolerated per profile | counted as error | tears down or tolerated, version dependent |
| NUL / whitespace | strips `\0` | `trim()` | strips `\u0000-\u0019` after decrypt | - | - | - | see round 1 |
| MID / sequence handling | library | de-dup off, MID workaround | library | monkeypatch | token only | token only, drops equal Observe seq | de-dup off |
| Nudge | none | none | none | none | CX3550 only (`D0310A=1`) | none | tinkerologie: display toggle for push-only models |
| Tested on `@86` | CX7550, CX3550 | AC3210/12, AC0950/10 (read only) | not documented | AC0850/31 | AC4220/12 | AC2220/10 | see round 1 |

---

## 4. What these sources add to the Gen3 register picture

Round 1 file `09-ac3220-capabilities.md` already has the register dictionary; only deltas from non-Python code:

- **Two full status fixtures of siblings on 0.2.3 / `Combo@86`**:
  `ruaan-deysel_homebridge-philips-airctrl/test/fixtures/ac4220-12-status.json` (59 keys, `D01S04` "Unicorn",
  `D0110C` 23) and `chayuto_seeed-XIAO-ESP32-C6/components/philips_air/test/ac2220_status.json` (`D01S04` "Cobra",
  `D0110C` 18). Only in the AC4220: `D03115`, `D03122`, `D03125`, `D03224`, `D05102`. Only in the AC2220: `D0110B`,
  `D03104`, `D0540C` (22000), `D05412`, `D05413`. Both carry `D03R81` (base64 blob), `D0313B` (20), `D03182`,
  `D03136`, `D0311F`, `D03106`, `D03112`, `D0312B`, `D0312C`. `D0540C`/`D05412`/`D05413` do not appear in any
  round 1 note.
- **Platform name differs inside the "family"**: AC2220 says "Cobra", AC4220 says "Unicorn". openHAB selects its
  `unicorn` profile by `D01S04 == "Unicorn"` *or* a model list that includes AC2210/AC2220/AC2221
  (`CoapProfile.java:208-209`, `:312-317`). A new integration must not key only on "Unicorn".
- **openHAB `unicorn` profile** (`CoapProfile.java:50-54`, `:81-85`, `:195-206`, `:686-733`): modes `D0310C`
  0 auto, 17 sleep, 1-5 manual, 19 medium, 18 turbo; fan speed fallback `D0310D`; timer `D03110` 1-12; humidity
  setpoint `D03128`; settings `D03130` beep (100/0), **`D03134` standby sensors (1/0)**, **`D03115` allergy sleep
  (1/0)**, **`D03112` display switch, inverted (0 = on, 1 = off)**; brightness `D03105` 0/101/115/123; lamp `D03135`
  0/1/2; `D03122` gas level index 1-4; `D0312C` AQI notification threshold; `D0110C` capabilities (18 = "mini"
  variant AC0950/51). Status: "the commands have not been confirmed on a device yet".
- **ioBroker `AC3221` table** (`lib/mapping.js:343-410`, built from an AC3221/13 owner's logs): `D0310C` also has
  **`-16` = "off"**; `D0310D` reports **18 for both speed 5 and turbo** (`:106-113`); `D03105` "+100 offset, not
  linear: 101=auto (not low), 115=low (not mid)"; `D0312A` only value 1 = pm2.5; `D03240`, `D03137`, `D03134`
  "Deliberately left unmapped pending device-side confirmation".
- **ruaan-deysel, "hardware-verified on real AC4220/12 firmware"** (`src/device/keys.ts:9-24`):
  1. "D03105 (DISPLAY_BACKLIGHT) is READ-ONLY: writes are ACKed and silently discarded, and it reads 101 when the
     lamp is on ... The real writable light control is D03135 (LAMP_MODE), domain {0, 1, 2}."
  2. "D03130 (BEEP) is boolean but stored as 0 / 100 ... Writing 1 reads back 100."
  3. "D0310C = 5 (MODE_B) reports fan speed 18, i.e. speed 5 IS Turbo."
  4. "D03137 (AMBIENT_LIGHT_MODE) is NOT writable: writing 0 reads back 1."
  Item 1 matters for the nudge: the tinkerologie HA nudge toggles the display backlight; on this family that write
  may be a no-op. Round 1 (`09-...:233`) already recorded a partial failure of `D03105` writes on an AC4221.
- **Homey** sends for AC3220/10 only `D0310C` in {0, 1, 2, 17, 18}, `D03105` in {0, 100}, `D0312A`, `D03137`
  (`drivers/deviceCoap/device.ts:51-84, 204-222`); 100 is outside the brightness domain above, which fits users'
  "cannot control" reports **[I]**.
- **atdr**: AC32xx speed ladder `D0310C` 17, 1, 2, 3, 4, 5, 18 and AC4220/AC4221 without 18; light on `D03135`
  (`src/accessories/accessories.models.js:337-371, 545-599`), citing the ruaan-deysel finding **[H]**.
- **`StatusType`**: pushes after a write carry `"StatusType":"control"`, periodic ones `"status"` (AC0850/31,
  atdr SKILL.md:369-381). Both fixtures above show `"StatusType": "status"`.

---

## 5. Recommended session algorithm

Design goals taken from the evidence: silence is never a fault; reachability is proven by sync; nothing is torn
down on a timer; one socket per device for the lifetime of the entry; every wait has a deadline.

### 5.1 Objects

Per device: one UDP socket (stable source port), one session token for the observation, a client key (counter)
guarded by an exchange lock, `last_contact` (any valid datagram from the device), `last_frame` (last decoded
status), `last_registration`, counters for diagnostics. Datagrams are accepted only from the device address and
matched by token; receive buffer >= 4 kB (status is about 2.1 kB and arrives IP-fragmented).

### 5.2 States

```
            sync ok                      first decoded frame
 OFFLINE ------------> REACHABLE_NO_STATE --------------------> LIVE
    ^   backoff            |   ^                                 |  ^
    |                      |   | probe ok                        |  | probe ok
    |   3 probes missed    v   |                                 v  |
    +------------------- SUSPECT <------- 60 s without contact --+--+
```

| State | Entity availability | What runs |
|---|---|---|
| OFFLINE | unavailable | sync attempts with backoff |
| REACHABLE_NO_STATE | device reachable, values unknown (do not fail setup) | registration refresh, probe, optional one-shot nudge |
| LIVE | available, last values kept however old | registration refresh, probe |
| SUSPECT | unchanged (still available) | probe retries |

### 5.3 Timings

| Step | Value | Source of the number |
|---|---|---|
| Request type | NON for everything, application-level deadline per request | chayuto and ruaan-deysel on `@86`; all Python libraries |
| Sync deadline | 5 s per attempt | sync answers in ~100 ms on the AC2220; openHAB pings with 5 s |
| Connect | sync (3 attempts, 5 s apart), then Observe GET, do not wait for an answer | AC2220: "doesn't answer an Observe GET directly"; ioBroker quiet-stream rule |
| Registration refresh | re-send the Observe GET with the **same token**, fresh MID, every Max-Age (60 s) counted from the last registration, fire-and-forget | same-token: chayuto (no duplicates); period: AC4220 lapse after ~150 s gives two chances |
| Probe trigger | 60 s without any contact | openHAB default; chayuto probes per quiet window |
| Probe packet | `POST /sys/dev/sync` under the exchange lock; store the returned key | ioBroker, openHAB, chayuto |
| Probe miss handling | retry every 10 s; **3 consecutive misses -> OFFLINE** (about 90 s after the last contact) | openHAB needs 2 misses in 120 s, ioBroker 1 miss with retransmits in 30 s, atdr escalates at 3 |
| Offline backoff | 10, 10, 10, 30, 60 s, then every 60 s | chayuto fixed 10 s; ruaan-deysel cap 60 s; ioBroker cap 120 s with the argument that a returning device must be noticed quickly |
| After a successful sync from OFFLINE or SUSPECT | send a fresh registration immediately | openHAB "the device may have lost the relation while it was away"; atdr #215 |
| Log policy | "lost" once, "restored" once, power-cycle hint at the third failed reconnect, the rest at debug | ioBroker |
| Command | lock; sync; control with key + 1 (32-bit wrap); expect `{"status":"success"}` within 3 s; up to 2 more tries, each with its own sync; total budget 10 s | openHAB (sync per command, success check); ruaan-deysel (budget) |
| Command confirmation | the next frame that mentions the key and arrives after the control answer; if it disagrees, resend once, then raise | atdr rules and `MAX_WRITE_RETRIES = 1` |
| Multi-key actions | one control payload (e.g. power on + mode) | atdr #82; otherwise wait 1.5 s after a power-on (MaddogWarner) |
| Bad frame | strip NUL and whitespace, check hex / length / digest / JSON; drop and count; after more than 3 in a row re-sync and re-register | ioBroker, openHAB |
| Duplicate handling | never by MID; drop a frame only if its Observe value equals the previous one | ruaan-deysel, chayuto; round 1 MID=1 finding |
| Startup without state | entities unknown but device reachable; optional nudge after 20 s without a frame, at most twice per connect (second after 65 s) | ruaan-deysel CX3550 timings; ioBroker/chayuto "wait" as the default |
| Reboot detection | `Runtime` lower than before -> treat cached values as unconfirmed, re-register | chayuto logs `Runtime`; round 1 suggestion |

Two strategy switches should exist from day one, because the evidence does not settle them for the AC3220:
`registration_refresh = same_token | new_token | none` and `startup_nudge = off | <key>`.

### 5.4 Proven on `@86` hardware versus assumed

| Claim in the algorithm | Status |
|---|---|
| Sync is answered while the status stream is silent | **Proven** on AC2220/10 0.2.3 (chayuto, ~100 ms, incl. 6+ min and 12.5 min quiet spells), on CX7550/01 (ioBroker commit 4590b1a: 26 of 26 probes in 4.6 h with one status frame). Stated by openHAB for standby. On the AC0850/31 "demonstrably" once, not re-verified. **Not shown on an AC3220.** |
| Sync probes do not disturb a running observation | **Proven** on AC2220 (77 probed quiet buckets in a 14.8 h run with 1,599 notifications) and CX7550 (probe + re-subscribe). |
| An Observe registration is not answered until the next push | **Proven** on AC2220 (6.5-64 s, 9 min after a power cut), AC0850 (9-53 s, minutes when off), "initial Observe timeout" on AC4220. |
| A plain status GET is not answered while quiet | **Proven** on AC2220 (2 x 15 s) and AC0850 (300 s). |
| Same-token re-registration is harmless | **Proven** on AC2220 only (0 duplicates). |
| Same-token refresh every 60 s prevents the ~150 s lapse | **Assumed.** The lapse and its cure are documented for the AC4220/12 with a *new-token* renewal (philips-airctrl PR #35 as quoted in the ruaan-deysel audit). Nobody tested same-token on a Unicorn-platform device. |
| The lapse exists on the AC3220 at all | **Assumed / unknown.** The AC2220 run does not show it, but that client re-registers after 75 s of silence, so it could not have seen it. |
| No answer to a refresh is normal | **Proven** on AC2220 ("harmless but pointless when the purifier is just quiet"); the opposite design (10 s deadline) is the documented cause of flapping on AC2220 in round 1 (F7). On the AC4220 renewals *were* answered within 10 s while the unit was running. |
| NON requests are sufficient | **Proven** (chayuto, ruaan-deysel, Python). CON also works (openHAB observe, ioBroker/Homey POSTs). Whether notifications are sent NON or CON on the AC3220: unknown. |
| Two local clients can coexist | **Conflicting**: works on AC2220 (chayuto); "[unverified] one connection at a time" on AC0850 (atdr). Design for one socket and tell users not to run a second client. |
| A write is echoed by a `StatusType: control` push within about 1 s | **Proven** on AC0850/31 only (8 of 9 observed writes; one took 83 s). **Assumed** for the AC3220. |
| Sync before every command is safe | **Proven in code use** on openHAB and Homey, but openHAB's commands are "not confirmed on a real device" for Unicorn; Homey users of AC3221/13 report working control after the 2026-08 build. |
| A write-based startup nudge works on purifiers | **Unproven outside HA.** Only CX3550 (`D0310A=1`) in ruaan-deysel's plugin. `D03105` is reported read-only on an AC4220/12, so the backlight toggle may not work on this family. |
| openHAB's "request MID must follow the device's highest MID" | **Unproven.** Maintainer's workaround without a published measurement; chayuto and ruaan-deysel use random start + increment successfully on `@86`. |
| ICMP ping as liveness | **Rejected**: AC2220 "ignores ping", AC0850 answers ping "while the application sleeps". |
| 3 misses / 90 s to offline, backoff cap 60 s | **Design choice**, bracketed by the implementations above; not a measured optimum. |

---

## 6. Corrections and additions to round 1

- "openHAB and ioBroker ... explicit liveness probe and reconnect backoff": correct for ioBroker; **openHAB has a
  probe but no backoff** (fixed interval) and still requires a first status frame before the thing is online.
- ioBroker's forum wording "Wiederholungen mit 30 / 60 / 120 Sekunden" matches the code; the README's "up to five
  minutes" is stale.
- `mfrister/phipsair` is Python, not Go. `hemtjanst/klimat` is an HTTP-era Go client and irrelevant here.
- The two repositories round 1 could only cite second-hand are now read: `atdr/homebridge-philipsair-platform`
  (AC0850/31 measurements) and `chayuto/seeed-XIAO-ESP32-C6` (AC2220/10 measurements).
- "Push only on change for the AC22xx family is an inference" (round 1, file 11): it is now a direct, logged
  observation on an AC2220/10 0.2.3 `@86` by an independent client.

---

## 7. Open questions (for a hardware session with the user's AC3220/10)

1. Does the AC3220 stop notifying about 150 s after a single registration (AC4220 behaviour), and does a
   same-token refresh every 60 s prevent it, or is a new token needed?
2. Does the AC3220 answer a registration directly while running (AC4220: renewals answered within 10 s) or only
   with the next push (AC2220)?
3. Does every accepted control write produce a `StatusType: control` push with the full state? If yes, does a
   write of the already-current value, or of a key the device discards (`D03105` on the AC4220), also produce one?
   That would give a side-effect-free startup nudge.
4. Does `GET /sys/dev/info` answer on the AC3220 while it is quiet, as a second probe that does not touch the key?
5. Does a sync from a second local client or a concurrent Air+ app session invalidate the key or the observation
   of the first? (openHAB and Homey sync before every command, which sidesteps the question for commands.)
6. What is behind the Observe sequence number advancing while no local client receives anything (AC2220: 41 -> 96
   in 12.5 min)? Pushes to the cloud?
7. Is the openHAB MID workaround needed (does the device drop a request whose MID collides with its own recent
   MIDs)?
8. How long can an AC3220 in standby stay silent with `D03134` (standby sensors) on versus off?

---

## 8. Sources

Cloned repositories (paths under `scratchpad/src`): see section 1. Upstream URLs:
- https://github.com/iobroker-community-adapters/ioBroker.philips-air (commits 4590b1a, 830b868, 4b3daca)
- https://github.com/openhab/openhab-addons/tree/main/bundles/org.openhab.binding.philipsair (PR https://github.com/openhab/openhab-addons/pull/21901)
- https://github.com/biemond/com.athom.philipsair
- https://github.com/atdr/homebridge-philipsair-platform
- https://github.com/ruaan-deysel/homebridge-philips-airctrl
- https://github.com/chayuto/seeed-XIAO-ESP32-C6
- https://github.com/MaddogWarner/homebridge-philips-air-purifier-complete
- https://github.com/mfrister/phipsair , https://github.com/hemtjanst/klimat
- https://registry.npmjs.org/node-coap-client/-/node-coap-client-2.1.0.tgz (unpacked in `scratchpad/dl08`, read only)
- Round 1 forum copy used for one check: `scratchpad/forum/openhab/t170501_posts.json`
  (https://community.openhab.org/t/philips-air-binding-5-2-0-0-5-3-0-0/170501)

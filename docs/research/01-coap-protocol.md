# 01 - Philips air purifier local wire protocol (encrypted CoAP), from primary source code

Research date: 2026-11-22. Target device: Philips PureProtect 3200, AC3220/10.

Scope of this note: the LAN protocol as implemented in the open-source clients, the behaviour of each
client library, and device-side quirks that are documented in code, commits, changelogs and issue threads.

Paths are relative to `scratchpad/src` unless they start with `aiocoap-0.4.17/` (the aiocoap 0.4.17 sdist
I downloaded from PyPI and read, in `scratchpad/dl/aiocoap/`).

Evidence labels used throughout:

- **[V-code]** verified by me in source code (path:line given).
- **[V-run]** verified by me by running my own independent implementation (`scratchpad/scripts/verify_crypto.py`).
- **[V-commit]** verified in a commit message / diff in a cloned repo.
- **[Issue]** stated by a named person in a GitHub issue/PR that I read through WebFetch (summarised by a
  small model, so wording is paraphrased unless quoted from code). Treat as credible hearsay.
- **[Inferred]** my own inference. Not verified against a device. I had no device and no packet capture.

Nothing in this note was tested against a real AC3220.

---

## 0. Executive summary

1. The device is a plain CoAP server on **UDP 5683**. There is no DTLS, no pairing and no credential.
   Three resources matter: `POST /sys/dev/sync`, `GET /sys/dev/status` (with Observe), `POST /sys/dev/control`.
   A fourth, `GET /sys/dev/info`, is plaintext and answers quickly.
2. "Encryption" is application-layer: AES-128-CBC with key and IV both derived from
   `MD5("JiangPan" + counter)`, where the counter travels in clear text at the start of every message.
   Anybody on the LAN can read and forge messages. It is obfuscation, not security.
3. Status is delivered by CoAP Observe. Every library sends **NON** requests. aiocoap has **no timeout
   for NON requests**, so every call can hang forever unless the caller wraps it in a timeout.
4. The three async libraries are one code lineage (betaboon -> kongo09 fork -> philips-airctrl fork).
   They differ in lifecycle handling, not in protocol.
5. The dominant reliability problems are device-side and firmware-dependent:
   - many firmwares **do not answer the Observe GET until the next state change** ("push on change");
   - at least one firmware **stops notifying about 150 s after registration** unless re-registered;
   - several firmwares **serve only the newest observer per client IP**;
   - notifications reuse/ignore CoAP message IDs;
   - about 1 in 1,800-5,300 notifications is corrupted by the firmware itself (NUL bytes, valid digest);
   - sync replies are occasionally malformed;
   - closing/reopening sessions too often has been reported to wedge the device's network stack.
   The libraries each handle a different subset of these, and the two fixes that exist (watchdog
   reconnect, Max-Age renewal) each make things worse on firmware of the other kind.
6. For the AC3220/10 specifically I found exactly one primary data point: a status dump from Nov 2024
   (firmware `0.1.9`, `WifiVersion: AWS_Philips_AIR_Combo@3.0`). Its status message is about 1.9 kB on
   the wire, which is larger than one Ethernet MTU. Which of the firmware behaviours in (5) the AC3220
   shows is **unknown** and is the first thing to measure.

---

## 1. Transport

| Item | Value | Evidence |
|---|---|---|
| Protocol | CoAP (RFC 7252) over UDP, unsecured (`coap://`) | [V-code] `betaboon_aioairctrl/aioairctrl/coap/client.py:51` `uri=f"coap://{self.host}:{self.port}{self.SYNC_PATH}"` |
| Port | 5683 (default arg in every client) | [V-code] `betaboon_aioairctrl/aioairctrl/coap/client.py:24`, `kongo09_aioairctrl/aioairctrl/coap/client.py:27`, `tinkerologie_philips-airctrl/src/philips_airctrl/coap/client.py:48`, `rgerganov_py-air-control/pyairctrl/coap_client.py:77` |
| Request message type (async libs) | **NON** for every request (sync, status GET, control POST, info GET) | [V-code] betaboon `client.py:50,63,85,116` (`mtype=NON`); kongo09 `client.py:79,93,123,168`; philips-airctrl `client.py:143,175,257,374,411` (`transport_tuning=Unreliable`) |
| Request message type (others) | py-air-control (CoAPthon3) and the openHAB binding (Californium) use **CON** for POSTs and the Observe GET | [V-code] `marcelrv_openhab-addons_philipsair/.../connection/PhilipsAirCoapAPIConnection.java:147` `request.setType(Type.CON)`; [Issue] py-air-control #58 log `CON-56159, POST` |
| Notification message type | NON reported in aiocoap debug logs for an AC2729/10 | [Issue] tinkerologie/ha-philips-airpurifier #172 (fwolf222, 2026-11-18). Not verified for AC3220 |
| Token | chosen by the CoAP library. aiocoap: counter with random 16-bit start, big-endian, leading zero bytes stripped (so normally 1-2 bytes) | [V-code] `aiocoap-0.4.17/aiocoap/tokenmanager.py:18,63-67`. A capture in philips-airctrl #44 shows token `05ae` |
| Message ID (client) | aiocoap: random 16-bit start, +1 per message | [V-code] `aiocoap-0.4.17/aiocoap/messagemanager.py:41,530-534` |
| Message ID (device) | **Not trustworthy.** "several Philips models keep sending MID=1 on every observation message" | [Issue] betaboon, betaboon/aioairctrl #3, 2021-04-24. Consistent with the dedup monkeypatch [V-code] and with openHAB's `NO_DEDUPLICATOR` [V-code] `PhilipsAirCoapAPIConnection.java:94` |
| Block-wise (RFC 7959) | No client sets Block options. No evidence the device uses Block2. Evidence it sends one big datagram: CoAPthon3's 1152-byte `recvfrom` truncated Philips answers and 1500 fixed it | [Issue] Tanganelli/CoAPthon3 #29; py-air-control #35 ("only there if your device sends messages bigger than 1152 bytes") |
| Datagram size | Status payload is 1448-2280 ASCII chars in captured examples (see 4.5). For AC3220 I compute ~1864 chars -> ~1.9 kB UDP payload -> **IP fragmentation on a 1500-byte MTU** | [V-run] sizes of vectors; [Inferred] for AC3220 from the status JSON in kongo09/philips-airpurifier-coap #181 |
| Multicast / discovery | None in the three Python libs. The openHAB binding discovers by sending a NON `GET /sys/dev/info` to `224.0.1.187:5683` (CoAP all-nodes) and to each subnet broadcast address | [V-code] `.../discovery/PhilipsAirCoapDiscovery.java:74-76,178-193,231-246` |
| CoAP ping | Device answers an empty CON (code 0.00) with RST in < 0.1 s, even when quiet | [Issue] mbreitkreuz, kongo09/philips-airpurifier-coap #396 (2 of 2 tests, AMF870). The openHAB binding calls `client.ping()` before (re)registering [V-code] `PhilipsAirCoapAPIConnection.java:126,157` |

aiocoap transport selection matters operationally:

- Default client transport on Linux is `udp6` (one dual-stack `AF_INET6` socket for all peers)
  [V-code] `aiocoap-0.4.17/aiocoap/defaults.py:69-79`. It fails on hosts without IPv6.
  kongo09 therefore pins `transports=["simple6"]` (one connected UDP socket per peer, address family
  chosen by the OS) [V-code] `kongo09_aioairctrl/aioairctrl/coap/client.py:48`; reason in the integration
  history: "Set AIOCOAP to use simple6 transport by default to support IPv4-only hosts, see
  .../issues/256" [V-commit] `kongo09_philips-airpurifier-coap` 36b186e (removed text) and 3eb702e.
- philips-airctrl uses the aiocoap default list (`Context.create_client_context()` with no arguments)
  [V-code] `tinkerologie_philips-airctrl/src/philips_airctrl/coap/client.py:60`.
- Each `Client.create()` builds a new aiocoap `Context`, i.e. a **new UDP source port**. Every
  "reconnect" therefore looks like a new client endpoint to the device.

---

## 2. Resources

All paths are identical in all four clients
([V-code] betaboon `client.py:20-22`; philips-airctrl `client.py:43-46`; py-air-control
`coap_client.py:95,143,165`; openHAB `PhilipsAirCoapAPIConnection.java:60-62`).

| Resource | Method | Request payload | Response payload | Encrypted? |
|---|---|---|---|---|
| `/sys/dev/sync` | POST | 8 ASCII chars: 4 random bytes as upper-case hex (client nonce) | 8 ASCII hex chars: the session counter ("client key") | No, both plaintext |
| `/sys/dev/status` | GET + `Observe: 0` | none | encrypted envelope (section 4) containing `{"state":{"reported":{...},"desired":null}}` | Response only |
| `/sys/dev/control` | POST | encrypted envelope containing `{"state":{"desired":{...}}}` | plaintext JSON `{"status":"success"}` or `{"status":"failed"}` | Request only |
| `/sys/dev/info` | GET (no Observe) | none | plaintext JSON, e.g. `{"modelid":..., "name":..., "device_id":..., "type":..., "swversion":..., "product_id":...}` | No |

Notes:

- `/sys/dev/info` is not in betaboon or kongo09. It is in philips-airctrl
  (`get_device_info()`, [V-code] `client.py:393-422`, added in 1.2.0 [V-commit] cc013a0), in the phipsair
  fork ([V-code] `mfrister_phipsair/phipsair/coap/client.py:61-73`) and in openHAB discovery. Field names
  come from openHAB's DTO ([V-code] `.../model/PhilipsAirPurifierDeviceDTO.java:26-38`) and its discovery
  filter `payload.contains("product_id")` (`PhilipsAirCoapDiscovery.java:114`).
  phipsair changelog: "the purifier seems to respond quickly" on this endpoint; commit 79bc1eb: "It
  responds quickly far more reliably. The status endpoint sometimes needs half a minute to respond."
  [V-commit].
- The status resource is only ever requested **with** the Observe option. philips-airctrl docstring:
  "Philips devices only serve the status resource through the CoAP Observe mechanism, so the Observe
  option is always sent to elicit a response." [V-code] `client.py:155-157`. I found no evidence of a
  plain GET being answered.
- No client sends Content-Format or Accept options.

---

## 3. Sync handshake and the session counter

### 3.1 What the code does

```
client                                        device
  | NON POST /sys/dev/sync  payload="A1B2C3D4"   |    (8 hex chars = os.urandom(4).hex().upper())
  |--------------------------------------------->|
  |            2.xx  payload="2170B935"          |    (8 hex chars = counter C0)
  |<---------------------------------------------|
```

[V-code] betaboon `client.py:45-57`; kongo09 `client.py:69-86`; philips-airctrl `client.py:138-150`;
py-air-control `coap_client.py:93-100`.

- The client nonce is generated and then **never used again** by any client. The openHAB binding does
  not even send a random value: it sends its current counter, `String.format("%08X", currentCounter)`
  [V-code] `PhilipsAirCoapAPIConnection.java:317-321`. So the request payload appears to be irrelevant
  to the device. [Inferred]
- The response is stored verbatim as the counter string (`set_client_key`), with **no validation** in any
  of the three Python libraries ([V-code] e.g. philips-airctrl `client.py:148-150`,
  `encryption.py:29-30`).
- Before each encrypted **client -> device** message the counter is incremented by one and the new value
  is used both as the clear-text prefix and as key-derivation input:
  `C(n) = (C(n-1) + 1) mod 2^32`, formatted as 8 upper-case hex digits
  [V-code] kongo09 `encryption.py:35-42,57-66`; philips-airctrl `encryption.py:32-38,51-57`.
  The first control message after a sync therefore carries `C0 + 1`.
  py-air-control's test asserts exactly this: `int(control_resource.encoded_counter,16) == int(SYNC_KEY,16)+1`
  [V-code] `rgerganov_py-air-control/testing/test_coap.py:70-78`.
- **Device -> client** messages carry their own 8-char prefix. Clients simply take the key from the
  message itself and never compare it with their own counter
  [V-code] kongo09 `encryption.py:68-79`; test `test_decrypt_uses_key_embedded_in_payload`
  (`kongo09_aioairctrl/tests/test_encryption.py:35-42`). So there is no replay protection on the client
  side, and a status message can be decrypted with no prior sync at all (the test vectors decrypt in a
  fresh context, [V-run]).

### 3.2 What the device requires (evidence, not code)

- A control message without a valid synced id is rejected with `{"status":"failed"}`; "you need to sync
  an id when sending a message. The id is received via /dev/sync. The message send then needs to contain
  id + 1" [Issue] holomekc, py-air-control #35, 2020-04-24.
- Long-lived aioairctrl sessions send `C0+1, C0+2, ...` and work, so incrementing by one per command is
  accepted. Whether the device demands *exactly* previous+1 or only "greater than", and whether the
  counter is per client endpoint or one global value, is **not documented anywhere I could find**.
- The value returned by sync "changes on every call" [Issue] openHAB forum log (thread 170501 p.2).
- Wrap-around at `FFFFFFFF`: betaboon raises `OverflowError` (`to_bytes(4)` of 2^32)
  [V-code] `betaboon_aioairctrl/aioairctrl/coap/encryption.py:20-22`; kongo09 and philips-airctrl wrap to
  `00000000` [V-code] kongo09 `encryption.py:38-39`, philips-airctrl `encryption.py:35`. What the
  device does at wrap is unknown. With a random 32-bit start and a few commands per day it is practically
  unreachable.
- py-air-control formats the incremented counter with `"{:x}".format(...)`, i.e. **without zero padding**
  [V-code] `rgerganov_py-air-control/pyairctrl/coap_client.py:130-131`. A counter with a leading zero
  nibble produces a 7-char prefix and breaks the fixed-width envelope. Do not copy this.

### 3.3 Recovery when out of sync

The only recovery mechanism in any library is: a control POST that does not return
`{"status":"success"}` triggers a new `_sync()` and a retry (details per library in section 6).
Nothing re-syncs proactively, and nothing re-syncs after a device reboot until a command fails.

The openHAB binding takes the opposite approach and **syncs immediately before every command**
(`long controlCounter = getSync(counter); ... controlCounter++`,
[V-code] `PhilipsAirCoapAPIConnection.java:285-300`). In its forum log the sync and the control POST are
about 20 ms apart. That makes counter drift impossible by construction and costs one extra round trip
(sync answers in 10-200 ms per logs in ha-philips-airpurifier #172).

### 3.4 Malformed sync replies (device bug)

[Issue] mbreitkreuz in kongo09/aioairctrl PR #14 and tinkerologie/philips-airctrl #44 (AMF870,
`AWS_Philips_AIR_Combo@86`): 2 of 1,317 sync replies in eight days were NUL-padded, e.g. the key logged as
`31` followed by NULs, or `33\0\0\0\0\0\0`. `set_client_key` accepts it; notifications still decode
(they carry their own key) but every later command fails in `int(key, 16)` with `ValueError` until the
next sync. One such event cost 9 minutes of failed commands. No released library validates the reply.

---

## 4. Encryption

### 4.1 Algorithm (identical in all four implementations)

[V-code] betaboon `encryption.py:12,24-55`; kongo09 `encryption.py:26,44-79`; philips-airctrl
`encryption.py:24,40-69`; py-air-control `coap_client.py:75,102-140`; openHAB
`PhilipsAirCoapCipher.java:42-135`. [V-run] against two captured device messages.

```
SECRET   = "JiangPan"                                   (8 ASCII bytes, hard-coded in every client)
ctr      = 8 ASCII chars, upper-case hex of a 32-bit big-endian counter      e.g. "2170B936"
h        = UPPER(HEX(MD5(SECRET + ctr)))                (32 ASCII chars)
key      = ASCII bytes of h[0:16]                       (16 bytes -> AES-128; only chars 0-9A-F)
iv       = ASCII bytes of h[16:32]                      (16 bytes)
ct       = AES-128-CBC(key, iv, PKCS7(plaintext_utf8, block=16))
ct_hex   = UPPER(HEX(ct))
digest   = UPPER(HEX(SHA256(ASCII(ctr + ct_hex))))      (64 ASCII chars)
wire     = ctr + ct_hex + digest                        (all upper-case ASCII hex)
```

Envelope layout (ASCII characters, not bytes of binary):

| Offset | Length | Field |
|---|---|---|
| 0 | 8 | counter, clear text |
| 8 | 2 x padded_len | ciphertext as hex (padded_len is a multiple of 16) |
| end-64 | 64 | SHA-256 over the preceding characters, as hex |

Total length = `72 + 2 * (floor(len(plaintext)/16) + 1) * 16`.

Important details:

- The AES key and IV are the **ASCII encodings of hex digits**, not the raw MD5 bytes. Each key byte is
  one of 16 values, so the key has 64 bits of entropy at most. This is irrelevant in practice because the
  key is fully derivable from public data.
- The digest covers the ASCII string `ctr + ct_hex`. It is a plain hash with no secret. It detects
  transmission damage only.
- Comparison is on upper-case strings. py-air-control upper-cases the ciphertext before hashing
  (`coap_client.py:105`); the aioairctrl family does not. I found no evidence that devices send lower case.
- `decrypt()` order in the Python libs is: digest check -> `bytes.fromhex` -> AES -> PKCS7 unpad -> UTF-8
  decode -> (caller) `json.loads`. Possible exceptions: `DigestMismatchException/Error`, `ValueError`
  (non-hex, bad padding, bad UTF-8), `json.JSONDecodeError`, `KeyError` on `["state"]["reported"]`.

### 4.2 Annotated example (generated by my own implementation, [V-run])

Assume the device answered the sync with `2170B935` (the constant used by py-air-control's test server,
`testing/coap_resources.py:12`). First command: power on a NEW2-generation device.

```
sync response (C0)       : 2170B935
counter used (C0+1)      : 2170B936
MD5("JiangPan2170B936")  : 50FDCE74B843C4B1E455FE7020569AFD
AES-128 key (ASCII)      : "50FDCE74B843C4B1"   = 35 30 46 44 43 45 37 34 42 38 34 33 43 34 42 31
CBC IV (ASCII)           : "E455FE7020569AFD"   = 45 34 35 35 46 45 37 30 32 30 35 36 39 41 46 44
plaintext (92 bytes)     : {"state": {"desired": {"CommandType": "app", "DeviceId": "", "EnduserId": "", "D03102": 1}}}
wire payload (264 chars) :
  2170B936                                                          <- counter
  CA885F16EC7BA551F20A0A136F3E08EA1FB0ED216B20EC905DC6E7AD63D1D26C
  D113016815F1F7F9E8E00DF8CE48470FEC509556317F0E14EA998718FE7ED7E0
  4965D5DF744E36EEC13EDF100EF88117037C4BB2DB938FCAD60D08D7B20302CB  <- 96 bytes ciphertext as 192 hex chars
  01956520A5D1D4732053B2A531D330C0E27E68D2AFCE015F5C8F3A0214401383  <- SHA-256("2170B936" + ct_hex)
```

(The plaintext uses Python's default `json.dumps` separators `", "` / `": "`, exactly as all three Python
libraries send it: betaboon `client.py:111`, kongo09 `client.py:163`, philips-airctrl `client.py:367`.)

### 4.3 Real captured vectors

`kongo09_aioairctrl/tests/test_encryption.py:88-173` contains two full device messages with plaintext.
My independent decryptor reproduces both plaintexts byte for byte:

| Vector | Model | Counter prefix | Wire length | MD5("JiangPan"+ctr) |
|---|---|---|---|---|
| DEVICE_1 | AC0850/11, `AWS_Philips_AIR@91.1` | `F45D4729` | 1704 chars | `2F062947A0F0C3E4D902EEFEC1F47FF3` |
| DEVICE_2 | AC2729/10, `AWS_Philips_AIR@91.1` | `86ABD25E` | 1448 chars | `522CA02E6903CDCD71F0C50BB04979A6` |

### 4.4 Security assessment

Weak by design:

- Confidentiality: none against anyone who knows the constant `JiangPan` (public since 2020). The
  per-message key input is transmitted in clear.
- Authentication: none. No device secret, no pairing, no user identity. `DeviceId` and `EnduserId` are
  sent empty and accepted.
- Integrity: unkeyed hash. An on-path attacker can forge both directions.
- Replay: the counter gives the device some replay resistance for commands; clients have none.
- MD5-derived key material, IV fully determined by the counter.

Practical consequence: any host on the same L2/L3 segment can control the purifier, and any host can
disturb an existing client's session (see single-observer behaviour in 7.3). Network isolation is the
only protection.

### 4.5 Message sizes and the MTU

| Source | Wire payload | Padded plaintext |
|---|---|---|
| AC2729/10 vector | 1448 chars | 688 B |
| AC0850/11 vector | 1704 chars | 816 B |
| AMF870 capture (philips-airctrl #44) | 2280 chars | 1104 B |
| **AC3220/10** (status JSON from kongo09/philips-airpurifier-coap #181, compact) | **~1864 chars** [Inferred] | 896 B |

A 1500-byte MTU leaves 1472 bytes of UDP payload. Minus CoAP header, token and options, any envelope
above roughly 1450 chars cannot fit in one frame. With no evidence of Block2, the AC3220's status
notifications are very likely **IP-fragmented UDP datagrams** (two fragments each). [Inferred]
Consequences: a receive buffer of at least 4 kB is required (CoAPthon3's 1152 was the first bug people
hit); firewalls, VLAN routers and some Wi-Fi mesh links that drop or mishandle fragments would produce
exactly the symptom "sync and control work, status never arrives".

---

## 5. Status delivery (CoAP Observe)

### 5.1 Registration and notification format

```
client                                               device
  | NON GET /sys/dev/status   Observe: 0   token=T      |
  |---------------------------------------------------->|
  |   2.05  token=T  Observe: n  Max-Age: 60  payload=E |   (first response; may be delayed, see 7.1)
  |<----------------------------------------------------|
  |   2.05  token=T  Observe: n+1 ...                   |   (notification on every change)
  |<----------------------------------------------------|
```

[V-code] betaboon `client.py:74-93`; kongo09 `client.py:110-139`; philips-airctrl `client.py:248-345`.

- Decrypted payload: `{"state":{"reported":{...all datapoints...},"desired":null}}`
  ([V-run] both vectors end with `,"desired":null}}`). Clients return `["state"]["reported"]`.
- Every notification is a **full snapshot**, not a delta (both vectors and the #181 dump contain the full
  key set including identity fields).
- `reported.StatusType` is `"status"` normally and `"control"` right after a command
  [Issue] openHAB forum log. `reported.ConnectType` is `"Online"` in every sample.
- `reported.Runtime` is device uptime in ms; it resets on reboot (useful as a reboot detector)
  [Issue] kongo09/aioairctrl #6 observation; field description in
  [V-code] `tinkerologie_philips-airctrl/src/philips_airctrl/device_info.py:397-399`.
- `Max-Age` on the registration response is **60** in every log I found (AC4220 fw 0.2.3, AC2210,
  AC2729) [Issue] philips-airctrl #34, ha-philips-airpurifier #172. Libraries default to 60 when the
  option is absent [V-code] kongo09 `client.py:104-107`; philips-airctrl `client.py:26,198-212`.
- Observe option value: a large increasing integer, e.g. `Observe 103791` on an AMF870
  [Issue] kongo09/aioairctrl PR #14. aiocoap drops notifications it considers reordered (Observe value
  not newer and less than 128 s since the last accepted one)
  [V-code] `aiocoap-0.4.17/aiocoap/protocol.py:695-717`, `numbers/constants.py:142`. A device whose
  Observe value jumped backwards (for example after an internal restart that kept the observer) would
  be silently ignored for up to 128 s. No evidence this happens; noted as a trap for custom clients.

### 5.2 Notification cadence

- Device running: every 1-5 s while values change; 106 pushes in 270 s on an AC4220 (~25/min)
  [V-commit] philips-airctrl eff5951 PR text.
- Device off / standby: "updates usually only happen every 3 minutes, sometimes a bit more rarely"
  (AC2889, 2022) [V-code] comment in `mfrister_phipsair/phipsair/purifier.py:129-133`.
- Push-on-change firmware in standby: **nothing at all** until something changes
  [Issue] kongo09/philips-airpurifier-coap #396, ha-philips-airpurifier #172.

### 5.3 Observation lifetime and re-registration

This is where the libraries and the reports disagree, and where firmware differs.

| Library | Re-registers? | Cancels? |
|---|---|---|
| betaboon 0.2.1 | never | never |
| kongo09 0.3.1 | never | `observation.cancel()` in `finally` when the generator exits (`client.py:135-139`) |
| philips-airctrl >= 1.4.0 | every Max-Age seconds, new request (new token), same context, no new sync; old observation cancelled locally after the new one answered (`client.py:315-337`) | on every exit path, guarded against double cancel (`client.py:214-222,344-345`) |
| openHAB binding | `reuseObserve.reregister()` (Californium: same token) when no data for 60 s, preceded by a CoAP ping; `proactiveCancel()` after 6 attempts (`PhilipsAirCoapAPIConnection.java:123-135`) | yes, proactive (GET Observe:1) |

"Cancel" in aiocoap is **local only**. aiocoap does not send a deregistration GET (Observe: 1); the
code comment says "We don't really support cancellation of observations yet"
[V-code] `aiocoap-0.4.17/aiocoap/protocol.py:667-674`. After a local cancel the token is forgotten, a
later notification is logged at INFO as "Response ... could not be matched to any request"
(`tokenmanager.py:185`), and aiocoap answers with RST **only if the notification is CON**; a NON
notification is ignored ("Ignoring unknown response (which is not a unicast CON)",
`messagemanager.py:121-141`). If Philips notifications are NON (reported, see section 1), the device is
never told that an observer went away. It keeps sending until its own expiry or until replaced.

Device-side lifetime, as reported:

- AC4220/12 fw 0.2.3 (and AC2210 fw 0.2.3): notifications stop about **150 s** after a single
  registration, with no error, while the device still answers a fresh sync in ~100 ms. Two measured
  sessions ended at 2 m 42 s and 2 m 31 s. With renewal every ~60 s a 270 s run stayed alive
  (renewals at 63.6, 124.1, 184.7, 245.2 s) [Issue] philips-airctrl #34; [V-commit] eff5951.
- AC2210 fw 0.2.3, another owner: with renewal enabled 47% of 414 renewals got no answer within 10 s;
  his reading is that the device "keeps an established observation running fine, but often doesn't answer
  a new observe request" [Issue] Luke2105-Loft59, ha-philips-airpurifier #172, 2026-10-31.
- AC2889/10 (2023): `status-observe` stalls after 20-60 hours, restart fixes it
  [Issue] kongo09/aioairctrl #6 (closed wontfix, cause never found).
- AC2889 `@64.3` (2022): the phipsair client never re-registers, sends `GET /sys/dev/info` every 60 s as
  keep-alive and uses a 10-minute silence watchdog [V-code] `mfrister_phipsair/phipsair/purifier.py:134,264-284`.
  Its author gives NAT mapping timeouts as the motive, not observer expiry [V-commit] 4951896.

I cannot tell from source whether the ~150 s lapse is an observer timeout of about 2.5 x Max-Age,
whether any inbound packet from the client refreshes it, or whether it is specific to firmware 0.2.3.
**Open question; must be measured on the AC3220.**

### 5.4 Keep-alive options seen in the wild

| Mechanism | Used by | Cost / risk |
|---|---|---|
| Re-register Observe (new token) every Max-Age | philips-airctrl 1.4.0+ | On push-on-change firmware the GET is not answered until the next change; philips-airctrl treats 10 s of silence as fatal -> reconnect storm (7.1) |
| Re-register Observe (same token) | openHAB/Californium | Needs a CoAP stack that lets you reuse a token; aiocoap always assigns a new one (`tokenmanager.py:231`) |
| `GET /sys/dev/info` every 60 s | phipsair | Plaintext, fast, no side effects known |
| `POST /sys/dev/sync` as ping | openHAB (log: "answered the ping, counter 780786140") | Returns a new counter each time; safe only if you also sync before each command |
| Empty CON ping -> RST | proposed in kongo09 #396; openHAB `client.ping()` | Not available through aiocoap's public API; an unanswered CON inside aiocoap fails all pending requests to that peer on retransmit exhaustion [Issue] #396 |

### 5.5 What the device does when the observer goes silent

Unknown from source. No library documents device behaviour here. Observed fragments: notifications to a
cancelled token keep arriving for at least 28 s (7 pushes) after the client dropped it
[Issue] philips-airctrl #44 capture; the newest registration from an IP replaces older ones on some
firmware (7.3).

---

## 6. Control

### 6.1 Envelope

Plaintext before encryption (all three Python libs and py-air-control):

```json
{"state": {"desired": {"CommandType": "app", "DeviceId": "", "EnduserId": "", "<key>": <value>, ...}}}
```

[V-code] betaboon `client.py:101-110`; kongo09 `client.py:153-162`; philips-airctrl `client.py:357-366`;
py-air-control `coap_client.py:167-176`.

- Several keys can be set in one message (`set_control_values(data: dict)`).
- `DeviceId` and `EnduserId` are empty strings. openHAB sends `"EnduserId": "1"`
  (`PhilipsAirCoapAPIConnection.java:290-292`). "EnduserId seems to be irrelevant" [Issue] py-air-control #35.
- Value types follow the device generation: old devices use strings (`"pwr": "1"`), NEW2 devices such as
  the AC3220 use integers (`"D03102": 1`). The libraries pass values through unchanged; the CLI has an
  `-I/--int` switch.
- The old *plain* CoAP protocol used `{"state":{"desired":{key: value}}}` without the three extra fields
  and without encryption [V-code] `rgerganov_py-air-control/pyairctrl/plain_coap_client.py:74`. Not
  relevant for the AC3220 but it shows the family history.

### 6.2 Response and success signalling

- Response payload is **plaintext** JSON. Success test: `json.loads(payload).get("status") == "success"`
  [V-code] betaboon `client.py:122-124`. py-air-control compares the raw string
  `'{"status":"success"}'` (`coap_client.py:181`).
- Failure is `{"status":"failed"}` [Issue] py-air-control #35; [V-code] test server
  `testing/coap_resources.py:107-109`.
- A success response only means the device accepted the message. The new state arrives later as an
  Observe notification with `StatusType: "control"`. openHAB sleeps 1 s after a command "otherwise we
  won't get the new value" (`PhilipsAirCoapAPIConnection.java:304-306`).
- If the response is not JSON (empty payload, error response) the Python libs raise from `json.loads`;
  no library inspects the CoAP response code.
- Both HA integrations **discard the boolean** returned by `set_control_values`:
  kongo09 awaits it and then optimistically updates local state
  ([V-code] `kongo09_philips-airpurifier-coap/custom_components/philips_airpurifier_coap/philips.py:260-263`);
  tinkerologie wraps it in `wait_for(..., 30)` and ignores the result
  ([V-code] `tinkerologie_ha-philips-airpurifier/custom_components/philips_airpurifier/coordinator.py:221`).
  A command that returns `False` after all retries is therefore silent.

### 6.3 Retry semantics per library

| | betaboon 0.2.1 | kongo09 0.3.1 | philips-airctrl 1.5.1 |
|---|---|---|---|
| Code | `client.py:100-133` | `client.py:146-188` | `client.py:354-391` |
| Attempts | 1 + `retry_count` (5) = 6, recursive | 6, loop | 6, loop |
| Re-encrypt per attempt | yes (new counter each time) | yes (`encrypt` inside loop, line 166) | **no** - `encrypt` is called once at line 369, above the loop at 371 |
| Re-sync | after every failure | only after the first failure (line 178) | after every failure, including the last (lines 383-385) |
| Delay between attempts | none | none | 0.5 s (`RETRY_DELAY`, line 23) |
| Timeout | none | none | none |
| Result | `True` / `False` (annotated `None`) | `bool` | `bool | None` |

**Regression in philips-airctrl** [V-code][V-commit]: commit 844a15c (2026-02-13) converted the
recursive retry into a loop but left `payload_encrypted = self._encryption.encrypt(payload)` outside it.
After a failed attempt the library re-syncs (the device hands out a new counter) and then re-sends the
*identical* ciphertext carrying the *old* counter. If the first failure was a counter mismatch, all five
retries are futile and the call returns `False`; only the next, separately issued command succeeds. The
unit tests mock `encrypt` and do not catch it (`tests/test_client.py:606-648`). Whether the device really
rejects the stale counter is the open question from 3.2, but betaboon's original and kongo09's fork both
re-encrypt, which is the behaviour the protocol was reverse-engineered with.

---

## 7. Device-side quirks (documented)

### 7.1 "Push on change": the Observe GET is not answered until something changes

- py-air-control #93 (2021): after a silent Wi-Fi firmware update from `AWS_Philips_AIR@62.1` to `@64.3`,
  status requests timed out while control kept working. Setcover (2021-08-31): the purifier sends CoAP
  updates only when values change; "Looks like the FW update from Philips is indeed a bugfix and not a
  bug." Workarounds people found: long timeouts, opening the Philips app (forces a refresh), sending a
  control write to force a push. [Issue]
- ha-philips-airpurifier #172 (2026): AC2729/10 (`@91.1`): sync answered in ~10 ms, status GET unanswered
  until a 30 s timeout; successful replies arrived after a median 10.7 s (p90 24.9 s). CX5120/11 (`@86.1`):
  a status request succeeded only when a reported value changed inside its 30 s window. AMF870
  (`Combo@86`): never answers a read. [Issue]
- philips-airctrl #44 capture: the first packet on a new observe token arrived 2.25 s after the GET and
  was simply the device's next push. [Issue]
- Library/integration consequences [V-code]:
  - `get_status()` in every library can block for an unbounded time.
  - philips-airctrl's renewal gives up after `RENEWAL_TIMEOUT = 10 s` and raises `TimeoutError`
    (`client.py:29,328-330`), which ends the stream and makes the HA coordinator reconnect. Reported
    result on an AC2210: 107 outages / 12 h 26 min unavailable in 24 h on the release that introduced
    renewal, versus 14 outages on the previous one [Issue] #172.
  - The tinkerologie integration works around it per model with a "status nudge" (a control write that
    forces a push) and by renewing only every 1800 s on nudge models
    (`coordinator.py:41,418-425`, `client.py:155-232`). **AC3220 has no nudge entry**
    (`device_models.py:618-620,1025-1027`), i.e. it is treated as a device that answers reads.
    Whether that is true for current AC3220 firmware is unverified.

### 7.2 Notifications stop without renewal (some firmware)

See 5.3. AC4220/AC2210 fw 0.2.3: silent after ~150 s. This is the reason for philips-airctrl 1.4.0's
renewal, and it is the mechanism behind the kongo09 integration's periodic deafness on such firmware:
that integration registers once and relies on a watchdog of `3 x Max-Age = 180 s` of silence before a
full reconnect ([V-code] `kongo09_philips-airpurifier-coap/.../coordinator.py:18,42-49,134-141`).
~150 s of data followed by 180 s of stale data per cycle is consistent with the title of
kongo09/philips-airpurifier-coap #396, "Integration goes deaf for ~3 min".

7.1 and 7.2 pull in opposite directions: firmware of type 7.2 needs frequent re-registration; firmware
of type 7.1 punishes any client that waits for the re-registration to be answered.

### 7.3 One observer per client IP / single client

- phipsair: "Do NOT use multiple clients to connect from one machine to a single Air Purifier. Only one
  of the clients seems receive responses in this case." [V-code] `mfrister_phipsair/phipsair/purifier.py:115-116`
- "this firmware only answers the newest observe request from an IP"; "the newest observe GET wins. A CLI
  client on the HA host takes over notifications until the watchdog re-registers" [Issue] mbreitkreuz,
  #172 and #396 (AMF870).
- tinkerologie integration comment: "these firmwares appear to serve only one CoAP client, so a second
  connection would evict the observer" [V-code] `.../philips_airpurifier/client.py:171-175`.
- Older firmware did the opposite at least once: "the aircleaner ... answers to really old status
  requests" [Issue] Setcover, py-air-control #93.

Practical meaning: a second HACS integration, a CLI test, a discovery probe or a config-flow probe from
the same host silently steals the notification stream. betaboon/kongo09 `get_status()` itself registers
an observation that is never cancelled, so "status read then observe" already creates two registrations
from one endpoint.

### 7.4 Message IDs

Notifications with a constant MID (`MID=1`) on "several Philips models" [Issue] betaboon. Any CoAP
stack that de-duplicates *responses* by (peer, MID) discards them. aiocoap did so in 0.4.1; betaboon's
monkeypatch disabled deduplication globally ([V-code] `betaboon_aioairctrl/aioairctrl/coap/aiocoap_monkeypatch.py:8-16`).
aiocoap now de-duplicates requests only ([V-code] `aiocoap-0.4.17/aiocoap/messagemanager.py:94-108`;
kongo09 PR #9 dates the change to aiocoap 0.4.7 [Issue]), which is why both forks removed the patch
([V-commit] kongo09 bcc2a89, philips-airctrl 844a15c). The openHAB binding still sets
`DEDUPLICATOR = NO_DEDUPLICATOR` and even rewrites its request MID to follow the device's
(`PhilipsAirCoapAPIConnection.java:94,149-155`).

### 7.5 Firmware-corrupted notifications

- NUL bytes (usually one hex pair replaced by `\0\0`) inside the ciphertext hex, with a digest computed
  over the already-corrupted string and a valid UDP checksum, i.e. produced by the device.
  Rates: 9 of 16,245 pushes (1 in ~1,800) in a 48 h log; 16 of 85,122 (1 in ~5,300) in a 10-day capture;
  AMF870 `Combo@86`. Also seen on an AC0850. [Issue] philips-airctrl #44, kongo09/aioairctrl PR #14.
- Effect in betaboon/kongo09: `bytes.fromhex` raises `ValueError`, the generator ends, kongo09's
  `finally` cancels the observation, the HA task dies without a log line and entities freeze until the
  180 s watchdog (median 174 s of silence per event) [Issue] PR #14 comments.
- Fixed only in philips-airctrl 1.5.1 (`_read_observed_status`, [V-code] `client.py:230-246`;
  [V-commit] 222bc5b). kongo09 PR #14 is still open.
- The tinkerologie integration clone I read pins `philips-airctrl==1.5.0`
  ([V-code] `.../philips_airpurifier/manifest.json`, version 2026.11.1), i.e. without this fix.

### 7.6 Device wedges under session churn (older reports)

- AC3829/10, 2020: polling every 2 minutes worked for under an hour; then the device stopped responding,
  the official app stopped too, and only a power cycle recovered it [Issue] inwaar, py-air-control #58.
- roldoe, same thread, 2021: with Observe set on every poll the device queues pushes per subscriber;
  "Closing the connection restarts the handshake. Doing this often seemed to crash the device's network
  stack" [Issue].
- CX5120 fw 0.4.9, 2026: a reconnect plus nudge every minute, "the CX5120 CoAP stack stalled after a few
  dozen rounds" [V-code] comment at `tinkerologie_ha-philips-airpurifier/.../coordinator.py:418-423`.
- kongo09 README: "Due to a bug in the Philips devices, this integration is rather instable ... Sometimes,
  a power cycle of the Philips device helps." [V-code] `kongo09_philips-airpurifier-coap/README.md:20`

Reconnecting (new socket + sync + new observation) is therefore not a free recovery action.

### 7.7 Cloud / app interaction

- During an HA outage the purifier was still controllable from the Air+ app [Issue] #172. The app uses
  the cloud path, not local CoAP.
- Opening the (older) Clean Home+ app made hung local status queries return [Issue] dfrommi,
  py-air-control #93 - consistent with "app triggers a state change/push".
- kongo09, 2022: captures showed the device sometimes stopped sending CoAP while still talking to AWS
  [Issue] py-air-control #93.
- kongo09 README: "Some of these models seem to have a newer firmware that does not allow local
  connections anymore" (`README.md:62`). No protocol-level evidence for a closed port in anything I read;
  the py-air-control #93 thread ends with firmware `91.1` working again.

### 7.8 Network-layer effect that looks like a protocol fault

[Issue] mbreitkreuz, kongo09 #396 (50 h capture, AMF870 on UniFi): 32 of 403 reconnect syncs got no
reply, and 31 of those "never left the HA host": the kernel had no ARP entry, the device (Wi-Fi power
save) missed the broadcast ARP requests, and the NON datagram was dropped locally. Unicast ARP was
answered 99.7% of the time, broadcast ARP 61%. Because NON requests have no timeout and no retransmit,
each lost sync cost a full 180 s watchdog cycle. Short timeouts with 2-3 quick retries and regular
traffic (which keeps the ARP entry fresh) address this.

---

## 8. Timing behaviour hard-coded in each library

### 8.1 aiocoap baseline (applies to all three async libraries)

| Fact | Evidence |
|---|---|
| NON requests: sent once, never retransmitted, **no response timeout**. `# FIXME: Implement timing out with REQUEST_TIMEOUT here` | [V-code] `aiocoap-0.4.17/aiocoap/protocol.py:566-567` |
| CON would retransmit: ACK_TIMEOUT 2 s x random 1-1.5, doubling, MAX_RETRANSMIT 4 (give up after 45-93 s) | `numbers/constants.py:55-63,85-99` |
| EXCHANGE_LIFETIME 247 s (request dedup window) | `numbers/constants.py:117-121` |
| OBSERVATION_RESET_TIME 128 s | `numbers/constants.py:142` |
| Context shutdown waits up to 3 s | `numbers/constants.py:184`, `protocol.py:423-455` |
| `ClientObservation.cancel()` asserts if called twice; `error()` cancels internally | `protocol.py:1181-1217` |
| A second `Context.shutdown()` raises `AttributeError` | [V-commit] philips-airctrl 6192640 |
| ICMP errors on the socket surface as `NetworkError` on pending requests and observations | `transports/simple6.py:156-157`, `transports/udp6.py:583-618` |

### 8.2 Library constants

| | betaboon 0.2.1 (2021-03) | kongo09 0.3.1 (2026-03-01) | philips-airctrl 1.5.1 (2026-11-16) | py-air-control 2.3.0 (2021-08) |
|---|---|---|---|---|
| CoAP stack | aiocoap ==0.4.1 | aiocoap >=0.4.17,<0.5, `simple6` | aiocoap >=0.4.11, default transports | CoAPthon3 (threads) |
| Python | not declared | >=3.12 | >=3.11 | >=3.4 |
| Sync timeout | none | none | none | 30 s default (`timeout` arg; was 5 s, was none) |
| Status read timeout | none | none | none | 30 s (was 2 s) |
| First observe response timeout | none | none | none | n/a |
| Observe renewal | no | no | every Max-Age (default 60 s) or `renew_interval`; `RENEWAL_TIMEOUT` 10 s | n/a |
| Control timeout | none | none | none | 30 s |
| Control retries | 5, resync each | 5, resync once | 5, resync each, 0.5 s apart, stale ciphertext | none |
| Unreadable notification | ends stream | ends stream | skipped with warning (1.5.1) | prints "Message from device got corrupted" |
| Context cleanup on failed `create()` | no | yes, incl. cancellation (`client.py:50-56`) | **no** (`client.py:59-63`) | `client.stop()` |
| Idempotent `shutdown()` | no | no | yes (1.5.0) | n/a |
| One-shot status without lingering observe | no | no | `get_status(observe=False)` (1.1.0) | `cancel_observing(response, True)` in `__del__` |
| `/sys/dev/info` | no | no | yes (1.2.0), `create(sync=False)` | no |
| Discovery | no | no | brute-force subnet scan: sync + status against every host, 20 parallel, 5 s each (`discovery.py:21,55-108,134`) | SSDP for HTTP devices only |

Integration-level timers that sit on top (for context; other notes cover the integrations):

- kongo09 integration: watchdog `Timer(60 x 3)` -> `_reconnect()`; `CoAPClient.create(self.host)` in the
  reconnect path has **no timeout** (`coordinator.py:76-91`); setup uses `wait_for(create, 25)`
  (`__init__.py:148`); config flow 30 s.
- tinkerologie integration: `COAP_CALL_TIMEOUT 30`, `SHUTDOWN_TIMEOUT 10`, reconnect back-off 5 -> 60 s,
  `RECONNECT_TASK_MAX 120`, watchdog `Max-Age x missed_count` (default 3), nudge watchdog 1800 s
  (`coordinator.py:28-59`); nudge helper 2 s register delay, 5 s write timeout, 12 s wait, 2 attempts
  (`client.py:17-22`).
- phipsair `PersistentClient`: connect timeout 10 s, retry after 10 s, info keep-alive every 60 s with
  10 s timeout, status watchdog 10 min, serialized command queue (`purifier.py:134,189-195,265-284`).
- openHAB binding: ACK_TIMEOUT 20 s, EXCHANGE_LIFETIME 65 s, client timeout 25 s, data considered stale
  after 60 s, ping + re-register up to 6 times, then cancel and start over
  (`PhilipsAirCoapAPIConnection.java:64-67,94-96,123-135`).

### 8.3 Failure scenarios

| Scenario | betaboon | kongo09 lib | philips-airctrl |
|---|---|---|---|
| Notification lost (UDP) | Unnoticed; next notification is a full snapshot | same | same; renewal response also resupplies state |
| Device silent but alive (no changes) | Stream idle forever; indistinguishable from dead | same | Renewal GET every 60 s; if unanswered in 10 s -> `TimeoutError`, stream ends |
| Device stops notifying (7.2) | Stream idle forever | same | Fixed by renewal |
| Request or response datagram lost | `await` never returns | same | same, except renewal (10 s) |
| Device reboot | Observation and counter are gone on the device; client sees nothing. Possibly `NetworkError` if an ICMP port-unreachable arrives while it is down. First command afterwards fails and triggers resync | same | Renewal re-registers within 60 s (or times out); command path has the stale-ciphertext bug |
| Wi-Fi drop / reconnect of the device | as reboot if the device lost state, otherwise transparent | same | same |
| Device IP change | Host is fixed at construction; no handling | same | same (integrations update host via DHCP discovery) |
| Corrupted notification | Exception ends generator | Exception ends generator, `finally` cancels | Skipped |
| Observation ended by aiocoap error | propagates | `finally` calls `cancel()` again -> `AssertionError` hides the real error ([V-code] `client.py:135-139` vs aiocoap `protocol.py:1181-1207`) | guarded |
| Sync reply malformed | accepted; later `ValueError` in `int(key,16)` | same (raises `ValueError` from `_increment_client_key`) | same |
| `create()` times out in caller | context leaked | context shut down | context leaked |

---

## 9. History: what each library changed and why

Lineage: rgerganov/py-air-control (HTTP 2018; plain CoAP and "firmware 1.0.7" encrypted CoAP added
2020-05 by Harald Heigl, commits b9bcbf7, f027a54) -> betaboon wrote an asyncio/aiocoap client inside
his HA integration (2020-12-19, cc2c190), moved it to betaboon/aioairctrl (2020-12-28) -> kongo09 forked
(2021-12) -> ruaan-deysel forked kongo09 0.2.5 as philips-airctrl (2025-06-09), now tinkerologie.
mfrister/phipsair is a 2022 side fork of betaboon.

### 9.1 py-air-control (reference, synchronous)

| Commit | Date | What it fixed |
|---|---|---|
| b9bcbf7 | 2020-05-05 | First encrypted client ("coapversion for sw-version 1.0.7"): sync, `JiangPan` KDF, decrypt |
| f027a54 | 2020-05-08 | "fixed client_key": keep the sync reply as a running counter, increment per command |
| 121be67 | 2020-06-03 | README: install CoAPthon3 fix for truncated answers (1152-byte receive buffer) |
| da12c0d | 2020-09-28 | 5 s timeout on sync (issue #60: unreachable device hung forever) |
| 2c21f19, cf53716 | 2021-04-25/26 | Cancel the observation created by each status read (issue #58: device stops responding) |
| e5b8930 | 2021-08-12 | Timeout configurable, default 30 s (issue #93: devices answer slowly/only on change) |

### 9.2 betaboon/aioairctrl (8 commits, last 2021-03-17)

| Commit | What |
|---|---|
| dadb80f (in the integration repo, 2020-12-26) | "make observation NON" - no rationale given |
| bf6a492 | `observe_status`: consume the first response before iterating notifications |
| 30b85b8, c97640b | Monkeypatch aiocoap: disable MID de-duplication (device sends `MID=1`), silence `CancelledError` in the observation iterator finalizer |

Known gap stated by the author (2021-04-24): "does not yet reconnect when the device is powered down
while an observation is running" [Issue] betaboon/aioairctrl #3.

### 9.3 kongo09/aioairctrl (52 commits; 0.2.1 2022-05 ... 0.3.1 2026-03-01)

| Commit | Date | What / why |
|---|---|---|
| 2cc196d, 6e40a06, dcbc9ae | 2022-05 | `get_status()` returns `(status, max_age)` so the integration can size its watchdog (PR #1 "max age" by mhetzi, PR #2 "Timeout") |
| d53bb74, dff1cc0 | 2022-12, 2024-01 | aiocoap bumps (0.4.5, 0.4.7) |
| 8fce00c, c8f197e, 341004d | 2026-02-21 ... 03-01 | Shut down the aiocoap context when the initial sync fails or is cancelled (integration issue #323 "opened sockets are not closed when client is not reachable") |
| bcc2a89 | 2026-03-01 | Remove the monkeypatch (obsolete with aiocoap >= 0.4.17) |
| 341004d | 2026-03-01 | Counter wrap; iterative retry with a single resync; cancel observation in `finally`; type guards |
| 5f3bd0b | 2026-03-01 | Tests with two real device vectors |
| 8866718 | 2026-03-01 | `transports=["simple6"]` per context instead of a process-wide env var (IPv4-only hosts; integration issue #322) |

Open, unmerged: PR #13 "add timeout for observe_status" (exit when silent for `max_age + 30 s`; "can hang
when the purifier restarts, for example during filter cleaning"), PR #14 "drop unreadable status
notifications". Issue #6 (stalls after 20-60 h) closed wontfix.

### 9.4 tinkerologie/philips-airctrl (79 commits; 1.0.0 2026-02-13 ... 1.5.1 2026-11-16)

| Version / commit | Date | What / why |
|---|---|---|
| 0.3.0 (916e1b1) | 2025-06-09 | Fork + discovery, device report, wizard; counter wrap |
| 1.0.0 (844a15c) | 2026-02-13 | Remove monkeypatch, `transport_tuning=Unreliable`, async context manager, iterative retry with 0.5 s delay (**introduces the stale-ciphertext retry**) |
| 1.1.0 (be1c615) | 2026-05-29 | `get_status(observe=False)`: cancel the one-shot observation, "devices that have a limited number of observer slots" |
| 1.2.0 (cc013a0) | 2026-07-02 | `/sys/dev/info`, `create(sync=False)` for firmware that never answers a status read (CX7550 `AWS_Philips_AIR_Combo`) |
| 1.3.0 | 2026-10-19 | Typing, `ClientNotInitialisedError` |
| 1.4.0 (eff5951) | 2026-10-28 | Observe renewal every Max-Age; cancel guard (#34) |
| 1.5.0 (6192640) | 2026-11-12 | Idempotent, concurrency-safe `shutdown()` (#36) |
| 1.5.1 (222bc5b) | 2026-11-16 | Skip undecryptable 2.xx statuses (#44) |

### 9.5 Which is the most robust basis, and what is still missing

philips-airctrl 1.5.1 has the most defensive code: renewal, unreadable-push skipping, safe shutdown,
one-shot reads, the plaintext info endpoint. kongo09 0.3.1 is smaller and has two things philips-airctrl
lacks: context cleanup on a failed `create()` and correct re-encryption on retry.

Missing in **all** of them:

1. Timeouts on sync, status read, first observe response and control. Every caller must add its own.
2. Validation of the sync reply (exactly 8 hex chars).
3. A liveness signal that is independent of status traffic (info GET or CoAP ping).
4. Renewal that does not treat an unanswered re-registration as a dead link.
5. Sync-before-command (or any proactive resync after reconnect/reboot detection).
6. Real observation deregistration towards the device (GET Observe:1 or RST).
7. Serialisation of commands (the counter is shared mutable state; concurrent `set_control_values`
   calls interleave `encrypt` and `await`).
8. A multicast/broadcast discovery (`GET /sys/dev/info` to 224.0.1.187) instead of sync-probing every host.
9. Any test against a simulated device; all client tests mock aiocoap.

---

## 10. Design implications for a new integration

1. **Bound every await.** Sync, info and control answer in 10-200 ms when the device is healthy; use
   3-5 s timeouts with 2-3 immediate retries (a lost NON never arrives late). Never bound the *status*
   GET the same way.
2. **Separate liveness from data.** Decide "available" from a cheap probe (`GET /sys/dev/info`, or an
   empty CON ping answered by RST) every 30-60 s. A quiet status stream is normal on push-on-change
   firmware and in standby.
3. **One long-lived socket, one observer.** Keep a single UDP endpoint per device for the life of the
   config entry. Do not open temporary clients for probing while the main one is running. Treat a full
   reconnect as a last resort with back-off (7.6).
4. **Re-register without tearing down.** Send the Observe GET again every ~60 s (or less than the
   measured lapse), keep accepting notifications on the previous token until the new one has produced
   data, and never raise because the GET was not answered.
5. **Sync right before each command** (or at least after any reconnect and after `Runtime` goes
   backwards), validate the reply with `^[0-9A-F]{8}$`, re-encrypt on every retry, serialise commands
   with a lock, and surface `{"status":"failed"}` as an error to Home Assistant. Confirm the change from
   the following `StatusType: "control"` push instead of optimistic state.
6. **Tolerate bad frames.** Skip (log once) any notification that fails digest/hex/padding/UTF-8/JSON.
   Do not de-duplicate responses by MID. Do not rely on Observe sequence numbers for ordering.
7. **Receive buffer >= 4 kB** and document that fragmented UDP must pass between HA and the device
   (same L2 segment is safest; guest-network/client isolation breaks it).
8. **Consider a purpose-built minimal CoAP layer.** The needed subset is small (4-byte header, token,
   Uri-Path, Observe, Max-Age; NON GET/POST; ACK incoming CON; empty CON ping; no block-wise, no DTLS).
   It gives control over tokens, re-registration, deregistration, timeouts and the receive path, none of
   which aiocoap exposes, and avoids aiocoap's per-context transport pitfalls (`udp6` vs `simple6`).
   The trade-off is owning that code and its tests.
9. **Build a device simulator first** (sync/status/control/info, NON pushes with fixed MID, delayed first
   response, 150 s lapse, single-observer eviction, NUL corruption, malformed sync). Every quirk in
   section 7 is then a regression test.
10. **Measure the AC3220 before fixing the design** (see open questions): one `tcpdump -n udp port 5683`
    of a sync + observe for 10 minutes, device on and in standby, answers most of them.

---

## 11. Open questions (not resolvable from source)

1. AC3220/10 on current firmware: is the Observe GET answered immediately or only on the next change?
2. Does the AC3220 stop notifying ~150 s after registration without renewal? Does any inbound packet
   (info GET, ping) keep the observation alive, or only a new Observe GET?
3. Observer model: one per IP, one per IP:port, or several? Does a new token from the same endpoint
   replace or add?
4. Counter semantics on the device: strictly previous+1 or any larger value; per endpoint or global;
   does a second client's sync invalidate the first client's counter? What is the relation between the
   counter in device-originated messages and the sync value?
5. Are notifications NON or CON on the AC3220, and is the device's MID constant?
6. Does the device use Block2 for large payloads, or IP fragmentation (my inference)?
7. Does the device honour a proper deregistration (GET with Observe: 1) or an RST?
8. Why did betaboon switch all requests to NON, and does the device handle CON requests (ACK,
   separate response) sanely on current firmware? CON would give retransmission and a natural timeout.
9. Does multicast/broadcast `GET /sys/dev/info` work on the AC3220 (openHAB relies on it for other models)?
10. Current AC3220 firmware / `WifiVersion` (the only sample is `0.1.9` / `AWS_Philips_AIR_Combo@3.0`
    from Nov 2024), and whether newer builds restrict local CoAP.

---

## 12. Sources

Cloned repositories (read, not executed):

- `betaboon_aioairctrl` - https://github.com/betaboon/aioairctrl (HEAD c97640b, 2021-03-17)
- `kongo09_aioairctrl` - https://github.com/kongo09/aioairctrl (HEAD cc28046, tag v0.3.1, 2026-03-01)
- `tinkerologie_philips-airctrl` - https://github.com/tinkerologie/philips-airctrl (HEAD b28ee4a, v1.5.1; full history fetched)
- `rgerganov_py-air-control` - https://github.com/rgerganov/py-air-control (HEAD e548496; full history fetched)
- `mfrister_phipsair` - https://github.com/mfrister/phipsair (HEAD 2e0bb43, 0.5.0) - cloned by me
- `marcelrv_openhab-addons_philipsair` - https://github.com/marcelrv/openhab-addons branch `philipsair-52` (HEAD 32d2df5, 2026-09-26), sparse checkout of `bundles/org.openhab.binding.philipsair` - cloned by me
- `kongo09_philips-airpurifier-coap`, `tinkerologie_ha-philips-airpurifier` - only the files cited
- aiocoap 0.4.17 sdist - https://files.pythonhosted.org/packages/1d/7c/10483df04d7910e21d55d47ab7c014fb02644b5b58ba741161360f8e9e8d/aiocoap-0.4.17.tar.gz

PyPI metadata: https://pypi.org/pypi/aioairctrl/json (latest 0.3.1), https://pypi.org/pypi/philips-airctrl/json (latest 1.5.1), https://pypi.org/pypi/aiocoap/json (latest 0.4.17, 2025-11-05).

Issue / PR pages read through WebFetch:

- https://github.com/tinkerologie/philips-airctrl/issues/34
- https://github.com/tinkerologie/philips-airctrl/issues/44
- https://github.com/kongo09/aioairctrl/pull/14
- https://github.com/kongo09/aioairctrl/pull/13
- https://github.com/kongo09/aioairctrl/pull/12
- https://github.com/kongo09/aioairctrl/pull/9
- https://github.com/kongo09/aioairctrl/issues/6
- https://github.com/kongo09/aioairctrl/pulls?q=is%3Apr and /issues?q=is%3Aissue
- https://github.com/betaboon/aioairctrl/issues/3
- https://github.com/betaboon/aioairctrl/pull/2
- https://github.com/rgerganov/py-air-control/issues/35
- https://github.com/rgerganov/py-air-control/issues/58
- https://github.com/rgerganov/py-air-control/issues/60
- https://github.com/rgerganov/py-air-control/issues/93
- https://github.com/Tanganelli/CoAPthon3/issues/29
- https://github.com/kongo09/philips-airpurifier-coap/issues/396
- https://github.com/kongo09/philips-airpurifier-coap/issues/181 (AC3220/10 status dump)
- https://github.com/tinkerologie/ha-philips-airpurifier/issues/172
- https://community.openhab.org/t/philips-air-binding-5-2-0-0-6-0-0-0/170501 (pages 1-2)
- https://community.home-assistant.io/raw/53030/457 ... /466

My own scripts: `scratchpad/scripts/verify_crypto.py` (independent crypto check against the two
vectors, example generator), `scratchpad/scripts/size_ac3220.py` (wire-size estimate).

Limitations: `api.github.com` and raw `github.com` HTML via curl were blocked, so issue content came
through WebFetch summaries and is paraphrased. I could not read diffs of unmerged PRs. No device, no
packet capture.

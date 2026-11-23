# 07 - Hardware, firmware and network footprint of the AC3220 family (discovery and keeping local control alive)

Round 2 note, written 2026-11-22. Builds on notes 01-06 (round 1) and overlaps slightly with 09 (capabilities) and 11 (firmware-claim verification); where those already hold the evidence I only point to them.

Evidence labels

| Label | Meaning |
|---|---|
| [V-code] | Read in a cloned repository. Paths are relative to `scratchpad/src`. |
| [V-doc] | Read in an official document saved locally (manual, IEEE registry, FCC page). |
| [V-forum] | Verbatim text from a forum copy saved in `scratchpad/forum` (Discourse raw/JSON), so quotes are exact. |
| [V-raw] | Fetched today with curl from raw.githubusercontent.com, saved in `scratchpad/dl07`. Exact text. |
| [WF] | GitHub issue or web page read through WebFetch (a small model summarises; only the short quoted strings are reliable). |
| [I] | My inference. |
| [H] | Hearsay or a claim by a third party that I could not check. |
| [NF] | Looked for, not found. |

Nothing in this note was tested against a real AC3220. No unit of the user's was probed.

---

## 0. Short answers

1. **Wi-Fi module.** The 2024+ "Combo" generation uses the **MXCHIP EMC6069-P** (2.4 GHz Wi-Fi 6 + BLE 5.2 combo module, FCC ID P53-EMC6069, granted 2023-12-20). This is proven by teardown for two siblings (AC0951/13 "Unicorn" and CX3550/01 "Trident") and matches the radio paragraph of the official AC3210/AC3220/AC3221 manual word for word ("802.11b/g/n/ax at 2.4GHz", "Bluetooth version 5.2 (LE)"). The AC3220 itself has not been opened by anyone I could find, so for the AC3220 this is a strong inference, not a fact. One project says the SoC is a Beken BK7235.
2. **`@86` means module firmware 0.8.6.** Two independent UART captures show the Wi-Fi module writing the string "0.8.6" into the main MCU at boot, and the Air+ app shows that as "Wi-Fi firmware 86". The purifier therefore carries two firmware images: the Wi-Fi module (`WifiVersion`, e.g. `AWS_Philips_AIR_Combo@86`) and the main MCU (`D01S12`, e.g. 0.2.3).
3. **MAC prefixes.** IEEE lists eight OUIs for MXCHIP. kongo09 matches five, tinkerologie four. The only two MACs on record for `@86` Combo purifiers (AC0951/13 and AC4221/11) are in `68:79:C4`, which tinkerologie does **not** match. No MAC and no DHCP hostname has been published for any AC3210/AC3220/AC3221.
4. **Discovery that works without DHCP sniffing exists.** A "Unicorn" device on `@86` (AC0950/10) answered a plaintext `GET /sys/dev/info` sent to the subnet broadcast address and to `224.0.1.187` within 200 ms (openHAB log of 2026-10-04). The reply carries `device_id`, which is identical to `DeviceId` in the encrypted status. So a device can be found and uniquely identified with one plaintext datagram, without a sync and without registering an observer.
5. **Onboarding** is done by the Air+ app with BLE assistance and a SoftAP fallback (an unprovisioned AC0951 exposes a "Philips Setup" AP, 10.0.0.1, JSON on TCP 30123). Internet is needed for onboarding. The Wi-Fi LED shows cloud state, not LAN state.
6. **The Air+ app does talk local CoAP on current firmware.** An AC4221/11 owner (`@86`, Feb 2026) captured his phone talking to the purifier on UDP 5683 and could still control the purifier from the app with the purifier's internet blocked. Round 1 notes 01 and 05 said the opposite on the strength of a 2023 maintainer statement; that should be corrected.
7. **PR #384 (RSA + AES-GCM on `/sys/dev/info/tls`)**: the code is internally coherent but never executed against a device, and is dead code even in the author's own fork. New evidence here: devices that advertise the alleged capability bit (`option` = 119, bit 6 set) include an old-generation AC2939 and two `@86` Unicorn units, and all of them work with the legacy `JiangPan` handshake. So if the mode exists it is optional today. Do not probe it by default.
8. **Hardware fallback is real but invasive.** Replacing/parking the MXCHIP module and driving the MCU UART (115200 8N1, `FE FF` framing, CRC-16/CCITT-FALSE, TLV datapoints) from an ESP32 is proven on an AC0951 (ESPHome component) and a CX3550 (MQTT firmware). The datapoint numbering is exactly the `D0xxxx` naming. Nobody has done it on an AC3220.

---

## 1. Wi-Fi module and identity

### 1.1 What the official AC3220 manual says [V-doc]

`scratchpad/dl09/manual/um_eu.txt` (text of the EU user manual for AC3210 / AC3220 / AC3221, source https://dam.versuni.com/m/318e9bf4b39631a/original/CC_2024_AC3210_AC3220_AC3221_User-manual_EU.pdf, saved by the note-09 agent):

- lines 73-76: "Standard WiFi interface based on 802.11b/g/n/ax at 2.4GHz with a maximum output power of 64mW EIRP." and "Bluetooth version 5.2 (LE) at frequency 2.4GHz with RF output less than 10mW EIRP."
- lines 40-41: "To ensure the best performance, kindly suggest the firmware of your purifier is upgraded to the latest version. You can do this upgrade via the Air+ app."

So the AC3220 has a single-band 2.4 GHz Wi-Fi 6 radio with BLE 5.2. Old-generation purifiers (EMW3080-class modules) were 802.11b/g/n without BLE.

### 1.2 The module in the sibling devices [V-raw, V-code, V-doc]

- tuct "ESPHome hacked air purifiers" project, Series 900 guide (https://raw.githubusercontent.com/tuct/levoit/main/devices/philips-900-series/README.md, also reachable as tuct/esphome-projects; saved as `dl07/tuct_devices_philips-900-series_README.md`), lines 32-39, device opened and photographed, AC0951:
  - "Stock Wi-Fi module | **MXCHIP EMC6069-P** - 2.4 GHz Wi-Fi + BLE, FCC ID `P53-EMC6069`"
  - "Module form | Blue castellated daughterboard (`EMC6069-HF`), soldered to the main PCB"
  - "MCU firmware | `0.3.3` (module firmware `0.8.6`)"
  - "Internal model string | `AC0951/13`, codename **`Unicorn`**"
  - "Stock local control | CoAP (`AWS_Philips_AIR`) without opening the case"
  - line 320: board markings "`TL-2780-C-V1.0` (main) and `TLC2700-C-V1.0` (LED module)"; main MCU "Unmarked QFP ... part number still unidentified".
  - Project changelog (`dl07/tuct_CHANGELOG.md`): module identified in the 2026.09.09 entry, AC0951 running ESPHome in the 2026.09.11 entry.
- 1RandomDev CX3550 project (`1RandomDev_philips-cx3550-homeassistant/README.md`, commits 2026-07-28): "the [MXChip EMC6069-P](https://fccid.io/P53-EMC6069) WiFi module uses the BK7235 microcontroller, which is not supported by LibreTiny yet." The CX3550 reports `WifiVersion: AWS_Philips_AIR_Combo@86` (note 06).
- FCC (https://fccid.io/P53-EMC6069, read through WebFetch): applicant "Shanghai MXCHIP Information Technology Co.,Ltd.", "2.4GHz Wi-Fi/BLE Module", "Date of Grant: 12/20/2023", 2412-2462 MHz and 2402-2480 MHz, single modular approval; block diagram, schematics and operation description are confidential. The datasheet exhibit (https://fcc.report/FCC-ID/P53-EMC6069/6997948.pdf, via web search summary) describes a "Wi-Fi 6 Combo SoC", "2.4G Hz IEEE 802.11 b/g/n/ax, BLE 5.2", 32-bit RISC-V MCU. Beken's BK7235 is publicly described the same way (1x1 2.4 GHz Wi-Fi 6 + BLE 5.2, RISC-V), so the BK7235 claim is plausible; I did not see the chip marking myself. [WF/H for the chip]

### 1.3 Does that carry over to the AC3220? [I]

For:
- Same internal codename. The AC3210/AC3220 report `D01S04: "Unicorn"` (notes 02 and 09); the AC0951 reports "Unicorn" on the UART (group 0x01, DP 0x04) and `type: "Unicorn"` on the LAN.
- Same Wi-Fi firmware family and number on siblings: `AWS_Philips_AIR_Combo@86` on AC3210/12 (note 09 dump B), AC0950/10, AC0951/13, CX3550, CX7550, AC2210/AC2220, AC4220/AC4221.
- The manual's radio description (1.1) equals the EMC6069 datasheet.
- Same `free_memory` scale on `@86` units: 97,904 (AC3210), 97,712 (AC0950), 95,536 (CX3550), about 100,000 (CX7550).

Against / unknown:
- No teardown, FCC filing or photo of an AC3210/AC3220/AC4220 board was found. [NF] (web searches for FCC IDs of the PureProtect 3200/4200 returned nothing; these models may not be sold in the US under a separate filing.)
- The one AC3220 dump from Nov 2024 (`@3.0`, MCU 0.1.9) shows `free_memory: 154416` and `blelog: false`, the `@86` dumps show about 97,000 and `blelog: -1`. That is most simply a firmware difference, but it is the only hint that early units could differ.

Confidence that a 2026 AC3220/10 has an EMC6069-class MXCHIP module: high. Confidence that it is exactly EMC6069-P with a BK7235: medium.

### 1.4 "@86" is module firmware 0.8.6; two firmware images [V-code, V-raw]

- `1RandomDev_philips-cx3550-homeassistant/reverse-engineering/PROTOCOL.md`, "Initial startup": the Wi-Fi module sends `SET` group `01`, DP `0f`, string "0.8.6" (`PAYLOAD=[01 0f 73 06 30 2e 38 2e 36 00 00]`); the MCU's group 01 report before that had DP 0x0F = "0.0.2" and DP 0x12 = "0.1.7".
- tuct 900 guide lines 351-365: "`0x0F` | `"0.0.0"` -> `"0.8.6"` | **Wi-Fi module firmware** - the module writes its own version here at boot. The app shows this as its *Wi-Fi firmware* (`86`)." and "`0x12` | `"0.3.3"` | **Device (MCU) firmware**"; "The two version strings are **confirmed against the app UI**".

Consequences:
- `WifiVersion` (`...Combo@86`) and `D01S12` are independent version numbers of two separate images. Both changed between the 2024 AC3220 sample (0.1.9 / `@3.0`) and the 2026 siblings (0.2.3 / `@86`), so OTA can update both. [I]
- "`@3.0`" and "`@86`" are not written in the same notation, so ordering by number is unsafe; dates say `@3.0` (2024) precedes `@86` (2026). [I]
- An integration should expose both as diagnostics (`sw_version` = MCU, plus a Wi-Fi firmware sensor) and key behaviour on `WifiVersion`, not on model.

### 1.5 How the module and the MCU talk, and why the device is "push on change" [V-code, V-raw, I]

- The module polls the MCU: "The WiFi module constantly polls groups `0x02`, `0x03` and `0x04`. If the device state (group `0x03`) changes, it is published to the mobile app via cloud MQTT." (1RandomDev PROTOCOL.md, "Behaviour"). tuct 900 guide lines 606-608: "The module **polls at ~1 Hz** (groups `0x02`/`0x03`/`0x04` every second, `0x01`/`0x05`/`0x0B` every ~10 s)".
- Sensor readings live in the same group as the controls (PM2.5 = group 0x03 DP 0x21, allergen index = DP 0x20; tuct lines 399-416), and "the MCU owns the readings" (line 244).
- [I] The change detector is therefore in the module firmware and works on the polled group-0x03 image. This is the mechanical explanation for the round-1 finding that `@86` only pushes when a value changes: silence means "no datapoint in group 0x03 changed", not "device unhealthy". It also means a nudge (writing any group-0x03 datapoint) must produce a push, which is what tinkerologie's "status nudge" relies on.
- Cold start quirk on the AC0951 (tuct lines 580-600): "The first handshake attempt **reliably fails**" and is followed by "~124 s of complete silence" before the module and MCU link comes up, "deterministic to the millisecond across captures". [I] If the AC3220 behaves the same, the purifier may be on Wi-Fi after a power cut but have no valid MCU data for about two minutes. Worth measuring on the real unit before choosing start-up timeouts.

---

## 2. MAC prefixes and DHCP hostname

### 2.1 Vendor lookup [V-doc]

IEEE registry (`dl07/oui.csv`, https://standards-oui.ieee.org/oui/oui.csv, downloaded today) and https://api.macvendors.com/<prefix>:

| OUI | Registrant | kongo09 manifest | tinkerologie manifest | foXaCe fork |
|---|---|---|---|---|
| B0F893 | Shanghai MXCHIP Information Technology Co., Ltd. | yes | yes | yes |
| 047863 | Shanghai MXCHIP | yes | yes | yes |
| 849DC2 | Shanghai MXCHIP | yes | yes | yes |
| 80A036 | Shanghai MXCHIP | yes | yes | yes |
| 6879C4 | Shanghai MXCHIP | yes (added 2026-01-31) | **no** | yes |
| 88A68D | Shanghai MXCHIP | no | no | no |
| D0BAE4 | Shanghai MXCHIP | no | no | no |
| C89346 | MXCHIP Company Limited | no | no | no |
| E8C1D7 | Philips (HTTP-era AC3829, 2020-2022 forum posts) | no | no | no |
| E4BC96 | Versuni (ESP32 models AC0650/AC0720, no local CoAP) | no | no | no |

Manifests: `kongo09_philips-airpurifier-coap/custom_components/philips_airpurifier_coap/manifest.json`, `tinkerologie_ha-philips-airpurifier/custom_components/philips_airpurifier/manifest.json`, `foXaCe_philips-airpurifier-coap/custom_components/philips_airpurifier_coap/manifest.json`. All three also have `{"hostname": "mxchip*"}` and `{"registered_devices": true}`.

History of the kongo09 matchers [V-code, `git show`]: `f91cb50` 2022-04-19 (B0F893, 047863, hostname mxchip*), `4315385` 2024-01-21 "extend autodiscovery for AMF" (849DC2), `64c8d2c` 2024-10-05 "add mac of new devices for discovery" (80A036, same day as the AC0850 variants), `a0377a5` 2026-01-31 "add new address for auto discovery" (6879C4, the day issue #300 was closed).

### 2.2 MACs and hostnames actually reported

| Date | Model (generation) | MAC prefix | DHCP hostname | Source |
|---|---|---|---|---|
| 2020-01 | AC3829/60 (HTTP era) | e8:c1:d7 | - | HA forum 53030 #77 [V-forum `t53030_all.txt:1010`] |
| 2020-01 | AC1214 (old CoAP) | B0:F8:93 | "MiCO" | #79 [V-forum :1018] |
| 2022-04 | 2 units (old CoAP) | b0:f8:93 | "mxchip" | kongo09, #291 [V-forum :3721] |
| 2022-04 | AC2889/10, AC3829/10, AC3033/10, AC1214 | 04:78:63 | "mxchip" (aceindy: "both are *mxchip*") | #292-#300 [V-forum :3740-3784] |
| 2023-01 | AMF765/10 "Pegasus" (D0xxxx keys) | 84:9D:C2 | - | #386 [V-forum :4684] |
| 2026-01 | **AC0951/13 "Unicorn", `@86`** | **68:79:C4** | - | kongo09 #300 [WF; note 04] |
| 2026-02 | **AC4221/11, `@86`, MCU 0.2.3** | "67:79:C4:59:" as typed | - | kongo09 #328 [WF] |
| 2025-03, 2026-11 | AC0650/10, AC0720/10 (ESP32, no CoAP) | E4:BC:96 | "espressif" | HA #448; tinkerologie #215 (note 04) |

- `67:79:C4` cannot be a real device address (0x67 has the group bit set), so the AC4221 report is almost certainly a typo for `68:79:C4`. [I]
- **No MAC prefix and no DHCP hostname has been published for an AC3210, AC3220 or AC3221.** [NF] (grep over notes 04/05, all saved forum copies, plus WebFetch of kongo09 #300, #328, #370 and tinkerologie #8.)
- **Hostname on the Combo generation is unknown.** "MiCO" (2020) and "mxchip" (2022) are both from old-generation modules. No post names the hostname of any EMC6069 device. The `mxchip*` hostname matcher in all three manifests dates from 2022 and is unverified for this generation. [NF]
- [I] The two `@86` data points both sit in 6879C4, the newest OUI anyone added. A 2026-built AC3220 will most likely be in 6879C4 or in one of the three MXCHIP OUIs nobody matches (88A68D, D0BAE4, C89346). With tinkerologie's manifest it would then not be auto-discovered at all unless the hostname happens to start with "mxchip".

---

## 3. Discovery options and their reliability

### 3.1 What `/sys/dev/info` returns

Unicast or broadcast, plaintext, no sync needed. Samples:

| Device / firmware | How | Payload | Source |
|---|---|---|---|
| AC3858/50, `Ms4102` (2020) | captured from the app, then replayed | `{"product_id":"<cut>","device_id":"<cut>","name":"Living Room","type":"AC3858","modelid":"AC3858/50","swversion":"Ms4102","option":"1"}` | HA #110 [V-forum `t53030_all.txt:1366`] |
| AC2939/10, `Ms2106` (2026-10) | openHAB broadcast discovery | `{"product_id":"b97e...","device_id":"78ee...","name":"Wohnzimmer","type":"AC2939","modelid":"AC2939/10","swversion":"Ms2106","option":"119"}` | openHAB forum 170501 #24 [V-forum `forum/openhab/t170501_posts.json`] |
| **AC0950/10 "Unicorn", MCU 0.3.3, `@86`** (2026-10) | openHAB broadcast discovery | `{"product_id":"e3a1f43cfacc11ee974e06d016384e4a","device_id":"fc50a199bceb11f18844e3188138d24e","name":"Schlafzimmer","type":"Unicorn","modelid":"AC0950/10","swversion":"0.0.0","option":"119"}` | same post |
| AC0951/13, `@86` (2026-01) | `coap-client -m get coap://<ip>/sys/dev/info` | keys in order product_id, device_id, name, type, modelid, swversion, option; all values strings; `"modelid":"AC0951/13","swversion":"0.0.0","option":"119"` | kongo09 #300 [WF] |
| CX7550/01, `@86` | philips-airctrl | placeholder example only (`modelid`, `name`, `device_id`) | philips-airctrl #7 [WF] |

Facts that matter:
- **`device_id` equals the status `DeviceId`** and `product_id` equals `ProductId`: the same AC0950 posted its encrypted status two posts earlier with `"ProductId":"e3a1f43cfacc11ee974e06d016384e4a","DeviceId":"fc50a199bceb11f18844e3188138d24e"` (170501 #22). [V-forum] Both integrations use `DeviceId` as unique id, so the unique id is available from the plaintext probe.
- `type` on Gen3 is the codename (same value as `D01S04`), `modelid` is the commercial model with suffix. For an AC3220/10 expect `type: "Unicorn"`, `modelid: "AC3220/10"`. [I]
- **`swversion` is useless on Gen3** ("0.0.0" on both Unicorn samples). Firmware versions must be read from the status (`D01S12`, `WifiVersion`).
- `option` is a bit field: "1" (2020), "119" (2026, old and new generation alike). See section 6.
- `coap-client` sends confirmable requests by default, so `/sys/dev/info` is also answered for CON GETs. In the same issue `GET /`, `/air`, `/firmware` and `/.well-known/core` all returned 4.04, so there is no CoAP resource directory. [WF]
- The same JSON family appears on the setup access point (section 4).

Library support: philips-airctrl `get_device_info()` with `create(sync=False)` (`tinkerologie_philips-airctrl/src/philips_airctrl/coap/client.py:393-422`, added in 1.2.0); phipsair `INFO_PATH` (`mfrister_phipsair/phipsair/coap/client.py:19`); openHAB discovery (below); not in betaboon/kongo09 aioairctrl.

### 3.2 CoAP broadcast / multicast: evidence that Gen3 answers [V-forum, V-code]

openHAB binding code (`marcelrv_openhab-addons_philipsair/bundles/org.openhab.binding.philipsair/src/main/java/org/openhab/binding/philipsair/internal/discovery/PhilipsAirCoapDiscovery.java`): NON `GET sys/dev/info` (:75, :236-238) to every interface broadcast address plus "224.0.1.187" (:180-185), response matching relaxed (:91-92), and any payload containing "product_id" is accepted (:113). Thing UID = `device_id` (:207).

Log from a user, openHAB forum https://community.openhab.org/t/170501/24 (2026-10-04, Mclupo), verbatim from the saved JSON:

```
09:52:59.188 Send discovery request: coap://172.17.255.255:5683/sys/dev/info
09:52:59.190 Send discovery request: coap://192.168.1.255:5683/sys/dev/info
09:52:59.191 Send discovery request: coap://224.0.1.187:5683/sys/dev/info
09:52:59.290 Creating Philips Air Purifier (COAP) discovery result for: IP=192.168.1.75, {... "type":"AC2939","modelid":"AC2939/10","swversion":"Ms2106","option":"119"}
09:52:59.386 Creating ... IP=192.168.1.76, {... "type":"Unicorn","modelid":"AC0950/10","swversion":"0.0.0","option":"119"}
09:52:59.680 Creating ... IP=192.168.1.76, {... AC0950/10 ...}
09:52:59.832 Creating ... IP=192.168.1.75, {... AC2939/10 ...}
```

- Both generations answered within 100-200 ms and each answered twice (each reply is logged twice, by the interceptor and by the handler; there are two distinct reply times per device). Two of the three requests could reach the LAN (the 172.17.x.x address is a Docker bridge), so the most likely reading is that each device answered both the subnet broadcast and the multicast group. [I] The log cannot prove which.
- This answers round-1 open question 9 ("does multicast/broadcast `GET /sys/dev/info` work on the AC3220?") for a same-platform sibling on the same Wi-Fi firmware: **yes**. For the AC3220 itself it remains an inference.
- The upstream binding documents it as the standard method: "CoAP devices are found with a CoAP broadcast" (`dl09/openhab_main/README.md:137`).

foXaCe fork (`foXaCe_philips-airpurifier-coap/custom_components/philips_airpurifier_coap/helpers.py:25-34, 187-233`): hand-built NON GET to `224.0.1.187:5683` for two paths, `sys/dev/info` and `sys/dev/info/encryption`, re-sent every second for 3 s ("the first multicast burst can be swallowed by IGMP snooping on some switches"). It claims (comment :25-27, PROTOCOL.md:88-89) that this is what the Air+ app does, and that "encrypted" devices answer the second path with a field `didt` = AES-CBC of "deviceId&deviceToken" keyed with MD5("JiangPan" + the client's own IP) (`helpers.py:126-146`). [H] There is no capture or device log behind the `didt` claim; the openHAB log shows Gen3 answering the plain path with a plaintext `device_id`, so the `encryption` path is not needed.

Reliability limits [I, from round-1 facts]:
- The device is in Wi-Fi power save and missed 39 % of broadcast ARP requests in the one measured network (kongo09 #396, note 04 F3). Broadcast and multicast CoAP probes travel the same way (buffered until DTIM), so a single probe can be missed. Send 3 to 5 probes one second apart: with a 39 % miss rate, three probes leave about 6 %, five about 1 %.
- Layer-2 only. No routed VLAN, no guest network, no Docker bridge networking. HA OS and supervised run with host networking, so they are fine.
- IGMP snooping can drop the multicast variant; the subnet broadcast variant does not depend on it. Send both, as openHAB does.

### 3.3 HA DHCP discovery: how it really works and when it fails [V-code]

`src10/ha_core/homeassistant/components/dhcp/__init__.py` (core checkout of 2026-11-22):
- Four feeders call the same matcher: `DHCPWatcher` (sniffs DHCP requests via `aiodhcpwatcher`, :411-447), `NetworkWatcher` (an active `aiodiscover` scan at start-up and every `SCAN_INTERVAL = timedelta(minutes=60)`, :75, :296-348; "Class to query ptr records routers"), `DeviceTrackerWatcher` (router integrations such as UniFi/FRITZ!Box supply ip, mac, hostname, :350-386) and a rediscovery watcher.
- Matching (:236-262): first, any device-registry entry whose `connections` contain this MAC and whose integration declared `registered_devices` matches regardless of OUI; then OUI matchers (first six hex digits) and hostname-only matchers (fnmatch on the lower-cased hostname).
- A flow is only started when IP or hostname changed for that MAC (:207-217).

What follows:
- OUI matching does not need HA to see the DHCP exchange: the hourly neighbour/PTR scan and router integrations also feed it. It does need the device's MAC to be visible to the HA host (same layer-2 segment) or a router integration.
- Hostname matching needs a hostname source (sniffed DHCP option 12, router PTR records, or a router integration).
- `registered_devices: true` only helps if the integration stored the real MAC as a device connection. That is where the existing integrations are weak:
  - kongo09 gets the MAC from the ARP cache with `getmac` after setup (`__init__.py:14,108`). Issue #370 (jiannmeng, 2026-07-23) [WF]: "my Home Assistant Yellow box obtained MAC 00:00:00:00:00:00 for the devices sometimes", "the 3rd kept getting "merged" into one of the other 2 Devices within HA", "within HA's registry the wrong MACs were never deleted"; devices on `AWS_Philips_AIR@73.1`. Fixed 2026-07-26 by ignoring all-zero and broadcast MACs (`helpers.py:8-9,35`, PR #373). The registry clean-up for already merged devices was manual.
  - tinkerologie only learns the MAC from a DHCP discovery (note 03 section 2.6), so a manually added unit with an unmatched OUI never gets one, and an IP change is then not followed (issue #8, AC3210, "When the device get a new IP, the integration turns into error and is not auto discovered anymore, nor with mac nor with id", closed "not planned" 2026-06-17 [WF]; partially addressed in 2026.6.1).
- OUI matchers are not specific to Philips: MXCHIP modules are in many brands' appliances. Any OUI-triggered flow must confirm the device before showing it to the user.

### 3.4 How the existing integrations identify a device, and whether they disturb a running session

| Integration | Discovery probe | Disturbs a live session? |
|---|---|---|
| kongo09 v0.37 | DHCP step runs sync + `get_status()` (an observe registration) **before** checking whether the device is configured (`config_flow.py:62-89`; note 11 F8) | Yes: on firmware with one observer per client IP the probe steals the coordinator's notifications on every HA start. PR #389 that fixed it was closed unmerged |
| tinkerologie 2026.11.1 | Matches by stored MAC or host first and only updates the host (`config_flow.py:151-175, 192-193`); new devices get sync + `get_status(observe=False)` (`client.py:126`), falling back to plaintext `sys/dev/info` + nudge (`config_flow.py:108-149`) | Not for configured devices; a new-device probe still opens an encrypted session |
| foXaCe 0.42.1 | DHCP + SSDP (`urn:philips-com:device:DiProduct:1`, HTTP-era only) + manual scan = multicast, then ARP-table sweep, then .1-.100 (`helpers.py:268-329`); "The rediscovery is now aborted before probing, since the device only accepts the single CoAP connection already held by the coordinator" (CHANGELOG 0.39.1) | Not for configured devices; the fallback sweeps open a full session to every candidate IP |
| openHAB | Plaintext broadcast/multicast `sys/dev/info`, UID = `device_id` | No session at all |

[I] The plaintext info request is not an observe registration and does not touch the sync counter, so it is the only probe that is safe to send to a device that another client (or the same integration) is already observing. No source reports a side effect of it; phipsair used it every 60 s as a keep-alive on an AC2889 in 2022 (note 01 section 6).

### 3.5 Other discovery channels

- **SSDP/UPnP**: only the HTTP-era devices (`urn:philips-com:device:DiProduct:1`; py-air-control `http_client.py:55-75`; openHAB `PhilipsAirUpnpDiscoveryParticipant`). No evidence for any CoAP-generation device. [NF]
- **mDNS**: no evidence that MXCHIP purifiers announce anything. [NF] (The mDNS/SSDP description in `renaudallard_homeassistant_philips_homeid/docs/PROTOCOL.md` is about HomeID kitchen appliances.)
- **CoAP resource discovery** (`/.well-known/core`): 4.04 on an AC0951 `@86` (kongo09 #300 [WF]).
- **BLE**: present in the module and used during onboarding (section 4). No public description of a GATT service, and no evidence that a provisioned purifier advertises or can be controlled over BLE. [NF] Not a discovery option today.
- **IPv6**: an AC4221 `@86` owner: "I have IPv6 on my network, but the device has not used a ipv6 address" (kongo09 #328 [WF]). Treat the device as IPv4 only.

---

## 4. Onboarding and coexistence with the Air+ app

### 4.1 Provisioning [V-doc, V-forum]

Manual (`dl09/manual/um_eu.txt`):
- Wi-Fi indicator table (lines 265-272): "Blink in orange - Connecting to the smart phone", "Stable in orange - Connected to the smart phone", "Blink in white - Connecting to the server", "Stable in white - Connected to the server", "Off - Wi-Fi function disabled or device lights are off".
- Pairing (lines 286-311): indicator "blinks orange for the first time"; "Enable Bluetooth feature on your smart phone to ensure the smooth pairing."; "Please ensure your smart phone is connected to a 2.4GHz (home) Wi-Fi netwok instead of a 5GHz Wi-Fi network or public Wi-Fi. For a successful pairing, we suggest turning off your mobile data before initiating the pairing process."; phone within 10 m.
- Troubleshooting (lines 806-832): enable the permissions "Location", "Storage", "Bluetooth", and "Local Network"; the Wi-Fi password "is case-sensitive, has a limit of 63 characters. Special symbols are not accepted."; turn off VPN; "If your router has a whitelist set up to block pairing, please disable the whitelist".
- Reset Wi-Fi (lines 325-341): press two buttons for 3 s until a beep; "The air purifier goes to pairing mode. The Wi-Fi indicator blinks orange."
- A second phone can add the purifier in the app "without doing the Wi-Fi connection reset on the device" (binding is by account, not by re-provisioning).

SoftAP side, HA forum 53030 #443 (vlagged, 2025-01-02, unprovisioned AC0951/13) [V-forum `t53030_all.txt:5183-5199`]: "When connected to the Philips Setup access point, I receive an IP of `10.0.0.100`. The purifier itself is `10.0.0.1` and it responds to UDP 53 ... and to port 30123 on TCP." A TCP connect prints

```
{"type":"deviceinfo","meta":{"message":"check device info","code":100},"data":{"option":55,"name":"AirPurifier","type":"Unicorn","modelid":"AC0951/13","swversion":"0.0.0","bind_token":"<<redacted>>"}}
```

and an empty line is answered with `{"type":"config","meta":{"message":"no json","code":1000}}`. In the same post: py-air-control's Wi-Fi setup commands (HTTP, plain CoAP, CoAP) do not work against it, and the APK has the info fields in a `com/gaoda/sdk/bean/coap` class.

Reading [I]: BLE is used to find the device and/or pass credentials ("smooth pairing"), with a SoftAP JSON protocol on TCP 30123 as the other path (the advice to switch off mobile data only makes sense for a phone that joins an AP without internet). The `bind_token` binds the device to the cloud account. **No open tool provisions this generation without the app**, so the user must onboard with Air+ once, with internet (also HA #290 for the old generation, note 05; tuct `docs/philips-coap.md`: CX7550 "needs the Philips Air app once for Wi-Fi onboarding, then fully local").

### 4.2 Does the device need internet afterwards?

- Local CoAP does not depend on the cloud in any library. Long-term internet-blocked operation is reported for old-generation units (RT1080 since 2022) and for a "4000i" in 2026 (note 05 section 5). 
- Combo generation, AC4221/11 `@86` (kongo09 #293, ThomasCr, Feb 2026; quoted in note 11 from WebFetch): "Yesterday I blocked internet traffic from the Philips Device on my Firewall - and could also control the device with the app."
- [I] With WAN blocked the Wi-Fi indicator will probably blink white permanently ("Connecting to the server"). The indicator says nothing about LAN reachability; do not use it in troubleshooting text as "connected".
- Not found: a report of an AC32xx running for months with internet blocked, and what the module does when it cannot reach the cloud for a long time (reconnect storms, reboots, NTP dependence). [NF]

### 4.3 The Air+ app does use local CoAP on current firmware [WF, V-forum]

- kongo09 #328 (ThomasCr, 2026-02-25, AC4221/11, MCU 0.2.3, `AWS_Philips_AIR_Combo@86`): "I made a tcpdump of my connection between my phone and the philips device and could see, that it also connects to port 5683." and "I can provide the pcap I made - but for me it looks encrpted". No pcap is attached. Together with the blocked-internet quote above, this is direct evidence of a local app-to-device path on `@86`.
- Historic: 2020 captures of the AirMatters app show local UDP 5683 and `coap://IPADDR/sys/dev/status` (HA #79, #110) [V-forum]; the manual asks for the iOS "Local Network" permission.
- Contradicting statement: kongo09, HA forum 53030 #407 (2023-09-15): "The Philips app connects to the cloud and the device connects to the same cloud, so they don't talk directly even if on the same network." [V-forum `t53030_all.txt:4840`] Round-1 notes 01 (7.7) and 05 (section 6) adopted this. The 2026 capture outweighs it: the app uses both paths.
- What the app does on that local path (legacy sync or the `/sys/dev/info/tls` exchange, how it gets an initial status from a push-on-change device, whether it holds an observation) is **unknown**; the one person with a pcap did not publish it. foXaCe's PROTOCOL.md asserts the app pings every 3 s with a 10 s timeout and re-syncs after any rejection; unverified. [H]

Coexistence consequences [I]:
- The app runs on a different source IP than HA, so under the "one observer per client IP" model (note 04 F8) it should not evict HA's observation, and its commands produce pushes that HA sees. Reports that opening the app "wakes" a stuck integration (note 04) fit: the app causes state traffic.
- A second local client on the **HA host** (CLI test, a second integration, an add-on) shares HA's source IP and is the dangerous case.
- Because the app can also work through the cloud, "the app still works" proves nothing about the LAN path.

---

## 5. Firmware updates

### 5.1 Mechanism (what is and is not known)

- Official wording: upgrade "via the Air+ app" (manual, 1.1). Old-generation forum reports say updates arrive without a prompt after a power cycle with internet (note 05 section 5). The status document carries `otacheck` (false in every dump). Which of the two applies to the Combo generation (prompted or silent) is not documented anywhere I could find. [NF]
- Two images are updated (1.4). No vendor changelog exists for either. [NF]
- No downgrade path and no local update endpoint are known (`GET /firmware` is 4.04 on an AC0951, kongo09 #300 [WF]).

### 5.2 Version matrix for the Combo family (additions to note 04 section 4.2 and note 09)

| Date seen | Model | MCU fw (`D01S12`) | Wi-Fi fw | `option` | Source |
|---|---|---|---|---|---|
| 2024-11 | AC3220/10 | 0.1.9 | `AWS_Philips_AIR_Combo@3.0` | - | kongo09 #181 (note 02) |
| 2025-01 | AC0951/13, unprovisioned | (swversion 0.0.0) | unknown | 55 (setup AP) | HA #443 |
| 2026-01 | AC0951/13 | 0.3.3 | `@86` | "119" | kongo09 #300 |
| 2026-02 | AC4221/11 | 0.2.3 | `@86` | - | kongo09 #293/#328 |
| 2026-07 | CX3550/01 | 0.1.7 | module reports "0.8.6" on UART; shadow `@86` | - | 1RandomDev; note 06 |
| 2026-09 | AC0951 | 0.3.3 | module "0.8.6", app shows 86 | - | tuct |
| 2026-10 | AC0950/10 | 0.3.3 | `@86` | "119" | openHAB 170501 #22/#24 |
| 2026 | AC3210/12 | 0.2.3 | `@86` | - | note 09 dump B |

### 5.3 What changed between `@3.0` and `@86` (observations only, nobody documented a changelog)

| Aspect | `@3.0` (AC3220, 2024-11) | `@86` (siblings, 2026) | Confidence |
|---|---|---|---|
| Status behaviour | no complaints on record (weak evidence it answered status reads) | push on change only, status/observe GET often unanswered until the next change (notes 04, 11) | medium |
| `blelog` field | `false` | `-1` | high (dumps) |
| `free_memory` | 154,416 | about 95,000-100,000 | one sample vs several |
| `option` in info | unknown | "119" | - |
| Legacy sync + AES-CBC | works | works (every followed-up report) | high |

### 5.4 Cloud hostnames the device contacts

- **No packet capture or DNS log of the purifier's own traffic was found** in issues, forums, the tuct/1RandomDev projects or web search. [NF]
- App-side endpoints of the MxChip backend are known from note 06: REST `www.api.air.philips.com`, MQTT host returned by the API for EU accounts `a2gv4wmvb0sdt5-ats.iot.eu-central-1.amazonaws.com`. [I] The module (firmware name `AWS_Philips_AIR...`, state mirrored in an AWS IoT shadow) most likely holds an MQTT/TLS session to that AWS IoT endpoint; where the OTA image comes from is unknown.
- One user observation: "The purifier was making a surprisingly large number of connections to external servers" (Reddit, 2026-07, note 05).
- Practical consequence: a hostname block list cannot be given with any confidence. The only reliable OTA block is denying the purifier's IP/MAC all WAN access at the router (keep DHCP; DNS and NTP are optional and untested). Cost: the app's cloud path, schedules, voice assistants and firmware fixes stop; local app control reportedly still works (4.2).

---

## 6. kongo09 PR #384 (RSA + AES-GCM on `/sys/dev/info/tls`): technical assessment

Provenance is covered in note 11 (F11). I read the PR ref (`kongo09_philips-airpurifier-coap`, `pr/384` = `9c51731`) and the author's fork as of 2026-11-20 (`foXaCe_philips-airpurifier-coap`, `df1e53e`).

### 6.1 What the code does [V-code, fork paths under `custom_components/philips_airpurifier_coap/`]

1. Capability test: `is_tls_option()` returns `((int(option) >> 6) & 1) == 1` (`aioairctrl/coap/client.py:36-44`), `option` being the field from the discovery reply.
2. Handshake (`client.py:90-112`): generate an RSA-1024 key pair; NON `POST /sys/dev/info/tls` with content-format 50 and body `{"type":"config_encrypt","random2":<1000..9999>,"pk":"<PEM SubjectPublicKeyInfo>"}`; the reply is JSON with `random1` and `prekey` (hex, RSA PKCS#1 v1.5).
3. Secret (`encryption.py:196-208`): `total = (random1 + random2 + int.from_bytes(prekey, "little")) & 0xFFFFFFFF`; secret = first 16 hex characters of SHA-256 over that 32-bit little-endian integer.
4. Then the normal `/sys/dev/sync` runs (`client.py:81-83`), and the envelope stays the same (8 hex counter + ciphertext + SHA-256 hex), but the key/IV come from `MD5(bytes.fromhex(secret) + counter)` and the cipher is AES-GCM with nonce = first 12 characters of the IV half, AAD = the key string, tag appended (`encryption.py:87-110, 112-152`).
5. Also added: a receive-side freshness window (accept counter in [last, last+10] modulo 2,000,000,000; `encryption.py:41-51, 161-194`), which the fork's CHANGELOG later had to fix twice (note 11).

### 6.2 Status

- Dead code: every call site uses `CoAPClient.create(host)` without `option` (`__init__.py:177`, `helpers.py:246`, `config_flow.py:119`, `coordinator.py:311`), in the PR and in the fork today. The discovery function returns `option` (`helpers.py:183`) but nothing passes it on.
- Tests run against a fake device with invented values (note 11). No device, firmware or capture is named anywhere.
- No independent source mentions `/sys/dev/info/tls`, `config_encrypt` or `prekey` (note 11 web search; none of the repositories cloned for this project contain them).

### 6.3 New evidence from this round: the capability bit is common, and legacy still works

| Device | `option` | bit 6 | Works with legacy `JiangPan` sync + AES-CBC? |
|---|---|---|---|
| AC3858/50, 2020 | "1" | 0 | yes (2020) |
| AC0951/13, setup AP, 2025-01 | 55 = 0b0110111 | 0 | not applicable (unprovisioned) |
| AC2939/10 `Ms2106`, 2026-10 | "119" = 0b1110111 | **1** | yes (openHAB binding, legacy only) |
| AC0950/10 Unicorn `@86`, 2026-10 | "119" | **1** | yes (same thread: full encrypted status decoded by openHAB) |
| AC0951/13 Unicorn `@86`, 2026-01 | "119" | **1** | yes (`aioairctrl status --json` returned the full status, kongo09 #300) |

So: if bit 6 really means "supports the TLS exchange", then (a) it is already set on current firmware of both generations, including the AC3220's platform, and (b) those devices still accept the legacy handshake. A mandatory switch has not happened on any device on record. The 55 -> 119 difference on the AC0951 (exactly bit 6) is suggestive of a feature added by a firmware update, but the two readings come from different interfaces (setup AP vs LAN), so that is not proven. [I]

### 6.4 Is it worth supporting?

- Security value: none. The secret has at most 32 bits of entropy (SHA-256 of a 32-bit sum), the exchange is unauthenticated, RSA-1024 with PKCS#1 v1.5, and the per-message key is still MD5-derived. It is obfuscation, like the legacy scheme. [I from the code]
- Risk of probing: unknown device-side effects. If the firmware switches the session for that client IP to GCM after a `config_encrypt` POST, a client that then continues with legacy envelopes would break its own session. Nobody has tested this. [I]
- Recommendation: read and log `option` (diagnostics), keep the crypto layer pluggable (envelope and counter logic are shared; only key derivation and cipher differ), and do **not** send anything to `/sys/dev/info/tls` in normal operation. Consider an explicit, opt-in fallback only for the case "bit 6 set, `/sys/dev/info` answers, legacy `/sys/dev/sync` gets no answer after several retries", and only after a bench test on the real unit or a published app capture. A phone-to-purifier pcap (the app does use UDP 5683, section 4.3) would settle in minutes whether the app posts to `/sys/dev/info/tls`.

---

## 7. Hardware alternatives (ESP32 on the MCU UART)

| Project | Device | Method | State |
|---|---|---|---|
| tuct/esphome-projects `components/philips` (https://raw.githubusercontent.com/tuct/levoit/main/components/philips/README.md) | AC0650/AC0651 (stock ESP32-C3 with secure boot) and **AC0950/AC0951** (MXCHIP EMC6069) | add an ESP32-C3, park the stock module, ESPHome external component | "An AC0951 is confirmed running this on hardware"; AC0950 untested; requires ESPHome 2026.05.3+ |
| 1RandomDev/philips-cx3550-homeassistant | CX3550 fan (EMC6069-P) | cut VCC/RX traces, ESP32 on the MCU UART, custom firmware with MQTT discovery | working, 2 commits (2026-07-28) |
| Hackaday project page https://hackaday.io/project/204909-esphome-hacked-air-purifiers-and-humidifiers | same as tuct | - | [WF] "The MXCHIP Wi-Fi module is held in reset and an ESP32-C3 wired in its place" |

Protocol (both projects agree; tuct verified "1026 frames ... with zero mismatches"):
- UART 115200 8N1, 3.3 V. Frame = `FE FF`, type (1), length (2, big-endian), payload, CRC-16/CCITT-FALSE over the payload.
- Commands: `0x01`/`0x02` handshake, `0x03` SET, `0x04` QUERY/GET, `0x07` STATUS/REPORT.
- Payload = group id + TLV datapoints (id, length or type byte, value); type `0x73` = string, `0x74` = blob.
- Groups: `0x01` device info, `0x02` Wi-Fi state (LED), `0x03` operating state, `0x05` filters, `0x08` network info.
- **This is the origin of the `D0xxxx` names**: `D` + group (2 hex) + length/type (1, 2, 4, S, R) + datapoint id (2 hex). Group 0x03 DP 0x02 length 1 = `D03102` (power); DP 0x0C = `D0310C` (mode); DP 0x21 length 2 = `D03221` (PM2.5); group 0x01 DP 0x05 string = `D01S05` (model); group 0x05 DP 0x0E length 4 = `D0540E` (HEPA remaining). Note 09 already uses this for the capability table; one mismatch is recorded there (UART 01/0x0F is the Wi-Fi version string while JSON `D0110F` is 3).
- Behaviour relevant to a replacement: strict request/response, the stock module polls at about 1 Hz, "Button presses never produce a SET" (the MCU only reports them in status), the MCU pushes a status about 25 ms after every SET.
- Parking the stock module on the AC0951: hold pad C (module reset/enable, 10k pull-up) low; the module stays soldered. On the CX3550 traces were cut.

Coverage of the AC3220: none. [NF] No project lists AC32xx/AC42xx/AC22xx; `docs/philips-coap.md` in the tuct repo lists the AC3210/AC3220/AC3221 only under "Cloud-free without ESPHome" (stock firmware over CoAP).

Is it a realistic fallback for an AC3220 owner? [I]
- Technically plausible: same codename, same module family, same datapoint map; the AC0951 component would need the AC3220's extra datapoints (lamp, ambient light, Auto+, temperature, humidity).
- Costs: opening a new appliance (warranty), work on a board that is partly at mains potential ("Do not connect the device to the mains while it's hooked up to a computer ... everything on the low voltage side can be live at 230V", 1RandomDev README), loss of the Air+ app and of OTA fixes, and first-of-its-kind reverse engineering for this model (board layout, pads, reset pin).
- Verdict: a last resort if a future firmware really removes local CoAP, not a starting point. It does give the project a strategic exit that does not depend on Versuni.
- Reflashing the stock module is not an option today (BK7235 not supported by LibreTiny per 1RandomDev; EMC6069 silicon and schematics unpublished per tuct).

---

## 8. Network behaviour that affects reliability

| Topic | What is known | Source / label |
|---|---|---|
| Band | 2.4 GHz only, 802.11b/g/n/ax | manual [V-doc] |
| Security mode | Manual names no WPA mode. The "WPA2 only, no WPA3" advice comes from an old-generation owner (aceindy, AC3829/AC1214, 2025-11) and an AC2889 that accepted WPA2/WPA3 mixed mode only after an update (note 04). Nothing is known for the Wi-Fi 6 module of the AC3220 | [NF] for this generation |
| SSID/password | Password up to 63 characters, "Special symbols are not accepted"; SSID case-sensitive; router MAC whitelist must allow the device | manual [V-doc] |
| IPv6 | Not used by an AC4221 `@86` on a dual-stack LAN | kongo09 #328 [WF] |
| Power save and ARP | Broadcast ARP answered 61 %, unicast ARP 99.7 % on an AMF870 `@86` (one site, UniFi, DTIM 1); queued UDP is dropped by the HA host when ARP fails | note 04 F3, note 11 F5 |
| Broadcast/multicast CoAP | Answered in 100-200 ms in the openHAB log, but subject to the same power-save loss as broadcast ARP | 3.2 [V-forum], [I] |
| DHCP renewals / IP change | No report of the Combo module misbehaving on renewal. IP changes break both integrations unless the MAC was learned (3.3) | notes 03/04; [NF] for module behaviour |
| After a power cut | AC0951: module-to-MCU link takes about 124 s to come up after a cold start (two captures) | tuct [V-raw]; applicability to AC3220 [I] |
| After a router reboot | Nothing specific found for this generation | [NF] |
| IP fragmentation | Still an inference from payload size (about 1.9 kB for the AC3220, note 01 section 4.5). No capture showing fragments or Block2 was found. Old-generation units with 1.4-2.3 kB envelopes have worked for years through plain UDP sockets, so fragments pass on ordinary LANs | [I] |
| Routed VLANs | Unicast UDP 5683 works routed for some users; discovery never does (kongo09 #300, Orange-GT3: "my issue was that the device couldn't be discovered across VLANs") | [WF], note 05 |

Why a periodic unicast probe matters twice [I]: the HA host's neighbour entry for the purifier expires after a period without traffic, and re-resolving it needs a broadcast ARP that the sleeping module often misses. A unicast datagram every 30-60 s keeps the entry in a state where the kernel revalidates with unicast ARP (answered 99.7 %). On a push-on-change device that can be silent for hours, the liveness probe is therefore also the fix for the "command never left the host" failure of note 04 F3. Plaintext `GET /sys/dev/info` is a candidate for that probe because it needs no session.

---

## 9. Design implications

1. **Identify by `device_id` from plaintext `/sys/dev/info`.** One NON GET, no sync, no observer. Use it for the config flow, for discovery confirmation, and for "is this still the same device" checks. Never open an encrypted session to a host that already belongs to a loaded entry.
2. **Three discovery sources, one code path**: (a) DHCP matchers for all eight MXCHIP OUIs (B0F893, 047863, 849DC2, 80A036, 6879C4, 88A68D, D0BAE4, C89346), `hostname: mxchip*` kept as a legacy extra, and `registered_devices: true`; (b) an active scan that sends `GET /sys/dev/info` to each IPv4 broadcast address and to 224.0.1.187, 3-5 times at 1 s spacing, at the user step and periodically (HA's own pattern: `homeassistant/components/wiz/discovery.py:54` with `SOURCE_INTEGRATION_DISCOVERY`, `DISCOVERY_INTERVAL = timedelta(minutes=15)` in `wiz/const.py:16`, using `network.async_get_ipv4_broadcast_addresses`); (c) manual host entry, always available.
3. **DHCP step order**: format MAC -> existing entry with that MAC? update host, abort, no I/O. Otherwise plaintext info probe -> `device_id` known? update host and MAC, abort. Otherwise confirm it is a Philips purifier (JSON with `modelid` and `device_id`) before showing a flow; MXCHIP OUIs are shared with other brands, so abort silently on anything else.
4. **Store the MAC, but never depend on it.** Take it from the DHCP discovery info or from the neighbour table right after a successful probe; reject all-zero, broadcast and group addresses; unique id stays `device_id`. The periodic broadcast scan then follows IP changes even where HA never sees DHCP and the OUI is unknown.
5. **Liveness and ARP warm-up in one**: a unicast plaintext info GET (or a sync round trip, per note 04) every 30-60 s, availability decided on several consecutive misses. Verify on the real unit that the info GET is answered while the device is idle on `@86` (evidence so far: AC0951, AC0950, CX7550).
6. **Firmware awareness**: expose MCU firmware (`D01S12`) and Wi-Fi firmware (`WifiVersion`) separately; ignore `swversion` from info; record `option`; select behaviour (push-on-change handling) from `WifiVersion`, with the model only as a hint.
7. **Start-up timing**: after a device power cycle allow at least 2-3 minutes before declaring failure (module-to-MCU handshake delay on the sibling), and retry discovery probes because of power save.
8. **Crypto layer**: one envelope/counter implementation with a pluggable key-derivation + cipher step. Ship legacy only. No traffic to `/sys/dev/info/tls` unless explicitly enabled.
9. **User documentation**: onboard once with Air+ (needs Bluetooth, 2.4 GHz, internet); reserve the IP; same layer-2 segment for discovery, routed UDP 5683 is enough for operation; blocking WAN for the purifier is the only known OTA block and makes the Wi-Fi LED useless as an indicator; the Air+ app on a phone can be used alongside HA, another CoAP client on the HA host cannot.
10. **Exit strategy**: note the UART route (section 7) in the project's design record as the fallback if local CoAP is ever removed; it needs no change to entity design because the datapoint ids are the same.

---

## 10. Open questions and how to answer them on the user's unit

| # | Question | Test |
|---|---|---|
| 1 | MAC OUI and DHCP hostname of the user's AC3220/10 | Router client list, or `ip neigh` on the HA host after a ping |
| 2 | Does it answer broadcast and multicast `GET /sys/dev/info`, and how often is a single probe missed? | 100 probes each to the subnet broadcast and 224.0.1.187, count replies; repeat with the unit idle for an hour |
| 3 | Exact info payload (`type`, `modelid`, `option`) and whether `device_id` = status `DeviceId` on this unit | One unicast GET plus one status read |
| 4 | Is the unicast info GET answered at all times on `@86` (suitable as liveness probe)? | Poll every 30 s for 24 h alongside an observation, compare with pushes |
| 5 | What does the Air+ app send on UDP 5683 (legacy sync, `/sys/dev/info/tls`, observe, multicast discovery)? | tcpdump on the router or a mirrored port while opening the app; no decryption needed to see the URI paths |
| 6 | Does a POST to `/sys/dev/info/tls` exist, and does it change how the device treats legacy clients? | Only after 5, on a bench, with HA stopped |
| 7 | Which hosts does the purifier contact, and is the update prompted or silent? | DNS log / flow log for the purifier's IP during the first days; watch `WifiVersion` and `D01S12` |
| 8 | Behaviour with WAN blocked for weeks (LED state, reboots, local stability) | Block, log `Runtime` and `rssi` from status |
| 9 | Time from power-on to first valid status; behaviour after router reboot and DHCP renewal | Smart plug power cycle with timestamps; router reboot |
| 10 | Are status notifications IP-fragmented or block-wise? | `tcpdump 'udp port 5683 or (ip[6:2] & 0x3fff != 0)'` |
| 11 | WPA3 / WPA2-WPA3 transition mode with the Wi-Fi 6 module | Only if the user's network uses it |
| 12 | Does the module really hold one observer per client IP on this model? | Second client from another host vs from the HA host |

---

## 11. Sources

Local code (relative to `scratchpad/src`)
- `kongo09_philips-airpurifier-coap`: `custom_components/philips_airpurifier_coap/manifest.json`, `helpers.py:8-9,35`, `__init__.py:14,108`, `config_flow.py:62-89`; commits `f91cb50`, `4315385`, `64c8d2c`, `a0377a5`, `d305856`; ref `pr/384` (`9c51731`).
- `tinkerologie_ha-philips-airpurifier`: `custom_components/philips_airpurifier/manifest.json`, `client.py:126,133-152`, `config_flow.py:95-195`.
- `tinkerologie_philips-airctrl`: `src/philips_airctrl/coap/client.py:393-422`, `CHANGELOG.md:78-95`.
- `foXaCe_philips-airpurifier-coap` (`df1e53e`, 2026-11-20): `manifest.json`, `helpers.py:25-34,112-233,268-329`, `aioairctrl/coap/client.py:29-112`, `aioairctrl/coap/encryption.py:1-213`, `PROTOCOL.md:79-110`, `CHANGELOG.md:51-55,144-149`.
- `marcelrv_openhab-addons_philipsair`: `.../internal/discovery/PhilipsAirCoapDiscovery.java:73-76,91-116,178-246`.
- `rgerganov_py-air-control/pyairctrl/http_client.py:55-75`.
- `1RandomDev_philips-cx3550-homeassistant` (cloned today): `README.md`, `reverse-engineering/PROTOCOL.md`.
- `scratchpad/src10/ha_core/homeassistant/components/dhcp/__init__.py:75,180-300,296-348,411-447`; `components/wiz/discovery.py:23,54`, `wiz/const.py:16`.

Local documents
- `scratchpad/dl09/manual/um_eu.txt` lines 40-41, 73-76, 265-341, 806-832.
- `scratchpad/dl07/oui.csv` (IEEE), `scratchpad/dl07/tuct_*.md`.
- `scratchpad/forum/t53030_all.txt` lines 1010, 1018, 1366, 3721-3784, 4684, 4840, 5183-5199; `scratchpad/forum/openhab/t170501_posts.json` posts 22 and 24.

Web
- https://fccid.io/P53-EMC6069 ; https://fcc.report/FCC-ID/P53-EMC6069/6997948.pdf
- https://raw.githubusercontent.com/tuct/levoit/main/devices/philips-900-series/README.md ; .../components/philips/README.md ; .../docs/philips-coap.md ; .../CHANGELOG.md (same repository as https://github.com/tuct/esphome-projects)
- https://hackaday.io/project/204909-esphome-hacked-air-purifiers-and-humidifiers
- https://github.com/1RandomDev/philips-cx3550-homeassistant
- https://github.com/kongo09/philips-airpurifier-coap/issues/300 , /issues/328 , /issues/293 , /issues/370 , /pull/384
- https://github.com/tinkerologie/ha-philips-airpurifier/issues/8 ; https://github.com/tinkerologie/philips-airctrl/issues/7
- https://community.openhab.org/t/170501/24 ; https://community.home-assistant.io/t/philips-air-purifier/53030/443 (and /79, /110, /291, /386)
- https://standards-oui.ieee.org/oui/oui.csv ; https://api.macvendors.com/
- https://dam.versuni.com/m/318e9bf4b39631a/original/CC_2024_AC3210_AC3220_AC3221_User-manual_EU.pdf

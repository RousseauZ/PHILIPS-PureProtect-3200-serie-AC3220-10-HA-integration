# 09 - AC3220/10 capability and datapoint map (round 2)

Scope: what the Philips PureProtect 3200 (AC3220/10, internal range "Unicorn") physically has, what it reports
and accepts over local CoAP, and how that should become Home Assistant entities. Builds on round 1 notes
02/03/04/05/06; nothing from those is re-derived here, only checked and extended.

Date of research: 2026-11-22. No AC3220 was available: every statement about device behaviour comes from
documents, other people's dumps, or other projects' code.

## 0. Sources and evidence labels

| Label | Meaning |
|---|---|
| **V-doc** | Official Philips/Versuni document that I downloaded and read verbatim |
| **V-dump** | Device status JSON read verbatim from a saved primary copy (forum raw post) |
| **R-dump** | Device status JSON relayed by a WebFetch summary of a GitHub issue (round 1; treated as accurate but not byte-verified) |
| **V-code** | Read in a cloned repository or a file fetched with git/raw |
| **R** | Paraphrase/quote relayed by WebFetch |
| **I** | My inference |

Paths below are relative to the scratchpad
`scratchpad`.

New primary sources collected in this round:

| What | Where | URL |
|---|---|---|
| EU user manual AC3210/AC3220/AC3221 (702 pages, 32 languages, PDF created 2025-01-10) | `dl09/manual/um_eu.pdf`, text `dl09/manual/um_eu.txt` (English = lines 84-865, Dutch from line 11145) | https://dam.versuni.com/m/318e9bf4b39631a/original/CC_2024_AC3210_AC3220_AC3221_User-manual_EU.pdf (linked from the AC3220_10 `.assets` JSON as type DFU) |
| Philips product API: AC3220/10 specification, features, summary (en_GB, nl_NL; round 1 copies) | `web06/prx/*.json` | https://www.philips.co.uk/prx/product/B2C/en_GB/CONSUMER/products/AC3220_10.specification (and `.features`, `.summary`, `.assets`; nl_NL on www.philips.nl) |
| Product API for siblings (AC3210/12, AC3221/13, AC4220/12, AC4221/11, AC2210/10, AC2220/10; AC3220/10 in de_DE, en_AU, en_SG) | `dl09/prx/*.json` | same URL scheme |
| openHAB Philips Air binding as merged (PR openhab/openhab-addons#21901, head `5e34c4d4`, 2026-10-13; identical to `main` on 2026-11-22) | `dl09/openhab_pr21901/CoapProfile.java`, `README.md`, `channels.xml`; `dl09/openhab_main/` | https://github.com/openhab/openhab-addons/pull/21901 , https://raw.githubusercontent.com/openhab/openhab-addons/main/bundles/org.openhab.binding.philipsair/README.md |
| CX3550 MCU-to-Wi-Fi-module UART protocol (same Wi-Fi firmware line `AWS_Philips_AIR_Combo@86`) | `dl09/cx3550/PROTOCOL_main.md` | https://raw.githubusercontent.com/1RandomDev/philips-cx3550-homeassistant/main/reverse-engineering/PROTOCOL.md |
| AC3210/12 dump, firmware 0.2.3 / @86 (openHAB forum, post 9, 2026-10-02) | `forum/openhab/t170501_posts.json` | https://community.openhab.org/t/170501/9 |
| AC0950/10 dump, firmware 0.3.3 / @86 (same thread, post 22) | same file | https://community.openhab.org/t/170501/22 |
| Decompiled-app notes | `src/kwesolowski_node-red-contrib-philips-airplus/docs/v3-protocol-reference.md`, `src/Ka3seBr0t_HA_Philips_Air_Plus/notes/properties.md`, `src/renaudallard_homeassistant_philips_homeid/custom_components/philips_homeid/{number,switch,fan,button}.py`, `dl06/hb-airplus/package/dist/state.js` | |
| Independent review with measurements (AC3220/10, dated 2026-10-06) | (WebFetch only) | https://housefresh.com/philips-3200-review/ |

Not found: a Philips document that lists the app's manual fan speeds for the AC3220, an Air+ help page that
names the lamp options, any status dump of an AC3220 on 2026 firmware, any mapping of `D03240` error bits for
purifiers, and any confirmation of a local filter-reset write on this family.

---

## 1. Official facts (what the hardware and the app have)

### 1.1 Specification sheet, AC3220/10 [V-doc `web06/prx/en_GB_specification.json`, `nl_NL_specification.json`]

| Item | Value |
|---|---|
| Product | "PureProtect 3200 Series Smart Air Purifier", CTN AC3220/10, start of production 2024-07-24, colour "Silver, Arctic White" |
| Air quality sensors | "PM2.5, Allergens" (nl: "PM2,5, allergenen"). **Temperature and humidity are not listed for the AC3220/10, but are listed for AC3210/12 and AC3221/13** (see 6.1) |
| CADR (particle, GB/T) | 520 m3/h; max room 135 m2 |
| Sound | 15 dB(A) min, 47.5 dB(A) max |
| Power | max 36 W; standby "<2 W"; 100-240 V (external 24 V adapter KA4801A-2402000EU per manual line 187) |
| Filter | "3-in-1 HEPA filter", layers "HEPA, Active Carbon", related accessory **FY3200**, recommended change **1 year** |
| Modes | Automatic mode: Yes. Sleep mode: Yes. **"Speed settings: Yes (5 levels)"** |
| Light | "Ambient night light: Yes"; air quality feedback "Colour ring, numerical"; interface "Digital (touch)" |
| Other | Child lock: Yes. Scheduler: "Yes (in app)". Wi-Fi 2.4 GHz. Voice control "Yes (Google, Alexa)" |

Feature texts [V-doc `web06/prx/en_GB_features.json`]: "double-fan design"; "The accessory package (FY3200)
contains both filters for the device"; "In the app, select Auto+ mode for AI technology that adapts to your
routine"; scheduling "Fresh Wake-up" and "Fresh Bedtime ... welcomes you with a cosy, warm night light";
"The purifier calculates filter life and alerts you when a replacement is needed".

### 1.2 User manual [V-doc `dl09/manual/um_eu.txt`, English section]

| Topic | What the manual says (line) |
|---|---|
| Radio | "Standard WiFi interface based on 802.11b/g/n/ax at 2.4GHz" (73); "Bluetooth version 5.2 (LE)" (75) |
| Parts | "B Particle sensor", "D Filter (FY3200)", "F Adapter (KA4801A-2402000EU)" (183-187). **No gas, temperature or humidity sensor is mentioned anywhere in the manual** |
| Buttons | Power, Mode switch, Light function. 3-second long presses: Child lock, Wi-Fi reset, Filter reset (controls overview, ~200-215) |
| Display icons | Auto mode, Medium mode, Sleep mode, Turbo mode, Wi-Fi indicator, PM2.5 display, **App-operated mode**, Child lock indicator, Filter cleaning alert, Filter replacement alert |
| Light sensor | "The light sensor is located beneath the power button." (218) |
| Colour ring | "The color of the air quality light is determined by the PM2.5 reading." <=12 Blue Good; 13-35 Blue-purple Fair; 36-55 Purple-red Poor; >55 Red Very poor (364-371) |
| Power-on | Starts "in the Auto mode with PM2.5 displayed"; after an off/on with mains kept, "will operate under the previous settings" |
| Modes on the device | "You can choose between the Auto mode, the Medium mode, the Turbo mode, or the Sleep mode by pressing the mode switch button. Additional operating modes can be selected in the Air+ app." Sleep: "After 3 seconds, the display lights turn off." |
| Allergy Sleep | "Allergy Seep mode [sic]: This mode can be enabled in the Air+ app ... your Sleep mode automatically adapts the fan speed in a similar way with the Auto mode, while keeping the sound level low." (424) |
| App-operated mode | "The appliance is operating a mode that is only available through the app, such as **additional manual fan speeds** or other modes that were customized in the app." (432) |
| Light function | Panel dims/turns off by ambient light. "You can press the light function button to switch to lamp mode: a cozy light ring around the control panel. Tailor the brightness of the cozy light in the Air+ app." (453) "You can press the button to turn off all lights and the control panel." (456) |
| Child lock | 3-second press, icon on the display |
| Filter cleaning | When the cleaning alert shows: vacuum the filter surface, then "Press and hold the ... button for 3 seconds to reset the filter cleaning time. - You can also reset the filter cleaning time via the Air+ app." (607-609) |
| Filter replacement | "healthy air protect lock": "If the filters are not replaced in time, the air purifier will stop operating and automatically lock" (622 ff.). Reset by 3-second press or "via the Air+ app" (692-694). Early replacement: unplug, replug, and "Within 15 seconds after power on" hold for 3 s (728) |
| Faults | Front cover not installed: "for safety reason, the appliance will stop operating". "Error code "E1" displays on the screen. The motor has malfunctions." (803). No other error code is documented |
| Not in the manual | timer, scheduler details, beep setting, standby monitoring, display brightness levels, number of manual speeds: all app-only |

Dutch names (for translations) [V-doc, Dutch section]: "Automatische modus", "Normale modus" (= Medium),
"Turbomodus", "Slaapmodus", "Allergie-slaapmodus", "App-gestuurde modus", "Kinderslot", "Waarschuwing filter
reinigen", "Waarschuwing voor filtervervanging", "lampmodus"; PM2.5 levels "Goed / Redelijk / Slecht / Zeer slecht".

### 1.3 Independent measurements [R, https://housefresh.com/philips-3200-review/ , AC3220/10, 2026-10-06]

Standby 1.1 W, Sleep 2.2 W, Medium 12.6 W, Turbo 31.1 W. "When set to lamp mode, the top of the 3200 emits a
nice, warm white glow." "You can enable 'Allergy Sleep' mode in the app". Filters "FY3200/30", two bonded
HEPA + carbon units with a pre-filter mesh. Useful for sanity checks (e.g. a power estimate per mode), not a
device API.

### 1.4 What exists physically - verdict

| Thing | Verdict | Basis |
|---|---|---|
| PM2.5 particle sensor | yes | manual, spec, dumps (`D03221`) |
| Allergen index | derived from the particle sensor, not a separate sensor | spec lists "Allergens" as a sensor reading; `D03120` |
| Gas / TVOC sensor | **no** | spec; issue #181 "without gas sensor"; no `D03122` in any 3200 dump; openHAB "the models have no gas sensor" (`CoapProfile.java:628`) |
| Temperature and humidity | **reported by the device** (`D03224` = 212, `D03125` = 47 in the AC3220/10 dump; the owner described the state as "47% humidity, 21.2 degC" [R, kongo09 #181]) although the AC3220/10 spec sheet omits them and the sibling sheets list them | conflict between V-doc and R-dump; the dump wins for an integration, but create the entities only when the keys are present |
| Ambient light sensor | yes (under the power button); drives display dimming, value not reported as a datapoint that anyone has identified | manual |
| Lamp ("cozy light ring", night light) | yes | manual, spec |
| Beeper | yes | manual ("The air purifier beeps"), `D03130` |
| Two fans, two FY3200 filter units | yes | features text, manual line 768 |

---

## 2. Key naming scheme

**Scheme: `D` + group (2 hex digits) + type/length code (1 char) + point id (2 hex digits).**

Evidence:

1. [V-code `dl09/cx3550/PROTOCOL_main.md`] The main MCU and the Wi-Fi module exchange TLV datapoints grouped by a
   one-byte group id: "Datapoints in TLV (Type, Length, Value) format". The table for group `0x03` ("Device
   state") lists point `0x02` (1 byte) power, `0x05` (1 byte) status LEDs, `0x0A` (1 byte) "Always 0x01",
   `0x0C` (1 byte) fan mode, `0x0D` (1 byte) "Actual fan state", `0x0F` (2 bytes) oscillation, `0x10` (1 byte)
   "Timer set value", `0x11` (2 bytes) "Timer remaining time", `0x30` (1 byte) beep. The same device's cloud
   shadow shows exactly `D03102`, `D03105`, `D0310A`, `D0310C`, `D0310D`, `D0320F`, `D03110`, `D03211`,
   `D03130` [V-code `src/Ka3seBr0t_HA_Philips_Air_Plus/notes/properties.md:35-58`]. Strings are typed `0x73`
   (ASCII "s") on the wire: the capture `03 73 0d 53 63 68 ...` is point 03 = name, `05 73 0a 43 58 33 35 35 30
   2f 30 31` = "CX3550/01" -> `D01S03`, `D01S05`.
2. Group meaning from the same document: `0x01` identity (read and written at power-up), `0x02` Wi-Fi state,
   `0x03` device state, `0x04` unknown (always zero), `0x08` unknown. Filters are group `05` (`D05xxx`,
   from dumps). On the cloud backend B the same groups appear as NCP "ports" (`Status`, `Control`, `Config`,
   `filtRd`, `filtWr`) [V-code `src/ShorMeneses_philips-airplus-homeassistant/custom_components/philips_airplus/models.yaml:10-15`].
3. Type codes seen: `1` = 1 byte, `2` = 2 bytes, `4` = 4 bytes, `S` = string, `R` = raw bytes sent as base64
   with a trailing newline (`D03R81`).
4. **1-byte values are signed in the JSON.** `D0310C` "reads -16 when powered off" on an AC4221 [R, kongo09
   #416] (= 0xF0), and the CX3550 mode 0x82 is reported as `-126` [V-code `properties.md:143-147`]. Parsers
   must not assume non-negative values or a closed enum.
5. Not everything maps 1:1: the UART point `01/0x0F` is a string holding the Wi-Fi module version ("0.8.6",
   written by the module) while the JSON has `D0110F: 3`; so do not derive meanings for `D011xx` from the UART
   table. [V-code, `PROTOCOL_main.md` "Initial startup"]

The app's own vocabulary: the Air+ app calls the three generations V1/V2/V3 (`f13979b = 3`: "V3: D03102 with
int 1/0") [V-code `src/kwesolowski_node-red-contrib-philips-airplus/docs/v3-protocol-reference.md:80-95`].
No source shows that the app documents the group/type/id scheme itself; the scheme above is supported by the
UART capture, not by app documentation.

---

## 3. Status dumps: union of keys on this family

Dumps used:

| # | Model | Device FW / Wi-Fi FW | Date | State | Source | Label |
|---|---|---|---|---|---|---|
| A | **AC3220/10** | 0.1.9 / `AWS_Philips_AIR_Combo@3.0` | 2024-11-02 | on, Auto, light off | kongo09 #181 (note 02 section 2.2) | R-dump |
| B | AC3210/12 | 0.2.3 / `@86` | 2026-10-02 | on, Auto, Auto+ on, lamp = air quality | openHAB forum 170501/9 | V-dump |
| C | AC0950/10 ("Unicorn" mini, `D0110C` 18) | 0.3.3 / `@86` | 2026-10-03 | on, Auto | openHAB forum 170501/22 | V-dump |
| D | AC2210/10 ("Cobra") | 0.2.1 and 0.2.3 / `@86` | 2026-01, 2026-06 | | kongo09 #306, tinkerologie #58 (note 04 section 4.2) | R-dump |
| E | AC4221/11 | 0.2.3 / `@86` | 2026-11-14 | value tables by diffing against app actions | kongo09 #416 | R |

Dump B verbatim (trailing alias fields added by the openHAB binding removed):

```json
{"D01102":0,"D01S03":"Schlafzimmer","D01S04":"Unicorn","D01S05":"AC3210/12","D01107":0,"D01108":3,"D01109":3,
"D0110A":0,"D0110C":19,"D01S0D":"688001001383","D0110F":3,"D01S12":"0.2.3","D01213":0,
"ProductId":"<product_id E>","DeviceId":"<device_id C>","otacheck":false,
"Runtime":328108,"rssi":-46,"wifilog":false,"blelog":-1,"free_memory":97904,
"WifiVersion":"AWS_Philips_AIR_Combo@86","StatusType":"status","ConnectType":"Online",
"D03102":1,"D03103":0,"D03105":101,"D03106":1,"D0310A":2,"D0310C":0,"D0310D":1,"D03110":0,"D03211":0,
"D03112":0,"D03115":0,"D0311F":0,"D03120":1,"D03221":1,"D03224":241,"D03125":46,"D0312A":1,"D0312B":1,
"D0312C":7,"D03130":0,"D03134":1,"D03135":1,"D03136":0,"D03137":1,"D03240":0,"D03180":1,"D03182":1,
"D0313B":20,"D03R81":"BQEBAgIBAgMD\n","D05102":3,"D05207":720,"D05408":9600,"D0520D":601,"D0540E":2870}
```

Differences between A (AC3220, 2024 firmware) and B (AC3210, 2026 firmware):

| Key | A: AC3220/10 0.1.9/@3.0 | B: AC3210/12 0.2.3/@86 | Reading |
|---|---|---|---|
| `D03112` | absent | 0 | added by newer firmware |
| `D03137` | absent | 1 | added by newer firmware |
| `D0313B` | absent | 20 | added by newer firmware |
| `aqit_ext` | 0 | absent | removed by newer firmware (a classic-generation leftover; a classic AC2939 has `"aqit":7,"aqit_ext":0`) |
| `blelog` | `false` | `-1` | type changed from boolean to integer |
| `free_memory` | 154416 | 97904 | different Wi-Fi firmware build |
| `D01S0D` | "688001001384" | "688001001383" | consecutive numbers per model (see 4.1) |
| everything else | same key set | same key set | |

**[I]** An AC3220/10 bought in 2026 and updated through the app should be expected to report the key set of
dump B (with `D01S05` "AC3220/10" and `D01S0D` "688001001384"). Entities must therefore be created from the
keys that are present, and re-checked when the firmware version changes.

Keys only on other family members: `D03122` gas index 1-4 (AC4220/AC4221); `D03104` (AC2210: 0, AC0950: 123;
display brightness on those models, used as the light key by `src/MaddogWarner_homebridge-philips-air-purifier-complete/philips_air_api.py:66`);
`D0110B` (AC2210/AC0950: 0). Not on the AC0950: `D03224`, `D03125`, `D03115`, `D0311F`, `D03135`, `D03137`,
`D03180`, `D03182`, `D03R81`, `D05102`, `D03106`, `D03112` (it does report `D03136` = 0 and `D0313B` = 20).

---

## 4. Datapoint table for the AC3220

Columns: **Dump** = value in A (AC3220/10, 2024) / B (AC3210/12, 2026). **RW**: R = report only, W = accepted on
`POST /sys/dev/control`, W? = written by another project or the app but never confirmed on a Unicorn device
over CoAP. **Conf.** = confidence in the meaning: H, M, L.

### 4.1 Group 01 and envelope fields (identity, housekeeping)

| Key | Meaning | Type | Dump A / B | RW | Source | Conf. |
|---|---|---|---|---|---|---|
| `D01S03` | Device name set in the app | string (UTF-8) | "Salon" / "Schlafzimmer" | R (app writes it) | all dumps; openHAB decodes UTF-8 | H |
| `D01S04` | Product range / platform codename | string | "Unicorn" | R | dumps; openHAB `GEN3_RANGE` (`CoapProfile.java:197`) | H |
| `D01S05` | Model id (CTN) | string | "AC3220/10" / "AC3210/12" | R | dumps | H |
| `D01S12` | Device (MCU) firmware version | string | "0.1.9" / "0.2.3" | R | dumps; UART point 0x12 = "0.1.7" on CX3550 | H |
| `D01S0D` | **12-digit product code, constant per model, not a serial number** | string | "688001001384" / "688001001383" | R | AC3210 = ...383, AC3220 = ...384, AC0950/10 = ...366, CX3550/01 = ...145, CX7550/01 = 688001006859 (one unit each). philips-airctrl labels it `serial_number` (`src/tinkerologie_philips-airctrl/src/philips_airctrl/device_info.py:33`) and puts it in discovery (`discovery.py:90`) | M (inference from the consecutive numbers; only one unit per model seen) |
| `D0110C` | "Capabilities" code the app uses to tell variants apart | int | 19 / 19 (AC0950: 18) | R | openHAB: "The capabilities the Philips app recognizes the small variant of the Unicorn range by" = 18 (`CoapProfile.java:199-201`) | M |
| `D01102` | unknown (0 on purifiers, 2 on CX3550 fan, 4 on AC3737, 5 on AMF765) | int | 0 / 0 | R | dumps. philips-airctrl says "error code" (guess, contradicted by non-zero values on healthy devices) | L |
| `D01107`, `D0110A`, `D01213` | unknown, always 0 | int | 0 | R | dumps; library guesses "warning code", "update available", "child lock (device level)" are unsupported | L |
| `D01108`, `D01109`, `D0110F` | unknown, 3 / 3 / 3 on every Combo device seen (`D01109` = 1 on AMF765) | int | 3 | R | dumps. UART group 02 has a similar pair for Wi-Fi LED state (`0x04` = connected), so a connection/provisioning state is plausible | L |
| `ProductId` | Cloud product id (per model) | 32 hex | <product_id A> / <product_id E> | R | dumps | H |
| `DeviceId` | Cloud device id (per unit); the only stable per-device identifier available locally | 32 hex | per unit | R | dumps | H |
| `WifiVersion` | Wi-Fi module firmware | string | `AWS_Philips_AIR_Combo@3.0` / `@86` | R | dumps | H |
| `Runtime` | Uptime of the Wi-Fi module in ms (resets on reboot) | int | 317641004 / 328108 | R | dumps | H |
| `rssi` | Wi-Fi RSSI dBm | int | -49 / -46 | R | dumps | H |
| `free_memory` | Free heap of the Wi-Fi module (bytes) | int | 154416 / 97904 | R | dumps | M |
| `StatusType` | "status"; briefly "control" after a command | string | "status" | R | #416; `properties.md:203` | H |
| `ConnectType` | "Online" (cloud link state as seen by the module) | string | "Online" | R | dumps | M |
| `otacheck`, `wifilog`, `blelog` | Firmware-update/log flags | bool or int | false / false / false or -1 | R | dumps | L |
| `aqit_ext` | Classic-generation leftover next to the threshold | int | 0 / absent | R | dump A; classic AC2939 dump | L |

### 4.2 Group 03 (state, settings, sensors)

| Key | Meaning | Type | Values | Dump A / B | RW | Source | Conf. |
|---|---|---|---|---|---|---|---|
| `D03102` | Power | int | 1 on, 0 off (standby) | 1 / 1 | **W** (confirmed over CoAP on AC4221 0.2.3/@86 [R #416]; must be a JSON integer, note 04 F15) | all projects | H |
| `D03103` | Child lock | int | 1 locked, 0 unlocked | 0 / 0 | **W** (confirmed on AC4221 [R #416]) | all projects | H |
| `D03105` | Display (control panel) brightness | int | 0 Off, 101 Auto (light sensor), 115 Low, 123 Bright | 0 / 101 | **W** partly: `0` confirmed to switch the light off; `101` did not switch it back on from local CoAP on an AC4221 @86 [R #416]. "It keeps reporting 101 when the purifier is off or in sleep, even though the lamp is off." "The app changes D03105 and D03135 together" | #416; openHAB `unicornBrightness()` (`CoapProfile.java:716-719`); kongo09/tinkerologie light | H (values), M (writability) |
| `D03106` | unknown, always 1 | int | 1 | 1 / 1 | R | present in A, B and AC2210, absent on AC0950. Library guess "child lock alternate" has no support. Candidates: light-sensor/auto-dim capability or state | L |
| `D0310A` | Function selector | int | **2 = purification** on every purifier seen (1 on the CX3550 fan; on combi devices 3/4 select turbo-or-fan / humidification) | 2 / 2 | W? (never needed on this model) | openHAB `ac3737Modes()` sends `D0310A` 2 or 3 (`CoapProfile.java:711-713`); kongo09 `NEW2_MODE_A` "value == 4" = humidification (`const.py:768-772`) | M |
| `D0310C` | Mode (and manual speed) | int (signed) | **0 Auto, 1-5 manual speed 1-5, 17 Sleep, 18 Turbo, 19 Medium**; reads -16 while powered off (AC4221 0.2.3) | 0 / 0 | **W** ("Fan, mode and child lock writes work normally over CoAP" [R #416]) | #416; kongo09 `philips.py:802-841`; openHAB `unicornModes()` (`CoapProfile.java:686-696`) | H for 0/17/18/19; **M for 1-5 on the AC3220** (see 5.2) |
| `D0310D` | Actual fan speed level | int | 0 idle/off, 1-4, **18 = top speed** (speed 5 and Turbo); 3 in Medium; 1 in Sleep; 0, 1 or 2 seen in Auto | 1 / 1 | R | #416; UART doc "Actual fan state"; openHAB `speedFallbackKey("D0310D")`; HomeID "reads 0 while auto idles the fan" (`sensor_descriptions.py:458-461`) | H |
| `D03110` | Switch-off timer setting | int | 0 off, **n+1 = n hours, 2..13 = 1..12 h**; `1` (30 min on the UART table) is not usable: coerced to 2 on a CX3550, "did nothing" on an AC4221 | 0 / 0 | W? (written by kongo09 select, openHAB, hb-airplus; verified by direct write on a CX3550 via cloud; read values 2 = 1 h, 3 = 2 h confirmed on AC4221 [R #416]) | `properties.md:222-246`; `CoapProfile.java:51,175`; `PROTOCOL_main.md` | H (encoding), M (CoAP write on Unicorn) |
| `D03211` | Timer minutes remaining | int | 0..720, counts down | 0 / 0 | **R only** (a write was ignored on the CX3550) | `properties.md:199`; #416 "60, 120" | H |
| `D03112` | Display/lights switch, **inverted**: 0 = display on, 1 = everything off | int | 0, 1 | absent / 0 | W? | openHAB `DISPLAY_SWITCH("dispon", "D03112", 0, 1)` (`CoapProfile.java:85`), channel "The display of the device is on". Fits the manual's "turn off all lights and the control panel". Not confirmed on a device (openHAB author: commands "have **not** been confirmed on a real device yet") | M |
| `D03115` | **Allergy Sleep** enabled | int | 1 on, 0 off | 0 / 0 | W? | openHAB `ALLERGY_SLEEP("allslp", "D03115", 1, 0)` (`CoapProfile.java:84`); feature confirmed by the manual; key is absent exactly on the models without the feature (AC0950, AC2210). philips-airctrl's "auto_mode" label is a guess | M-H |
| `D0311F` | unknown, 0 | int | 0 (toggled 1 -> 0 on a classic AC2939 while it stayed in Sleep) | 0 / 0 | R | dumps. philips-airctrl guess "sleep mode". Possibly a transient state of the sleep/display logic | L |
| `D03120` | Indoor Allergen Index | int | 1..12 (bands 1-3 good, 4-6 fair, 7-9 poor, 10-12 very poor, by analogy with the threshold steps 1/4/7/10) | 1 / 1 | R | all projects; HomeID "APK AirStatusPortProperties.indoorAirIndex" | H |
| `D03221` | PM2.5, ug/m3 | int (2 bytes) | 0..999 | 1 / 1 | R | all projects | H |
| `D03224` | Temperature x 10, degC | int (2 bytes) | 212 = 21.2 | 212 / 241 | R | all projects; owner's description in #181 | H |
| `D03125` | Relative humidity % | int | 0..100 | 47 / 46 | R | all projects | H |
| `D0312A` | Index shown on the display ("preferred index", classic `ddp`) | int | 0 = IAI, 1 = PM2.5 (2 = gas only on AC422x) | 1 / 1 | W? | kongo09 `NEW2_PREFERRED_INDEX` (`const.py:497`, map `520-523`); openHAB `GEN3_DISPLAYED_INDEX` writes `pm25 ? 1 : 0` and "the gas index (2) is not offered, as the models have no gas sensor" (`CoapProfile.java:203, 628-637`) | H (meaning), M (write) |
| `D0312B` | Index actually shown (classic `rddp`), mirrors `D0312A` | int | 0/1/2 | 1 / 1 | R | decompiled app: "`D0312B` ... Sensor mode (0=IAI, 1=PM2.5, 2=Humidity)" (`v3-protocol-reference.md:55`); classic dumps carry `"ddp":"1","rddp":"1"` side by side. kongo09 names it `NEW2_HUMIDIFYING` (`const.py:475`), which only makes sense on humidifiers | M |
| `D0312C` | **Air quality notification threshold** (classic `aqit`): the allergen-index level from which the app notifies | int | 1 Good, 4 Fair, 7 Poor, 10 Very poor | 4 / 7 | W? | openHAB `GEN3_THRESHOLD = "D0312C"`, accepts `1, 4, 7, 10` (`CoapProfile.java:202, 606-613`), channel text "Air quality level at which the Philips app sends a notification" (`channels.xml:161-175`); HomeID independently: "set_air_quality_threshold ... D0312C" from the APK's AirControlPort (`number.py:143-152`); observed values 4, 7, 4 fit. philips-airctrl's "air quality index" sensor label is wrong | M-H |
| `D03130` | Beep (key tones) | int | 100 on, 0 off | 100 / 0 | W? (verified on CX3550 via cloud; kongo09 switch) | `properties.md:173-174`; kongo09 `const.py:851-856`; UART "Beep on mode change ... the beeping on first power up and when turning on/off can only be disabled by physically cutting power to the buzzer" | H |
| `D03134` | **Standby monitoring**: sensors keep measuring while the purifier is off | int | 1 on, 0 off | 0 / 1 | W? | kongo09 `NEW2_STANDBY_SENSORS` (`const.py:495, 857-861`, not listed for AC22xx); openHAB `STANDBY_SENSORS("standby", "D03134", 1, 0)`; HomeID "sensor monitor in standby" (`switch.py:255-285`) | H (meaning), M (write) |
| `D03135` | Lamp function (light ring) | int | 0 off, 1 air-quality colour, 2 ambient / night light | 0 / 1 | **W partly**: `0` works; `1` and `2` were ignored or switched the lamp off on an AC4221 @86 [R #416] | #416; kongo09 map `const.py:500-504`; openHAB `lampModes()` | H (values), M (write) |
| `D03136` | unknown, 0 | int | 0 | 0 / 0 | R | adjacent to the lamp keys, but **also reported (0) by the lamp-less AC0950**, so it is not a lamp-only setting; the key behind the "brightness of the cozy light" that the manual says the app can tailor is not identified. philips-airctrl "lamp mode alternate" is a guess | L |
| `D03137` | Ambient light scene | int | 1 Warm, 2 Dawn, 3 Calm, 4 Breath (#416 calls them warm, dawn, soft, cool) | absent / 1 | W? (ignored from local CoAP on AC4221 @86: "D03137 stays at 1") | kongo09 `const.py:463, 958 ff.`; hb-airplus `effects = { Warm: 1, Dawn: 2, Calm: 3, Breath: 4 }` (`dl06/hb-airplus/package/dist/state.js:8`); AC3210 owner: the app "does allow changing the light color on my AC3210", options "correspond to the same options available for the HU1509/00 humidifier" [R tinkerologie #6] | M-H |
| `D0313B` | unknown constant 20 | int | 20 | absent / 20 | R | 20 on AC3210, AC2210, AC0950 and on the CX3550 fan, where no user action changed it (`properties.md:100, 179`). philips-airctrl "timer remaining (alt)" is wrong | L |
| `D03240` | Error / alert code | int (2 bytes) | 0 = none; purifier codes unknown (on humidifiers bit 8 = out of water) | 0 / 0 | R | kongo09 `NEW2_ERROR_CODE` (`const.py:472, 756-761`); openHAB maps it to the classic `err` channel | H (role), L (values) |
| `D03180` | Auto+ (AI auto mode) enabled | int | 1 on, 0 off (255 on a classic model without it) | 0 / 1 | W? | kongo09 switch `const.py:862-866`; features text | M-H |
| `D03R81` | Raw 9-byte table, base64 + newline; belongs to the Auto+ block (points 0x80-0x82) | bytes | A: `00 01 01 01 02 01 02 02 03`; B: `05 01 01 02 02 01 02 03 03`; classic AC2939: "000000000" | R | decoded here; values look like fan levels for a 3x3 grid. philips-airctrl "schedule data" is a guess | L |
| `D03182` | unknown, 1 (also 1 on the classic AC2939) | int | 1 | 1 / 1 | R | philips-airctrl guess "schedule enabled" | L |

### 4.3 Group 05 (filters)

| Key | Meaning | Type | Dump A / B | RW | Source | Conf. |
|---|---|---|---|---|---|---|
| `D05408` | Filter (FY3200) lifetime, total hours | int (4 bytes) | 9600 / 9600 (= 400 days of operation) | R | all projects | H |
| `D0540E` | Filter lifetime remaining, hours | int (4 bytes) | 9501 / 2870 | R; W? = reset by writing the total (see 5.9) | all projects | H |
| `D05207` | Filter cleaning interval, total hours | int (2 bytes) | 720 / 720 | R | all projects | H |
| `D0520D` | Hours until the filter surface must be cleaned | int (2 bytes) | 621 / 601 | R; W? = reset | all projects | H |
| `D05102` | Filter status bitmap | int | 3 / 3 (also 3 on AC3737) | R | "`D05102` ... Filter status bitmap ... g7/d.java:getFilters()" (`v3-protocol-reference.md:63`); philips-airctrl says "filter type" | L-M |

In dump A both counters are exactly 99 hours below their totals on a new unit, so they count operating hours
at the same rate **[I]**. `D0540E == 0` is the documented "healthy air protect lock" condition (the purifier
stops) **[I from manual]**.

---

## 5. Write payloads

Envelope (round 1): plaintext `{"state":{"desired":{"CommandType":"app","DeviceId":"","EnduserId":"", <keys>}}}`,
encrypted, `POST /sys/dev/control`. All values are JSON integers. Send one logical change per request and
confirm it from the next status push; several writes on this family are acknowledged and then ignored
(#416, note 04 F15).

### 5.1 Power

| Action | Keys |
|---|---|
| on | `{"D03102": 1}` |
| off | `{"D03102": 0}` |

The device resumes its previous mode ("will operate under the previous settings"). While off, `D0310C` can read
-16 and `D03105` stays 101; neither means anything.

### 5.2 Modes and manual speeds

| Target | Keys | Shown on the device |
|---|---|---|
| Auto | `{"D0310C": 0}` | Auto icon |
| Sleep | `{"D0310C": 17}` | Sleep icon, display off after 3 s |
| Medium | `{"D0310C": 19}` | Medium icon |
| Turbo | `{"D0310C": 18}` | Turbo icon |
| Manual speed n (1-5) | `{"D0310C": n}` | "App-operated mode" icon |

kongo09 and tinkerologie always add `"D03102": 1`; openHAB does not for the Unicorn profile (no `modePowersOn`,
`CoapProfile.java:50-54`). Sending both keys is the safer choice for `fan.turn_on(preset_mode=...)`.

**Does the AC3220 accept 1-5?** Probably yes; not proven on an AC3220.

- For: the AC3220/10 spec sheet says "Speed settings: Yes (5 levels)" [V-doc]; the manual says the app adds
  "additional manual fan speeds" shown as "App-operated mode" [V-doc]; on the sibling AC4221 (same "Unicorn"
  platform string) an owner recorded "1-5 manual speed 1-5" by diffing against app actions, with `D0310D`
  following 1-4 and reading 18 for speed 5 [R #416]; kongo09, tinkerologie and openHAB all send 1..5 for the
  family, and the 2024 AC3220 tester wrote "Tested. Works" without details [R #181].
- Against: nobody has posted an AC3220 status with `D0310C` in 1..5, and devices of this family are known to
  ignore out-of-range values silently (AC3737: "Protocol allows 1-16, but device ignores values >2",
  `v3-protocol-reference.md:45`).
- Consequence of `D0310D`: there are five physical levels (1, 2, 3, 4, top). **Speed 5 and Turbo run the same
  fan level (18); Speed 3 and Medium run the same level (3).** They differ only in the mode icon.

### 5.3 Display brightness

`{"D03105": 0}` off, `{"D03105": 101}` auto, `{"D03105": 115}` low, `{"D03105": 123}` bright.
The Air+ app writes `D03105` together with `D03135` [R #416]. Local "on" writes failed on an AC4221 @86; treat
anything but `0` as unverified until tested on the user's unit.

`{"D03112": 1}` all lights off, `{"D03112": 0}` back on (newer firmware only, unverified).

### 5.4 Lamp and ambient light

`{"D03135": 0}` lamp off; `{"D03135": 1}` air-quality ring; `{"D03135": 2}` ambient/night light;
`{"D03137": 1|2|3|4}` scene Warm/Dawn/Calm/Breath (only meaningful with `D03135` = 2; key absent on old
firmware). Candidate combined write, mirroring the app: `{"D03105": 101, "D03135": 2, "D03137": 2}` - this
exact payload switched the lamp **off** on an AC4221 @86 [R #416], so expect that ambient control may be
app-only on current firmware.

### 5.5 Child lock, beep, Auto+, Allergy Sleep, standby monitoring

| Setting | On | Off |
|---|---|---|
| Child lock | `{"D03103": 1}` | `{"D03103": 0}` |
| Beep | `{"D03130": 100}` | `{"D03130": 0}` |
| Auto+ | `{"D03180": 1}` | `{"D03180": 0}` |
| Allergy Sleep | `{"D03115": 1}` | `{"D03115": 0}` |
| Standby monitoring | `{"D03134": 1}` | `{"D03134": 0}` |

Auto+ modifies the Auto mode and Allergy Sleep modifies the Sleep mode; they are settings, not `D0310C` values.

### 5.6 Preferred index and notification threshold

`{"D0312A": 0}` allergen index, `{"D0312A": 1}` PM2.5. `{"D0312C": 1|4|7|10}`.

### 5.7 Timer

`{"D03110": 0}` off; `{"D03110": h + 1}` for h = 1..12 hours (2..13). Do not send 1. `D03211` then counts down
from `60 * h`.

### 5.8 Scheduler

No device key identified. Fresh Wake-up / Fresh Bedtime are app features; whether they are stored on the
device (`D03182`/`D03R81` are too small for timetables) or run from the cloud is unknown. Home Assistant
automations replace them.

### 5.9 Filter reset

No project resets Gen3 filters over CoAP, and nobody reported trying. Known facts:

- The app can do it ("You can also reset the filter lifetime via the Air+ app", manual 694).
- On the other cloud backend the app "writes the full lifetime back into the remaining-hours property on the
  filtWr NCP port (APK MujiFilterControlPort)": `D0520D = 720`, `D0540E = 4800` for AC0650/AC0651/AC1715
  [V-code `src/renaudallard_homeassistant_philips_homeid/custom_components/philips_homeid/coordinator.py:1335-1344`,
  `button.py:184-202`; same in `models.yaml:24-27`].
- tinkerologie's `filter_reset` action only knows Gen1/Gen2 keys and logs "total capacity unknown" for Gen3
  (note 03, lines 273-274).

Candidate payloads for an experiment, **untested**: `{"D0520D": <D05207>}` (720) to reset the cleaning timer,
`{"D0540E": <D05408>}` (9600) to reset the filter life. Read the totals from the status instead of hard-coding
them. The device may require a different port than `control` for group 05; if the write is ignored, the
buttons must not be offered.

---

## 6. Siblings and regional variants

### 6.1 Official differences [V-doc `dl09/prx/*.json`, `web06/prx/*.json`]

| Model | Series | Colour | Sensors per spec sheet | CADR | Filter | Max power | Other |
|---|---|---|---|---|---|---|---|
| **AC3220/10** | PureProtect 3200 | Silver, Arctic White | PM2.5, Allergens | 520 m3/h | FY3200, 1 year | 36 W | 5 speed levels; sold as /10 in NL, DE, UK, AU, SG, MY |
| AC3210/12 | PureProtect 3200 | Silk Beige | PM2.5, allergens, temperature, humidity | 500 m3/h (130 m2) | FY3200 | 36 W | |
| AC3221/13 | PureProtect 3200 | Dark grey | PM2.5, allergens, temperature, humidity | 520 m3/h | FY3200 | 36 W | |
| AC4220/12 | PureProtect Pro 4200 | Supernova Silver | PM2.5, **gas**, allergens, temperature, humidity | 600 m3/h | FY4200 | | |
| AC4221/11 | PureProtect Pro 4200 | Metallic black | PM2.5, **gas**, allergens, temperature, humidity | 600 m3/h (156 m2) | FY4200 "4-in-1" | 54 W | max 51.5 dB(A) |
| AC2210/10, AC2220/10 | PureProtect Quiet 2200 | Arctic White | PM2.5 | 400 / 420 m3/h | FY2200/30, **3 years** | 28 W | "Automatic display dimming"; range string "Cobra" |

The manual is shared by "AC3210/12 ... AC3220/12 ... AC3221/13" (asset description) and is the one linked from
the AC3220/10 page; an AC3220/60 page exists for India (`philips.co.in`, specification JSON has no usable rows).
Product pages for AC3220/12 return 404 in nl_NL and de_DE.

### 6.2 Differences that matter to an integration

| Aspect | AC3210 / AC3220 / AC3221 | AC4220 / AC4221 | AC2210 / AC2220 / AC2221 | AC0950 / AC0951 |
|---|---|---|---|---|
| `D01S04` | "Unicorn" | "Unicorn" (note 04) | "Cobra" | "Unicorn", `D0110C` = 18 |
| Gas index `D03122` (1-4) | no | yes | no | no |
| Preferred index `D0312A` | 0, 1 | 0, 1, 2 (gas) | 0, 1 | 0, 1 |
| Temperature / humidity keys | yes (dumps A, B) | yes | not in the AC2210 dump | no |
| Allergy Sleep `D03115` | yes | expected (same profile) | key absent in the AC2210 dump | no |
| Lamp `D03135` / `D03137` | yes | yes | yes | no |
| Display brightness | `D03105` 0/101/115/123 | same | also `D03104` | `D03104`/`D03105`, no Auto |
| Manual speeds | 1-5 (see 5.2) | 1-5 (observed) | 1-5 per integrations | none (speed is reported only) |
| Filter totals | 9600 h / 720 h | not in the material | `D05408` 19200 h | 9600 h / 720 h |
| Within the 3200 series | no functional difference found: same manual, same profile in kongo09, tinkerologie and openHAB; only colour and the CADR figure of the AC3210 differ | | | |

Model handling rule: match on the base model (`AC3220` before the slash) or on `D01S04` plus key presence, never
on the full CTN with region suffix. Homey's app enabled writing "per exact model ID" (`'AC3220/10', 'AC3210/12',
AC3221/13`) and left other suffixes read-only (note 05, line 452).

---

## 7. Proposed Home Assistant entity model (one device)

Device registry: manufacturer "Philips", model "PureProtect 3200 Series", `model_id` = `D01S05`,
`sw_version` = `D01S12` (the Wi-Fi version belongs in diagnostics or a disabled diagnostic sensor),
no `serial_number` (`D01S0D` is a model code, `DeviceId` is a cloud id), `connections` = MAC from DHCP discovery.
Unique id base = `DeviceId`. Every entity is created only if its key is in the status; the key set is
re-evaluated when `D01S12` or `WifiVersion` changes.

### 7.1 Fan (main entity, `name=None`)

- Features: `TURN_ON`, `TURN_OFF`, `PRESET_MODE`, `SET_SPEED`.
- `is_on` = `D03102 == 1`. Nothing else is read while off.
- `preset_modes = ["auto", "sleep", "medium", "turbo"]` - the four modes of the device's own mode button.
  Read from `D0310C` only (0, 17, 19, 18). Any other value -> `preset_mode = None`. Auto+ and Allergy Sleep
  stay switches.
- `speed_count = 5` (`percentage_step` 20). Write: 20/40/60/80/100 % -> `{"D03102":1,"D0310C":1..5}`.
- `percentage` read-back = the **actual** level from `D0310D`: 1 -> 20, 2 -> 40, 3 -> 60, 4 -> 80, 18 -> 100,
  0 -> 0, in every mode. That gives a live speed in Auto and Sleep, 60 % in Medium and 100 % in Turbo, and equals
  the commanded step in manual mode. (Both existing integrations return `None` in a preset.)
- Because speed 5 = Turbo and speed 3 = Medium at fan level, an alternative for a cleaner front panel is to write
  19 for 60 % and 18 for 100 %; keep that as a decision to test on the device, not a default.
- If manual speeds turn out to be rejected by the user's unit (no status change after the write), drop
  `SET_SPEED` at runtime and keep the presets.
- No extra state attributes.

### 7.2 Sensors

| Entity | Key | Device class / unit / state class | Category, default |
|---|---|---|---|
| PM2.5 | `D03221` | `pm25`, ug/m3, measurement | enabled |
| Indoor allergen index | `D03120` | none, no unit, measurement (1-12) | enabled |
| Temperature | `D03224` / 10 | `temperature`, degC, measurement, 1 decimal | enabled |
| Humidity | `D03125` | `humidity`, %, measurement | enabled |
| Filter life remaining | `D0540E` / `D05408` | %, measurement; computed with one decimal or floor-to-1 so that a non-zero remainder never shows 0 % (kongo09 #413) | diagnostic, enabled |
| Filter life remaining (time) | `D0540E` | `duration`, h | diagnostic, disabled |
| Filter cleaning due in | `D0520D` | `duration`, h (plus % of `D05207` if wanted) | diagnostic, enabled |
| Timer end | now + `D03211` minutes | `timestamp`; update only when the computed end moves by more than 90 s | enabled when a timer exists; avoids a state write every minute |
| Fan speed level | `D0310D` | none (redundant with the fan percentage) | diagnostic, disabled |
| Wi-Fi signal | `rssi` | `signal_strength`, dBm, measurement | diagnostic, disabled |
| Last restart | now - `Runtime` | `timestamp`, updated only when it jumps by more than 60 s | diagnostic, disabled |
| Error code | `D03240` | none (raw integer until codes are known) | diagnostic, disabled |

### 7.3 Binary sensors

| Entity | Rule | Class |
|---|---|---|
| Filter replacement needed | `D0540E == 0` | `problem`, diagnostic |
| Filter cleaning needed | `D0520D == 0` | `problem`, diagnostic |
| Problem | `D03240 != 0`, raw code as attribute | `problem`, diagnostic |

### 7.4 Switches (all `entity_category = config`)

| Entity | Key | On / off | Default |
|---|---|---|---|
| Child lock | `D03103` | 1 / 0 | enabled |
| Beep | `D03130` | 100 / 0 (`is_on` = value > 0) | enabled |
| Auto+ | `D03180` | 1 / 0 | enabled |
| Allergy sleep | `D03115` | 1 / 0 | enabled |
| Standby monitoring | `D03134` | 1 / 0 | enabled |
| Display | `D03112` | **0 / 1 (inverted)** | disabled until verified |

A switch whose key is missing must not exist (tinkerologie shows a missing key as "on", note 03).

### 7.5 Selects (config)

| Entity | Key | Options -> value | Default |
|---|---|---|---|
| Display brightness | `D03105` | off 0, auto 101, low 115, bright 123 | enabled |
| Lamp | `D03135` | off 0, air_quality 1, ambient 2 | enabled |
| Ambient light scene | `D03137` | warm 1, dawn 2, calm 3, breath 4 | enabled if the key exists |
| Displayed index | `D0312A` | allergen_index 0, pm25 1 | enabled |
| Timer | `D03110` | off 0, 1 h 2, ... 12 h 13 | enabled |
| Notification threshold | `D0312C` | good 1, fair 4, poor 7, very_poor 10 | disabled (it only affects app notifications) |

Display brightness is a select, not a light: the four values are not a brightness scale, and "auto" is a mode.
Modelling it as a dimmable light with an "auto" effect is what produced the "strange behavior of display
backlight" reports (kongo09 #160, #181). A `light` entity for the lamp (on = `D03135` 2, effects = scenes) is
only worth building after local lamp writes are proven on the user's firmware.

Every select and switch must treat the write as unconfirmed until the status shows the new value, and revert
the UI after a short timeout otherwise.

### 7.6 Buttons

| Entity | Action | Default |
|---|---|---|
| Reset filter cleaning timer | `{"D0520D": D05207}` | only after the write is verified (5.9) |
| Reset filter life | `{"D0540E": D05408}` | same; diagnostic/config category |

### 7.7 Never record, never expose as attributes

`Runtime`, `free_memory`, `StatusType`, `ConnectType`, `otacheck`, `wifilog`, `blelog`, `D03R81`, `D0312B`,
`D0313B`, `D03106`, `D0311F`, `D03182`, `D05102`, `D011xx`, raw `D03211` and raw `rssi` (unless the user enables
the diagnostic sensor). `Runtime` changes in every push, so any attribute or sensor based on it writes a new
recorder row per notification (kongo09 issue #395). Diagnostics download: redact `DeviceId`, `ProductId`,
`D01S03`, and the MAC/IP.

### 7.8 What the two existing integrations get wrong or miss for this model

| # | Issue | kongo09 | tinkerologie |
|---|---|---|---|
| 1 | Displayed-index select uses the Gen2 key `D03-42` (string values) although the device reports `D0312A` (integers) | yes: `PhilipsAC3210.AVAILABLE_SELECTS = [NEW_PREFERRED_INDEX]` (`philips.py:1173-1176`); permanently `unknown`, and selecting sends `{"D03-42": "IAI"}` (note 02, 2.3) | yes: `_CONFIG_AC3210` (`device_models.py:618-634`) |
| 2 | Allergy Sleep `D03115` | missing | missing |
| 3 | Standby monitoring `D03134` | description exists, not listed for the family | missing |
| 4 | Notification threshold `D0312C`, display switch `D03112` | missing | missing; library mislabels `D0312C` as "air quality index" |
| 5 | Timer `D03110` | select present per note 02's MRO simulation (notes 03/04 read the override as dropping it; either way it has a dead duplicate select) | missing |
| 6 | Ambient scene `D03137` | missing | present, also created when the key is absent |
| 7 | Display as a dimmable light with effect "auto" (`D03105` 115 for any brightness < 255) | yes | yes |
| 8 | Percentage is `None` in presets; `D0310D` not used | yes (sensor commented out) | disabled sensor only |
| 9 | Preset read-back needs an exact pattern including power; `D0310C` = -16 when off is not handled explicitly | yes | `fan_mode` select shows "auto" when nothing matches, also when off |
| 10 | Filter alerts as binary sensors, error as an entity | no | event entity only |
| 11 | Filter percentage rounds to 0 % (#413) | yes | same formula |
| 12 | Filter reset for Gen3 | none | action exists but does nothing for Gen3 |
| 13 | Device registry | `sw_version` = Wi-Fi version, `serial_number` = `DeviceId` | library reports `D01S0D` as serial number |
| 14 | `runtime` etc. as fan attributes (recorder noise) | yes | no |
| 15 | No verification that a write took effect (lamp/display writes are known to be ignored on @86) | optimistic | optimistic |

---

## 8. Open questions (need the user's device)

1. Key set and firmware of the user's unit (`D01S12`, `WifiVersion`); are `D03112`, `D03137`, `D0313B`,
   `D03224`, `D03125` present?
2. Does `D0310C` = 1..5 work, and what does `D0310D` report for each mode (expected 1/2/3/4/18)?
3. Which light writes work locally on current firmware: `D03105` 101/115/123, `D03135` 1/2, `D03137`,
   `D03112`? On an AC4221 @86 only "off" worked.
4. Do `D03115`, `D03134`, `D0312A`, `D0312C`, `D03130`, `D03180`, `D03110` accept local writes? (All are
   written by at least one other project, none has a published confirmation on a Unicorn device over CoAP.)
5. Filter reset: does writing the total to `D0520D` / `D0540E` on `/sys/dev/control` work?
6. `D03240` values for E1 (motor), front cover removed, and the filter lock.
7. Meaning of `D03106`, `D0311F`, `D03136`, `D0313B`, `D03182`, `D03R81`, `D05102`, `D011xx`: diff status
   pushes while changing one app setting at a time (cozy-light brightness, Auto+, schedules).
8. Does the device push status while off with standby monitoring disabled? (Relevant to the liveness design:
   with `D03134` = 0 and power off, nothing changes, so a push-on-change firmware stays silent.)
9. Is the temperature/humidity reading plausible on the AC3220/10 (the spec sheet omits those sensors)?

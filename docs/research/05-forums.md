# 05 - Community forums: user experience and tribal knowledge (AC3220 / PureProtect 3200 and siblings)

Research date: 2026-11-22. Angle: what users and third-party maintainers report in forums, not code analysis
(see 01-04 for protocol, integrations and GitHub issues).

## 0. Method, sources and access limits

All forum posts below were read from the forums' own JSON/raw endpoints (not from search-engine snippets), unless
marked otherwise. Raw dumps are kept for re-verification in
`scratchpad/forum/`.

| Source | How read | Coverage |
|---|---|---|
| HA forum, "Philips Air Purifier" thread 53030 (466 posts, 2018-05-11 .. 2026-08-31) | Discourse `posts.json?include_raw=true`, all 466 posts | complete; 2023-2026 read in full, 2020-2022 keyword-filtered then read |
| HA forum threads 750048 (CX3550), 1022131, 968133 (VLAN), 752984, 1012454, 998744 (HomeID), 544333 (NutriU/HomeID), 982874 | same | complete |
| Homey community thread 32151 (289 posts, 2020-07-07 .. 2026-11-22) | same | complete; 2025-2026 read in full |
| Homey NL thread 127966 "Philips luchtreiniger" (AC3220/10), Homey thread 160059 (HomeID app) | same | complete |
| openHAB community threads 170501, 153475, 149855, 128356 + official binding README | same + raw.githubusercontent.com | complete |
| ioBroker forum topic 84797 "Test Adapter philips-air v2.x.x" (36 posts, 2026-06-17 .. 2026-11-19) | NodeBB `/api/topic/84797` | complete |
| Domoticz forum topic 34116 "philips air purifier" | HTML | complete |
| simon42 community (German HA forum) threads 33946, 61216, 6072, 57654 | Discourse JSON | complete |
| Reddit | **reddit.com is blocked** (403 for curl, not reachable for WebSearch/WebFetch). Read only through the pullpush.io archive API, which is incomplete | partial |
| Tweakers / Gathering of Tweakers | **Not reachable**: curl gets "Access Denied ... DPG Media's Web Application Firewall" (HTTP 403), WebFetch/WebSearch refuse the domain. General web searches for Dutch terms returned no GoT topic | **not covered** |
| FHEM, Jeedom, Gladys, SmartThings, Hubitat forums | Discourse/web search | nothing relevant found |

Evidence labels used below:

- **[V]** I read the primary post and quote it verbatim (author handle, date, URL given).
- **[A]** verified to exist, but a single anecdotal report (n=1) - do not generalise.
- **[H]** hearsay or speculation by the poster.
- **[I]** my inference from combining sources.

Short URL forms: `HA#n` = `https://community.home-assistant.io/t/philips-air-purifier/53030/n`,
`Homey#n` = `https://community.homey.app/t/app-pro-philips-air-purifiers-humidifier-app-healthy-air-always/32151/n`,
`OH#n` = `https://community.openhab.org/t/philips-air-binding-5-2-0-0-5-3-0-0/170501/n`,
`ioB:pid` = `https://forum.iobroker.net/post/pid`.

---

## 1. Summary of what the forums say

1. **The AC3220/10 is a local encrypted-CoAP device of the "new generation" (D-code keys; the sibling AC3210/12
   reports the family name "Unicorn" in `D01S04`, and openHAB groups the AC3220 in its `unicorn` profile) and local
   control is reported working in the Netherlands** (HA#468, 2026-01-15). The same holds
   for the siblings AC3210/12, AC3221/13, AC4220, AC4221/11 on HA, Homey, openHAB and ioBroker. One owner in
   Australia with Wi-Fi firmware `AWS_Philips_AIR_Combo@86` / device firmware `0.2.3` got no reply at all
   (HA#470, 2026-04-02, unresolved); an AC3210/12 with exactly that firmware pair works on openHAB (OH#9, 2026-10-02)
   and an AC4220 on 0.2.3 works on HA once moved off a guest Wi-Fi (HA#462).
2. **I found no forum report of a firmware update that removed local CoAP from an AC3220 or a sibling.** The
   "newer firmware does not allow local connections" warning that scares buyers comes from the kongo09 README and
   is not model-specific. The models that verifiably do not answer on UDP 5683 (AC0650/AC0651, some AC1715) are a
   different hardware/cloud platform. For those, "ECONNREFUSED" (port closed) is reported, not a timeout.
3. **"Works, but not consistently" is the normal experience on every platform**, not only HA: Homey users of the
   3200/4200 report the app crashing several times a day, a Dutch AC3220/10 owner on Homey writes "Het werkt niet
   stabiel helaas" (2026-03-13), a HA CX3550 user on the tinkerologie integration "often find[s] it unavailable"
   (2026-08-22). The long-time HA maintainer described it as "totally random" (HA#393).
4. **The single most useful piece of tribal knowledge, repeated independently for five years and on four
   platforms: the device often says nothing until its state changes.** Users found that toggling the device
   (buttons or app) makes a hanging setup or a stale integration come alive. Maintainers of the ioBroker and
   openHAB integrations confirmed in 2026 with logs that newer devices "push only when something changes" and
   stay silent in standby, and both rebuilt their availability logic around that. This matches the firmware
   behaviour documented from GitHub issues in notes 01/04.
5. **Network preconditions matter and are a real source of "cannot connect"**: 2.4 GHz only, WPA2 (WPA3/transition
   mode broke it for one user), no guest network / client isolation, a routed VLAN works only if UDP 5683 is
   allowed both ways, mesh/AP steering can hurt, DHCP reservation recommended.
6. **Firmware updates are automatic and cannot be declined in the app; the only reported way to avoid them is
   blocking the purifier's internet access**, which several users have run for years with local control intact.
   Initial onboarding needs internet and the Air+ app.
7. **No working cloud alternative exists for this model in HA today.** HomeID-based integrations (HA and Homey)
   do not see Air+ CoAP purifiers; an ioBroker cloud/MQTT pull request was declined on 2026-11-19; Alexa/Google
   bridging gives commands only; no evidence of Matter or HomeKit support.

---

## 2. Every report found for AC3220 and the same family (AC3210, AC3221, AC4220, AC4221, AC2210/2220/2221)

| Date | Where | Author | Device / firmware | Software | Result (verbatim where quoted) | Label |
|---|---|---|---|---|---|---|
| 2024-12-11..22 | Homey#140, #143, #146 | xazac, Kai_Schmerer, Munnikie | AC4221/11, AC3421, AC4220/12 | Homey "Philips Air" | "The Philips AC4221 and AC3421 air purifiers are recognised but cannot be controlled." / "The Philips AC4220/12 cannot be controlled" | V |
| 2025-01-08 | Homey#152, #154 | Joseph | AC3220/10 | Homey app, device type "> 2020" | "Is AC3220/10 supported? I think it's a 2024 model, but trying to create a >2020 device for it doesn't seem to work" then "Actually it works now ... it shows values indeed. However when I use the power button or the slider in Homey, the purifier does not respond in any way." | V |
| 2025-01-11 | Homey#156 | Dennis_Bekker | AC3220/10 | Homey app | "can add it and it shows all values correctly, cant control the device from homey no button is working." Developer then added the model in a test build | V |
| 2025-01-21 | Homey#163 | Joseph | AC3220/10 | Homey test build | "Both this one and the regular version indicate in Homey "crashed" regularly." | V |
| 2025-01-16 .. 2026-03-13 | https://community.homey.app/t/philips-luchtreiniger/127966 | Edwin58, Walty, Lars_Dz | AC3220/10 | Homey app | 2025-06-04 "nee helaas lukt niet"; 2025-11-08 Walty: add as "Purifier >= 2020" by IP works; 2025-11-13 "Klopt, dank het werkt"; 2026-03-13 "Het werkt niet stabiel helaas." | V |
| 2025-08-10 | Homey#189 | cyberrage | 1x AC3421/13, 2x AC4221/11, 2x AC0951/13 | Homey app | the 3421/4221 "works fine"; app "kept crashing"; AC0951 read-only | V/A |
| 2025-12-15 | HA#457 | SMAW | asks about AC3220/10 before buying | - | "It's a kinda must for me that it will work with homeassistent" | V |
| 2025-12-15 | HA#458 | aceindy | - | kongo09 README | quotes: "Some of these models seem to have a newer firmware that does not allow local connections anymore..." and the list entry "AC3220" | V |
| 2025-12-27 | HA#461 | rik-c | AC4220, FW 0.2.3 | kongo09 integration | "I have a new AC4220 here with FW 0.2.3 and it isn't connecting." | V |
| 2025-12-28 | HA#462 | rik-c | same | kongo09 + `aioairctrl` | "I have it working! Turned out the HA integration didn't play nice with the air purifier being on the guest network wifi ... I did get data when I swithced to my home netwerk wifi instead of guest wifi. After that I tried the integration and it worked with manual configuration!" | V/A |
| 2025-12-28 | Homey#213 | PJ-AU | AC4221/11, AC2220/10 | Homey app | "they appear to connect to your app, however they don't display any data" | A |
| **2026-01-15** | **HA#468** | **jochemsiegel** | **AC3220/10, bought in NL** | "this integration" = kongo09 (reply to #458) | **"I've just purchased a AC3220/10 in the Netherlands, and this integration is working perfectly fine, no issues with firmwares."** (no firmware numbers given) | V/A |
| 2026-01-17 .. 2026-08-04 | Homey#224, #231, #233, #267, #275 | MichaelHomey, Ilyad_Razi, Frank_Verschoor | AC3221/13 | Homey 1.0.64 .. 1.0.77 | "is recognized and shows all information, but cannot be controlled"; "When I turn it on / off in the Philips App on my Phone, the homey pro recognizes, that power switched on/off. But I cannot switch it on / off via Homey."; "Changing the color of the LED ring also works."; fixed in test build 2026-08-01 ("I can turn it on and off and change the speed") | V |
| 2026-03-26 | Homey#243 | NickW | 3x "AC3200" + 1x "AC4200" | Homey app, TP-Link Deco mesh, assigned IP | "The app is working properly, but it's crashing multiple times a day for no reason ... even with one device it keeps crashing." | V/A |
| **2026-04-02** | **HA#470** | **fredskis** | **AC3220/10, bought in Australia; "Wi-Fi Firmware: AWS_Philips_AIR_Combo@86 and Device Firmware: 0.2.3"** | kongo09 + `aioairctrl` | **"no luck :( can't even get anything through aioairctrl"** - no follow-up, cause unknown | V/A |
| 2026-04-08 | Homey#249 | Anton_Wierenga | AC3420/10 (2-in-1 sibling) | Homey app | "App crashes regularly. I made a flow that automatically restarts the app as a workaround." "I have the impression the app only crashes when the device is in off/inactive state" | V/A |
| 2026-04-14 | Homey#261 | Edwin_Biemond (dev) | AC4221/11, AC3221/13 | Homey app | "reading all values from your devices won't be any problem. to control them I need to add your version to. some code." | V |
| 2026-08-18/23 | ioB:1351888, ioB:1352293 | TT-Tom (maintainer) | AC3221 | ioBroker.philips-air 2.0.0 | AC3221 "(Luftreiniger der neuen Generation) wird unterstützt" - built from one owner's debug log | V |
| 2026-09-09/13 | Homey#281, #283 | MvL72 / Edwin_Biemond | PureProtect 3200 | Homey app | dev: "reading for sure ... already support these. 'AC3220/10', ''AC3210/12', AC3221/13" | V |
| 2026-09-27 | https://community.openhab.org/t/philips-air-binding-4-0-0-0-5-0-0-0/149855/34 | ollo | AC3210 | openHAB binding (old build) | thing "becomes online after some time", warning "Initializing handler ... takes more than 5000ms", "I'm not receiving any updates" | V/A |
| 2026-10-02 | OH#9 | ollo | AC3210/12, `"D01S12":"0.2.3"`, `"WifiVersion":"AWS_Philips_AIR_Combo@86"`, `"D01S04":"Unicorn"` | openHAB binding (reworked build) | "with the new jar I'm finally able to receive updates from my AC3210" - full status dump posted (see section 9) | V |
| 2026-10-04 | OH#25 | marcel_verpaalen (maintainer) | profile `unicorn`: "AC2210, AC2220, AC2221, AC3210, AC3220, AC3221, AC4220, AC4221" | openHAB binding | reading confirmed on AC3210/12; "The control commands follow the Philips app and the Home Assistant integration, and have **not** been confirmed on a real device yet." | V |
| 2026-11-16/17 | https://community.homey.app/t/app-pro-philips-homeid-community-app-and-device-testing/160059/7 .. /12 | medenjara, ugrbnk | "PureProtect 3200 Series ... AC3360/11" and AC4220/12, "firmware 0.2.1 (auto-updated)" | Homey HomeID (cloud) app + old CoAP app | HomeID cloud pairing: "No compatible cloud device was Found."; local: "the old local CoAP Homey app can read their sensors and toggle `light_mode`, but cannot control power or fan speed"; dev: "neither appears in the cloud registries used by its current pairing flow. I'm investigating local CoAP support" | V/A |

Reading of this table [I]:

- Every platform that tried could **read** these models as soon as they were added as a generic CoAP device.
  **Control** failed wherever the software selects its command set by an exact model-ID whitelist (Homey), until the
  model was added. That is a mapping problem, not a connectivity problem, and it is the most frequent complaint for
  this family on Homey.
- Only two HA-forum data points exist for the AC3220 itself (one works, one does not), plus two Homey owners
  (works, "not stable"). The sample is too small to say how reliable the AC3220 is on HA; the evidence about *why*
  it is unreliable comes from siblings and from maintainers (sections 4 and 7).
- "AC3360/11" appears nowhere else in my sources; treat the model number as unverified (possibly a regional or pet
  variant of the 3200 series; the poster lists a "Fur Capture Boost" mode).

---

## 3. Dated timeline (all models), with firmware and what users did

### 2019-2020: HTTP era ends, CoAP begins

- 2020-01-21, HA#79, sollan (AC1214): app capture shows the device "only communicating via udp on port 5683. All
  TCP ports seems to be closed". [V]
- 2020-01-29, HA#83, woockie: tcpdump of the app: "it communicates with the purifier only over UDP (coap) and
  mostly with amazonaws over TCP". [V]
- 2020-07-07, Homey#1, Edwin_Biemond: "since late 2019 philips moved away from http to coap". [V]
- 2020-10-31, HA#131, ondrabanov: Air Matters diagnostics for an AC3033/10: "Firmware Version: AWS_Philips_AIR@54.2
  ... Local Connected: true Remote Connected: true Status: Localcontrol". (So the 2020 app did use the local
  channel when on the same LAN.) [V]
- 2020-10-26, HA#127, alander: reserved the IP in the router "so it didn't change between renewals". [V]

### 2021: polling crashes devices; observe arrives; October OTA breaks things

- 2021-02-14, Domoticz, devguy (https://forum.domoticz.com/viewtopic.php?t=34116, post p268783), AC3829/10:
  "don't use this for continuously polling like Domoticz. The fundamental wrong way that py-air-control reads out
  the sensor values make the network stack of the device crash after a certain time. This can be solved by
  disconnecting the device from the power... The device expects clients that are interested in updates to subscribe
  using the COAP protocol. The device keeps pushing updated values to the client without any additional request."
  [V/A] - the earliest clear statement that repeated sync+poll hurts the device and that observe is the intended
  mechanism.
- 2021-03-01, HA#178, woockie: betaboon's integration "disconnects after a random time too and crashes the
  integration. Restarting HA helps." HA#180, RT1080: "services continue to respond even after it crashes, only
  sensors don't update." [V]
- 2021-03-19..27, HA#183/#191: runs of ~36 h, 1.5 days, 10 days before the stream stops. AC2889 on software 1.0.7,
  `AWS_Philips_AIR@62.1` (HA#192). [V]
- 2021-03-21/22, HA#185-#188: purifier on a guest network fails; "After moving the purifier to main network, it
  all worked fine." (d95HA, AC4236). kongo09: "I had it on a different VLAN which made it tricky for the Coap
  messages to reach HA." [V]
- **2021-10-05..09 OTA wave.** HA#197, woockie: "I forgot to block the internet connection of one of my air
  purifiers. It upgraded itself the firmware and from that time I can't see it in my home assistant." HA#200: after
  removing the internet block "it works again properly locally too" [A - the only report that local control needed
  internet, and it was during/just after an update]. HA#201, GSzabados (AC3829/50): "Something is wrong with that
  new firmware ... It just stopped reporting. Both to Air Matters (Clean Home) and to HA. Actually it was
  responding to commands from HA." HA#202, inso22: an AC2889 "completely unusable" even in the apps. HA#205:
  "the issue is definitely the firmware and it is out for months", pointing to
  https://github.com/betaboon/aioairctrl/pull/5, /pull/4 and https://github.com/rgerganov/py-air-control/issues/93. [V]
- 2021-12-08, HA#216, kongo09: "when I change something in the AirMatters app, it is immediately reflected in Home
  Assistant. But when I call a service, it doesn't work most of the time. It's like listening works, but not
  talking." HA#227: even the `aioairctrl` CLI "stopped reporting updates even before HA stopped receiving
  updates". [V]
- 2021-12-15, HA#226, Rikkie80: "if I shut down and start the purifier via the dedicated app just before restarting
  HA, integration is successful most of the time". HA#228, RT1080: "If the device is not recognized during ha
  restart a manual toggle will work and make it appear ... service calls typically also revive the device in ha ...
  I do not get rid of the errors in my log though. 1000's per day. This is the case since the October updates".
  [V] - first sightings of "a state change wakes it".
- Firmware seen: AC2889 `AWS_Philips_AIR@67.5` (HA#214, 2021-12), AC3033 `Ms3331` / `AWS_Philips_AIR@68.3` (HA#235).

### 2022: kongo09 takes over; reconnect timer; "reload the integration"

- 2022-01-06, HA#250, kongo09: "Mine are unavailable most of the time. The integration is essentially broken since
  Philips did a firmware update over-the-air." [V]
- 2022-02-09, HA#263/#264: speculation that lost UDP messages are not retransmitted correctly. [H]
- 2022-04-09, HA#271: kongo09 `v0.9.3-beta.1` "brings an attempt at reconnections (thank you @mhetzi)". HA#272,
  RT1080: "i have hundreds of these errors per day by the way. Best to add an ignore in your logger config." [V]
- 2022-04-10, HA#276, kongo09: "The Clean Home+ app is not using the local CoAP connection but the cloud.
  Unfortunately, the API is not public. Philips has invested a bit into this and now Alexa and Google Home are
  integrated. IFTTT uses it as well. I've written to Philips and asked for access but they haven't even replied." [V/H]
- 2022-04-10, HA#277, RT1080: purifiers on a different VLAN work; "To avoid further firmware upgrades following the
  last f*-up by Philips i blocked all internet communication ... odd behavior in the past where a reboot of ha
  would render the purifier unavailable unless it was on during reboot." HA#290: "Biggest challenge is setting up
  the purifier which can only be done whilst maintaining an internet connection" (he onboarded through a phone
  hotspot with the same SSID as his no-internet network). [V/A]
- 2022-04-11..13, HA#291-#315: devices register the DHCP hostname `mxchip` (older: `MiCO`), MAC prefixes
  `b0:f8:93`, `04:78:63` (Shanghai MXCHIP), one `e8:c1:d7` on an HTTP-era unit. HA#315, woockie: in the app's
  diagnostic mail "sometimes local connection is set to 'no'". [V]
- 2022-04-22..25, HA#327/#337/#338/#344/#358/#362: the stream "always" dies "after loss off power (moving between
  outlets) and after some time (a few hours to a day)" (jutonium). GSzabados: "That is normal ... The device stop
  sending updates to HA, as being a Local Push setup. Try to reload the integration"; "reloading fixed the no
  update issue. You can build an Automation to this" using `homeassistant.reload_config_entry`. aceindy observed
  the opposite pattern: "a restart of HA fixes it ... a restart of the philips does not help ... philips remains
  accessible by (cloud) app al the time." [V]
- 2022-05-21, HA#364, djalexnl (AC4236, v0.10.7): "after I restart homeassistant it hangs on loading the
  integration until i do something with the airpurifier, change mode on the device or turn off or on... then the
  integration loads"; and "Ha (or node red) turns it .. the device turns on but then after few seconds the button
  turns off (not the device) and the state is out of sync". [V/A]
- 2022-10-23, HA#371, kongo09: "Philips devices are super unreliable over encrypted CoAP ... For some people on old
  firmware it works well, for most people on newer firmware it's an unresolvable pain ... unplug your device, wait
  a few seconds, plug it back in ... after some time (an hour, a day, who knows?) it will become unresponsive
  again." [V]

### 2023: new D-code devices; firmware @73 stabilises some units

- 2023-01-21, HA#386: first AMF765/10 dump with D-codes (`'D01S04': 'Pegasus'`, `'D01S12': '0.8.5'`,
  `'WifiVersion': 'AWS_Philips_AIR@76'`). [V]
- 2023-02-12, HA#389, RT1080: "Philips pushes them out. But why would you want a Fw update? The Philip updates
  continue to break the integration. Personally I set my purifiers up on a no internet vlan to avoid further fw
  updates". [V]
- 2023-03-07, HA#392/#393: README "Word of Caution" quoted; kongo09: "For myself, it is totally random. Right now
  it works. A week ago it wasn't." [V]
- 2023-04-22, HA#396, jutonium: two AC2889 "received firmware updates due to me not paying attention when setting
  up the new router. But all the problems of the past seem to be solved now. The filters connect to the 2,4GHz even
  though the router provides a 5GHz Network with the same name ... the connection to HA seems to be stable for
  about a month now." Firmware `software_version: 1.0.7`, `wifi_version: AWS_Philips_AIR@73.1`. [V/A] - a firmware
  update that *improved* things.
- 2023-08-12, HA#403 (AC3829, v0.15.0): "When i'ts going down I just reboot HA or turn the AC3829 off/on and the
  connection is restored." [V]
- 2023-09-15..19, HA#406-#409, lintmars (AC3829/10): cannot ping or ARP the purifier from other Wi-Fi hosts although
  the app works; "fixed. turns out to be the issue with dual mode WiFi. I have forced my HA machine to use 2.4Ghz
  band and then it works now." [V/A]

### 2024: "do newer devices still talk CoAP?"

- 2024-02-16, HA#415-#419: AC0650 never answers; AC0850 "Connected to Wifi and Auto Discovered by Home
  Assistant." [V]
- 2024-06-27, Homey#120, Edwin_Biemond: "AC0650/10 is an issue ... this device never responds back"; Homey#121:
  "the app has a poll interval of 2 minutes". [V]
- 2024-09-26 .. 10-14, simon42 (https://community.simon42.com/t/6072/5, /7 and
  https://community.simon42.com/t/33946/6, /8): 4000i (AC4236) units lose Wi-Fi and "müssen neu angelernt werden";
  the unit "nahe zum Fritzbox Repeater - Mesh" is the unstable one; firmware "WLAN Firmware: AWS_Philips_AIR@75.3,
  Gerät-Firmware: Ms4418"; "das wacklige WLAN des Geräts und die nur auf Reverse Engineering beruhende HA
  Integration (Entwickler Top aber Philips macht dicht)". [V/A]
- 2024-11-02..29, HA#423-#429: three AC1715/10 "cannot connect"; CX5120 `aioairctrl ... status --json` hangs;
  kongo09: "There were a few reports of newer devices that don't work - maybe the API got closed for them?" [H];
  eight days later mattrayner: "Interestingly, without me changing anything, its started working". [V/A]
- 2024-12-10, HA#430, GSzabados: "No of those apps has an update firmware function, it happens automatically ...
  for forcing an update ... unplug the device, wait a minute, plug it back and turn it on. Once connected to the
  wifi and internet it will try to update the firmware automatically." [V/H]
- 2024-12-16, HA#431, Paul1865 (AC1715/11): `ConnectionRefusedError: [Errno 111] Connection refused (ECONNREFUSED,
  received through errqueue)`. kongo09: "That looks like the connectivity problem that many people experience."
  [V] - [I] it is not: a refused UDP port means nothing listens on 5683, unlike the usual timeout.
- 2024-12-22/24, Homey#150/#151: Homey app "moved away from polling to observing". [V]

### 2025: AC3220 shows up; network lessons; cloud-only small models

- 2025-01-01/02, HA#440-#444, vlagged (AC0951/13, not yet onboarded): in setup-AP mode the purifier is `10.0.0.1`,
  answers "UDP 53 ... and to port 30123 on TCP" with JSON
  `{"type":"deviceinfo",...,"data":{"option":55,"name":"AirPurifier","type":"Unicorn","modelid":"AC0951/13","swversion":"0.0.0","bind_token":"<<redacted>>"}}`;
  the APK references `com/gaoda/sdk/bean/coap`. [V/A] (Useful for a future local-onboarding feature; note the
  AC0951 also calls itself "Unicorn".)
- 2025-01-01, HA#442, RT1080: "setting it up with the Philips app is fine. If you want to prevent it from updating
  its firmware then best to block internet access". [V]
- 2025-02-28 .. 04-21, HA#445-#449: Google Assistant SDK workaround (section 8). [V]
- 2025-03-06, HA#448, martymarty004: AC0650/10, "MAC: E4:BC:96:xx:xx:xx, Wi-Fi FW: 1.6.4, Device FW: 0.1.9",
  static DHCP, `ECONNREFUSED`; "Did the firmware update kill local access completely?" 2025-05-12, HA#450: "scan
  for open ports on the device, but found none." [V] The same handle posted the same day on Reddit about an
  AC0651/10: "I get a connection refused"
  (https://www.reddit.com/r/homeassistant/comments/1ism7ww/philips_air_purifier_600_series_integration/mry91tg/),
  so this is one more owner, not two.
- 2025-06-09/10, Homey#182-#184: timeouts with Homey and purifier on different mesh nodes; dev: "homey on lan will
  help , sometimes they don't allow inter wifi connections". [V]
- 2025-07-02, https://community.home-assistant.io/t/philips-cx3550-fan-integration/750048/12, SniperJack
  (2x CX3550/01): constant timeouts on setup, then "I started pinging the device ... and just left the ping running
  ... Boom! It worked ... I repeated this for both fans, multiple times, and it worked every time." Post 13,
  Trial_Master: "I still got the timeouts following your process, in addition I tried turning the fan on/off via
  the app and that seemed to make the HA Integration happy." Post 16 (2026-06-18): "It doesn't seem to be working
  for me." [A]
- 2025-07-17, HA#452, RT1080: "prevent the machine from communicating over the internet. This breaks the Philips
  app but avoids firmware updates which have in the past been known to break certain functionality." [V]
- 2025-08-10, Homey#190, Edwin_Biemond: "the security on top of coap on philips devices is not the best. plus no
  fimrware updates. think the ac3x,4x,5x devices are more expensive and have better hardware to handle these local
  connections. philips app itself is using these cloud connections instead." [V/H]
- 2025-10-10 / 11-29, HA#453/#454: AC1715 "on 0.0.9" - "Cannot connect to device" (two users, unresolved);
  HA#455, kongo09: "not all devices and not all versions of all devices speak the same protocol. Maybe it depends
  on the firmware version, I don't know." [V]
- 2025-11-29, HA#456, aceindy: "my new wifi access points was configured initially to use one SSID for both 5Ghz
  and 2.4Ghz. It was also set up to offer WPA2 as well as WPA3. After i created a 2nd wifi network at 2.4 Ghz and
  took out WPA3 it instantaneously connected and it hasn't lost connection ever since ... recap: Air purifier
  requires 2.4Ghz and no WPA3, only WPA2". [V/A]
- 2025-12-27, HA#460 (CX5120): "HA said cannot connect. I stopped the device and retried and then it was able to
  connect." [A]
- 2025-12-27..29, HA#461-#465: AC4220 guest-Wi-Fi story (section 2). HA#464: "Routers with built-in Guest wifi
  networks isolate all clients from all clients". [V]
- 2025-12-30, https://community.home-assistant.io/t/device-on-other-vlan/968133/1: purifier on an ASUS "guest
  network pro" IoT VLAN cannot be added; "the moment i shift the air purifier to the same network as HA, it work
  fine." [V/A]

### 2026: the AC3220 year

- 2026-01-04, HA#467, kongo09 on AC0650: "it doesn't use encrypted CoAP for local connections in the way most
  other devices do. It's unclear to me if it offers local connections at all." [V]
- 2026-01-15, HA#468: AC3220/10 NL works (section 2).
- 2026-03-02, HA#469, kongo09: "new release with a major refactoring of the underlying `aioairctrl` library". [V]
- 2026-03-25, https://community.home-assistant.io/t/998744: "Philips HomeID Integration" announced (section 8).
- 2026-04-02, HA#470: AC3220/10 AU fails (section 2).
- 2026-04-02..16, Homey#245-#262: crashes on AC3200/AC4200/AC3421. Dev: "it seems TP Link Deco is tricky or the
  coap library I use cannot handle all situations" (#245); "I see a lot of corrupted or half messages , invalid
  hash etc." (#251); a UniFi user found the purifier "sticking to the AP on the 2nd floor, even though it's located
  on the 3rd floor" (#255) and still crashed after fixing that (#262). [V]
- 2026-06-01, https://community.home-assistant.io/t/1012454/2, aceindy (AC1214, AC2729, AC3829 on kongo09):
  "working stable enough ... maybe once a month i need to reset them, maybe once a year I have to re-join them on
  my wifi." [V/A]
- 2026-06-18 .. 08-29, ioBroker releases 1.4.0-2.1.0 fix "bricht nicht mehr alle paar Minuten ab" and "verbinden
  sich nicht mehr alle paar Minuten neu, obwohl die Verbindung in Ordnung ist" (section 7). [V]
- 2026-07-18, Reddit r/homeassistant, u/-3rdPlace- (4000i):
  https://www.reddit.com/r/homeassistant/comments/1uzsdy2/philips_air_purifier_home_assistant_more_dynamic/ -
  "The purifier was making a surprisingly large number of connections to external servers. Once local control
  through Home Assistant was working reliably, I blocked its internet access in my firewall. It is still available
  on the local network". [A, via archive]
- 2026-08-22, https://community.home-assistant.io/t/1022131/1, Exclaim8934 (CX3550, tinkerologie integration):
  "often find it unavailable ... pinning it and restarting HA helped me to get it available again (sometimes also
  connecting first via the official app), but this is all but smooth." [V/A]
- 2026-08-27, Homey#276, Loranga (AC2889): "responds to ping and HTTP locally, but 20 direct CoAP sync attempts to
  UDP/5683 received no response." [A] - an HTTP-firmware unit.
- 2026-09-10..14, Homey#282-#285, manni0607 (AC2889, "Device Firmware Version: 1.0.7, WLAN Firmware Version: 91.0.1
  (91.1)"): "Since a recent firmware update on Philips' end, the device is no longer reachable in Homey or Apple
  Home"; dev: "you need to use > 2020 devices . that uses coap ... try to fix ip dhcp address and wifi 2.[4] ghz ,
  not shared with 5ghz." - "Thank you very much, that helped!" [V/A] - a firmware update that switched an old unit
  from HTTP to CoAP, not one that removed local control.
- 2026-10-01..14, openHAB rework and merge (section 7).
- 2026-10-25, Homey#289: test build to "fix the cpu bug and aggressive retries on sync, plus every device has it
  own sync counter." [V]
- 2026-11-16..19: Homey HomeID thread (cloud registry does not list Air+ purifiers) and ioBroker decision not to
  merge the cloud PR (section 8).

---

## 4. Symptoms of "inconsistency" and what they turned out to be

| Symptom as users describe it | Reports | Explanation offered in the forums (and by whom) |
|---|---|---|
| Setup hangs / "Timeout, cannot connect" although ping works | HA#391, #394, #423, #471, 750048/3, /7, 982874, simon42 33946 | (a) network isolation; (b) device silent until something changes: "it hangs on loading the integration until i do something with the airpurifier" (HA#364); "sobald ich den Ventilator eingeschaltet hatte, waren auch alle Datenpunkte da" (ioB:1351912); HA#460 |
| Entities go unavailable / flap every few minutes while the device is fine | HA#392 log `[coap] Connection loss was not expected.`, HA#228 "1000's per day", ioB:1351923, 1022131 | False-positive watchdog. ioBroker maintainer after a controlled test (ioB:1352841): "Dein Ventilator pusht nur, wenn sich etwas ändert ... Die Stille, die als 'Verbindungsabbruch' im Log stand, war also nie ein Fehler - der Adapter hat sie nur falsch gedeutet." |
| Sensor values freeze, commands still work | HA#180, #201, #327 | observe stream died silently (see 01/04: observation must be renewed) |
| Values update, commands are ignored | HA#216, #219 | not explained in the forums; kongo09: "listening works, but not talking" |
| Works for hours/days, then dead until power cycle | HA#183, #191, #371, README | "the network stack of the device crash[es]" under polling (Domoticz, 2021) [A]; Homey dev: "pull the plug for some minutes" |
| Dead after HA restart | HA#225, #277, #361; HuisAutomatisering README | "Philips devices can need up to 3 minutes after a Home Assistant restart or after removing the integration before they accept a new connection." (README, verified text) |
| Dead after the purifier lost power | HA#327, #338, #362 | "The CoAP connection has to be reestablished" - reload integration |
| Purifier drops off Wi-Fi and must be re-onboarded | simon42 6072/5, /7, 61216/4; HA 1012454/2 | mesh repeater proximity; WPA3 transition mode (HA#456) |
| Read works, control does nothing | Homey (section 2), OH#22 | model not in the command-mapping whitelist |
| State bounces back after a command | HA#364 | optimistic state overwritten by a stale notification [I] |
| Third-party app "crashes" several times a day | Homey#163, #189, #243, #248, #249, #266 | dev: corrupted/partial frames, invalid hash, invalid JSON, sync retry storm (Homey#251, #256, #287, #289) |

Workarounds users actually settled on (frequency order):

1. **Power-cycle the purifier** (10 s to a few minutes unplugged), sometimes plus HA restart - kongo09 README,
   HA#142, #217, #362, #403, Homey#78, #127, #287.
2. **Toggle the device** via its buttons or the app to make it emit a status frame - HA#226, #228, #364, #460,
   750048/13, 1022131.
3. **Reload the config entry / restart HA**, optionally from an automation (`homeassistant.reload_config_entry`) -
   HA#344, #358; Homey equivalent: a flow that restarts the app (Homey#249).
4. **Fix the network**: main LAN instead of guest, dedicated 2.4 GHz WPA2 SSID, DHCP reservation - section 6.
5. **Block internet** to freeze firmware - section 5.
6. **Silence the log** (`logger` filter for the aiocoap "Connection loss was not expected" error) - HA#272.
7. **Give up on local control**: smart plug (the purifier starts when power returns - simon42 33946/5, 750048/9),
   Google Assistant SDK (HA#445-#449), or buy another brand (simon42 61216, Reddit 1iqyovn).

---

## 5. Firmware updates and local control

### 5.1 What is actually reported

| Device group | Evidence | Verdict |
|---|---|---|
| Classic CoAP units (AC2889, AC3033, AC3829, AC4236 ...), Wi-Fi firmware `AWS_Philips_AIR@NN` | October 2021 OTA degraded reliability (HA#197-#205, #250); `@73.1` reported to improve it (HA#396); units on `@91.1` in 2025-2026 still speak CoAP (openHAB 153475/35, Homey#282-#285) | Updates changed **behaviour**, never removed CoAP. On AC2889/AC3829 an update even moved the device from HTTP to CoAP (openHAB README: "Some models, such as the AC2889 and AC3829, used HTTP with early firmware and use CoAP after a firmware update.") |
| Small/cheap models AC0650, AC0651 (also AC0720 per note 04) | `ECONNREFUSED` on 5683, no open ports, MAC `E4:BC:96`, numeric Wi-Fi firmware `1.6.4` (HA#448, #450, Reddit) | Never had local CoAP. Different platform. Not a firmware regression [I]; kongo09 HA#467 |
| AC1715 | worked on CoAP for years (e.g. Homey#121 2024-06, AC1715/11 "no problems"); from late 2024 new units refuse (HA#423, #431 ECONNREFUSED, #453 "on 0.0.9", simon42 61216/6). The HomeID integration README lists "AC0650, AC0651, AC1715" as "MUJI" devices on the "FUSION" cloud relay | Two variants exist. Whether a firmware update converts an old AC1715 or it is a hardware revision is **unknown** |
| Airfryers etc. on HomeID | README of renaudallard/homeassistant_philips_homeid, section "Cloud-only Firmware" (text verified): "do not install any firmware update the Philips app offers ... The app does not label the FUSION migration ... There is no way back. FUSION firmware never generates local credentials" | Verified precedent at the same vendor (Versuni) that an ordinary-looking update can remove local control. Not purifier evidence |
| **AC3220 / Unicorn family** | works on device 0.2.3 + `AWS_Philips_AIR_Combo@86` (OH#9, HA#462); "firmware 0.2.1 (auto-updated)" still readable locally (Homey 160059/7); one unexplained failure on 0.2.3/@86 (HA#470) | **No report of local control being removed.** Risk for the future cannot be excluded |

### 5.2 Is the AC3220 affected by the "newer firmware" warning?

The warning in the kongo09 README (`src/kongo09_philips-airpurifier-coap/README.md:62`: "Note: Some of these models
seem to have a newer firmware that does not allow local connections anymore...") is a generic caveat above the
whole model list; the AC3220 is simply one list entry (`README.md:96`). The tinkerologie README says the same in
other words (`src/tinkerologie_ha-philips-airpurifier/README.md:18`: "Some firmware versions disable local CoAP or
stop responding to it intermittently."). Neither names the AC3220. [V]

For the one failing AC3220 (HA#470) a likely explanation [I] is not "CoAP removed" but the push-on-change
behaviour of `Combo@86` firmware described in notes 01/04: a plain `aioairctrl status` waits for a reply that the
device only sends on the next state change, so on an idle unit the tool appears to "get nothing". This is
unconfirmed for that user.

### 5.3 Can updates be avoided?

- Updates are pushed automatically; the apps have no "update"/"decline" control (HA#389, #430). An update attempt
  is triggered after a power cycle with internet available (HA#430) [H]. Status dumps carry an `otacheck` flag
  (`"otacheck":false` in OH#9 and HA#434) - meaning unverified.
- **Blocking internet for the purifier is the only avoidance method reported**, used long-term by RT1080 (no-internet
  VLAN since 2022: HA#277, #389, #442, #452), fakemoth (HA#340), a 2026 Reddit user (section 3) and recommended
  as optional in the HuisAutomatisering fork README ("block the purifier's internet access. Then the Philips app
  and cloud stop working, but a firmware update can no longer switch off local control."). [V]
- Costs: the Air+ app, schedules made in the app, Alexa/Google stop working. Onboarding itself needs internet
  (HA#290). One 2021 anecdote where local control only came back after the block was lifted (HA#200) - possibly an
  interrupted update. [A]
- Nobody in the forums lists the hostnames to block. Other sources name AWS IoT; the HomeID README names
  `ats.prod.eu-da.iot.versuni.com` for the HomeID/FUSION relay (not verified for Air+ purifiers).
- Nobody reports a downgrade path.

---

## 6. Network-level tips that matter

| Topic | What is reported | Sources | Label |
|---|---|---|---|
| Band | Purifier is 2.4 GHz only. A combined 2.4/5 GHz SSID caused failures to join or to stay connected on older firmware; a dedicated 2.4 GHz SSID fixed it | HA#396, #456; Homey#101, #130 ("My Wify has 2.4 and 5 Ghz on the same SSID, that was the problem"), #284/#285 | V, several independent |
| Security mode | WPA2/WPA3 transition mode broke connectivity; WPA2-only fixed it "instantaneously" | HA#456, 752984/28 | A |
| Guest network / client isolation | Guest Wi-Fi blocks HA -> purifier even when the user expects one-way reachability | HA#188, #462-#465, 968133 | V, several |
| VLAN | Works routed for some (HA#277 RT1080, HA#340 fakemoth "different VLAN with no internet, wasn't a problem"), fails for others (HA#185, #275, 968133, openHAB 128356/8). Requirement stated by the HuisAutomatisering README: "Allow only Home Assistant -> purifier on UDP 5683 (stateful, so the answers are allowed back)" | mixed | V |
| Discovery | kongo09 auto-discovery is DHCP-based (hostname `mxchip`, MXCHIP OUIs - HA#291-#316), so it only works when HA sees the DHCP traffic (same broadcast domain). openHAB discovers by sending `coap://<broadcast>:5683/sys/dev/info` and to multicast `224.0.1.187` (OH#24 log) | V |
| mDNS / IGMP | Suggested as culprit by forum helpers in the VLAN thread (968133/2, /6) but **no evidence** these devices use mDNS; local control is unicast UDP 5683. No forum report ties a failure to IGMP snooping | H |
| IPv6 | rik-c guesses "maybe IPV6 isn't supported on the guest wifi" (HA#462). aiocoap logs show `UDP6EndpointAddress 192.168.x.x` because it uses a dual-stack socket; no evidence the purifier needs IPv6 | H |
| Mesh / roaming | Units behind a mesh repeater are the unstable ones (simon42 6072/7); purifier "sticking" to a far AP (Homey#255); TP-Link Deco called "tricky" (Homey#245); Homey dev asks for "no mesh" and a wired hub (Homey#251, #253). A Linksys Velop user had no problem (HA#362) | A, several |
| Wi-Fi client isolation between bands | HA host had to be on 2.4 GHz for one router (HA#409) | A |
| DHCP | Reserve the address. A changed lease is "usually" why a working setup stops (atdr homebridge README, verified text); recommended in HA#127, #448, Homey#284, HuisAutomatisering README | V |
| "Ping trick" | Keeping a ping running from the HA host made setup succeed for one user on two CX3550; not reproducible for others | 750048/12, /13, /16 | A |
| Internet | Not needed for local control once onboarded (several long-term reports); needed for onboarding | section 5.3 | V |
| RSSI | Devices report `rssi` in every status frame (e.g. -46 in OH#9) - usable as a diagnostic entity | V |
| Security | "The Philips CoAP protocol uses a fixed, publicly known key and no authentication: every device that can reach the purifier on your network can read and control it." (HuisAutomatisering README) | V (README text) |

Concurrency (other local clients, the app):

- tinkerologie README troubleshooting row (`README.md:167`): "Device unavailable | Stop other local CoAP clients
  that access the same device. If the connection stays unavailable, power-cycle the device." [V]
- HuisAutomatisering README: "Using the Philips app at the same time as Home Assistant tends to make this worse,
  because both compete for the same encrypted session." [V text; mechanism unproven]
- atdr/homebridge-philipsair-platform README and its author on Reddit (u/notforfooduse, 2026-09-10,
  https://www.reddit.com/r/homebridge/comments/1qs007r/philips_air_600800i_integration/p908rdl/): "These purifiers
  serve **one connection at a time**"; "It might take up to 90 seconds to respond"; a switched-off unit "can
  legitimately stay silent for half an hour". [V text; claim is the author's]
- Homey dev to a user who ran `philips-airctrl` next to Homey: "don't use philips-airctrl , pull the plug for some
  minutes, restartt the homey app" (Homey#287). The user then stopped the CLI and Homey still failed (Homey#288),
  so the second client was not the (only) cause there. [V]
- Counter-evidence: in 2020 the app and the HA integration worked together (HA#67, HTTP era); in 2021 changes made
  in the app showed up in HA immediately (HA#216); kongo09 says the app talks to the cloud, not locally (HA#407).
  Whether today's Air+ app opens a local CoAP session on the same LAN is **not established** by any forum post.

---

## 7. How the other ecosystems fare, and what they do differently

### Homey - "Philips Air" (com.athom.philipsair, Edwin_Biemond)

- Transport history: HTTP -> CoAP in v0.0.23 (2020-07); **polling every 2 minutes** until December 2024
  (stated by user DirkG in Homey#121); **observe since 2024-12-22/24** ("now working to move away from polling and do observing ... should
  also work better now with 2 or more devices", Homey#150/#151).
- Reliability after the switch: the thread turns into crash reports through 2025-2026 (section 2). Diagnoses by
  the developer: timeouts/"No response received for sync call", "corrupted or half messages , invalid hash",
  "invalid json ... I think sometimes I got part of the data", a CPU bug from "aggressive retries on sync", and a
  shared sync counter across devices (fixed 2026-10-25: "every device has it own sync counter"). There is a
  user-facing "Add 60 seconds delay" setting (Homey#276).
- Device model: user picks a coarse type ("Purifier >= 2020", "Purifier + Hum >= 2020"); **control commands are
  enabled per exact model ID** (`'AC3220/10', 'AC3210/12', AC3221/13`), so new region suffixes read fine but
  cannot be controlled (Homey#200: "you got AC3039/14 and only added AC3039/10").
- Standing advice: fixed DHCP address, 2.4 GHz-only SSID not shared with 5 GHz, no mesh, hub on Ethernet, unplug
  the purifier for minutes, re-add the device.
- Developer's view of the cause: weak device hardware and no firmware fixes; the Philips app uses the cloud
  (Homey#190); adding a cloud-only small model "will break devices of ac3000 etc" (Homey#239).

### openHAB - Philips Air binding (marcel_verpaalen; merged for openHAB 5.3, PR
https://github.com/openhab/openhab-addons/pull/21901, announced OH#40 on 2026-10-14)

- 2019: HTTP port of py-air-control; 2021: CoAP (Eclipse Californium); 2024-01-29: "Use observeAndWait to keep
  better connectivity"; 2025-08: broke with Californium v4 in openHAB 5 (153475/25).
- 2026-10 rework (OH#5, verified text): "CoAP devices in standby no longer go offline after two minutes. The
  binding pings them with a method they answer in standby, and restarts the observe relation when they respond
  again."; "CoAP status updates are pushed from the device to the handler. The old approach slept and polled on the
  shared scheduler."; "Commands and refreshes run in order ... This also fixes some command races and key
  renewal."; "Fixed key exchange and connection leaks, and the observe relation left behind when a thing is
  disposed."; "Values the device doesn't send now show as NULL instead of 0."
- Liveness rule in the official README (verified): "CoAP devices push their state changes, so they are not polled.
  ... When no update has arrived for the refresh interval (at least 30 seconds), the binding checks whether the
  device still answers. A device that sends no updates, for example in standby, stays online as long as it answers
  this check. The thing goes offline when the device neither sends an update nor answers within twice the refresh
  interval (at least 60 seconds)." Default `refreshInterval` 60 s.
- Device profiles detected from the reported model, with manual override and persistence across restarts
  (`unicorn` for the AC3220 family, key style `D03102`). The profile is stored so that "Commands right after a
  restart therefore use the correct field names" (OH#25).
- Observed side effect of pure push: PM2.5 updates "nearly every 2-3 seconds" while running (OH#13, #15) - users
  asked for rate limiting. An unplugged CoAP unit stayed "Online" with stale data in the old build (149855/38).

### ioBroker - philips-air adapter (TT-Tom, forum topic 84797)

- 1.4.0 (2026-06-18): "Die Verbindung zu CoAP- und HTTP-Geräten ist jetzt deutlich zuverlässiger: Mehrere Fehler,
  die zum Absturz des Adapters, zum Einfrieren der Verbindung oder zum Verhindern der Wiederverbindung führen
  konnten, wurden behoben." 1.5.0 (2026-06-24): "Die CoAP-Verbindung bleibt nun stabil und bricht nicht mehr alle
  paar Minuten ab".
- 2.0.0 (2026-08-23): per-model mapping because "die neueren CoAP-Geräte dieselben internen Codes mit
  unterschiedlicher Bedeutung belegen"; models AC2889 (all classic), AC3221, CX3550, CX7550, Generic. Tip for
  users: plain names like `pwr`/`pm25` mean classic device, codes like `D03102` mean new generation.
- 2.1.0 (2026-08-29), after a three-phase test by a CX7550 owner (ioB:1352634, ioB:1352841): running - frames only
  while settings were changed, then 11 minutes of silence; **standby - "69 Minuten lang kein Ton vom Gerät, 11
  Nachfragen des Adapters, 11-mal geantwortet - und kein einziges 'connection lost'"**; unplugged - "nach 5 Minuten
  'lost', Wiederholungen mit 30 / 60 / 120 Sekunden Abstand", errors logged for the first three attempts only, one
  power-cycle hint, reconnect "sofort" after plugging in. Release note: "Ruhige Geräte senden nur, wenn sich etwas
  ändert. Die Werte stehen dann eine Weile unverändert im Objektbaum - das ist normal".
- 2.3.0 (2026-10-26): new instances start as "Generic" (sensors only) and the log names the model the device looks
  like.

### Domoticz - roldoe/domoticz-philips-air (2021)

Observe-based plugin written because polling through py-air-control crashed the AC3829's network stack (section 3).

### Homebridge - @atdr/homebridge-philipsair-platform (2026)

Shells out to `aioairctrl`; README stresses one connection at a time, up to 90 s for a reply, and DHCP
reservations. Detects the register style ("dashed registers" vs "dash-less") per device at runtime.

### Pattern across ecosystems [I]

Every project went through the same three stages: (1) polling with a fresh key-sync per poll (unstable, can hang
the device), (2) observe with a silence watchdog (flapping, because silence is normal), (3) observe plus a cheap
"are you there" probe and backoff, plus per-model profiles. HA's two integrations are at stage 2-3 (see 02/03);
openHAB and ioBroker reached stage 3 in autumn 2026 and report quiet logs afterwards. No ecosystem reports having
eliminated the need for an occasional power cycle.

---

## 8. Alternative routes mentioned for this model

| Route | Status for AC3220 | Evidence |
|---|---|---|
| Air+ cloud (OAuth + AWS IoT MQTT) in HA | No HA integration found in any forum. ioBroker PR https://github.com/iobroker-community-adapters/ioBroker.philips-air/pull/406 ("Cloud-Erweiterung") was reviewed and **not merged**: Bluefox 2026-11-18 (ioB:1363794) "Das ist eine Cloud-API, die nicht offiziell ist. Wenn Versuni dort etwas ändert, landen die Issues bei dir"; TT-Tom 2026-11-19 (ioB:1364071) "dass wir den PR nicht mergen werden" | V |
| Philips HomeID integration (HA, renaudallard) | **Not applicable.** Forum announcement (998744, 2026-03-25) says "Air Purifiers: AC0650, AC0651, AC series", but the README (verified) restricts purifiers to "AC0650, AC0651, AC1715 ... Cloud relay (FUSION MQTT)" and states: "Not supported: ... the older Philips air devices that use the local encrypted **CoAP** protocol". It does read the Air+ app's cloud account (`com.philips.air`) for those three models | V |
| Philips HomeID app for Homey (ugrbnk) | Tried with an "AC3360/11" and AC4220/12 on 2026-11-16/17: "No compatible cloud device was Found"; dev: models are not "in the cloud registries used by its current pairing flow" | V/A |
| Google Home via HA "Google Assistant SDK" | Works as a command-only bridge: "turn on ac1715", "turn off ac1715", "turn on auto mode on ac1715", "turn on sleep mode for ac1715"; "You don't get the data back"; mode commands failed on an HU5710 | HA#445-#449 | A |
| Alexa | Retail listings say Alexa/Google compatible; kongo09 (HA#276, 2022) confirms cloud skills exist. No HA forum report of bridging an AC3220 through Alexa | H |
| IFTTT | Mentioned once as existing in 2022 (HA#276). Nothing since | H |
| Matter / HomeKit | **Nothing found.** Web search for Air+ Matter support returned only Alexa/Google/Siri-shortcut statements. Homey#282 shows people bridging to Apple Home through third-party hubs. Users who need Matter are steered to SwitchBot (simon42 61216/3, /17) | not found |
| ESPHome / hardware mod | No project for the AC3220. Closest: https://github.com/1RandomDev/philips-cx3550-homeassistant replaces the fan's "MXChip EMC6069-P" Wi-Fi module ("uses the BK7235 microcontroller, which is not supported by LibreTiny yet") with an ESP32 speaking the documented UART protocol, exposing MQTT. The CX3550 runs the same Wi-Fi firmware line (`AWS_Philips_AIR_Combo@86`, note 04) as the AC3220 family, so the same module family is plausible but unverified for the AC3220. HA forum 874395 documents the PM1003PH particle sensor inside an AC0830 | V (project) / I (applicability) |
| Smart plug | Purifier resumes when power returns (reported for AC5659 and CX3550); on/off only | simon42 33946/5, 750048/9 | A |

Protocol side-note from the CX3550 hardware project (verified in its `reverse-engineering/PROTOCOL.md`): the
main MCU and the Wi-Fi module exchange TLV datapoints in numbered groups, e.g. group `0x03` "Device state", point
`0x02` (1 byte) = power, `0x0C` (1 byte) = mode, `0x0F` (2 bytes) = oscillation, strings typed `0x73` ("s"); the
module "constantly polls groups 0x02, 0x03 and 0x04" and "If the device state (group 0x03) changes, it is
published to the mobile app via cloud MQTT." [I] This explains the CoAP key names: `D` + group (2 hex) + length
or type (`1`, `2`, `4`, `S`, `R`) + point (2 hex) - `D03102` = group 03, 1 byte, point 02 (power);
`D0320F` = group 03, 2 bytes, point 0F; `D01S05` = group 01, string, point 05 (model id). It also explains why
the Wi-Fi module only pushes on change.

---

## 9. Reference data posted in forums

AC3210/12 status as logged by openHAB (OH#9, 2026-10-02, user ollo) - same family and firmware pair as reported
for the AC3220/10 in HA#470:

```
{"D01102":0,"D01S03":"Schlafzimmer","D01S04":"Unicorn","D01S05":"AC3210/12","D01107":0,"D01108":3,"D01109":3,
"D0110A":0,"D0110C":19,"D01S0D":"688001001383","D0110F":3,"D01S12":"0.2.3","D01213":0,"ProductId":"...",
"DeviceId":"...","otacheck":false,"Runtime":328108,"rssi":-46,"wifilog":false,"blelog":-1,"free_memory":97904,
"WifiVersion":"AWS_Philips_AIR_Combo@86","StatusType":"status","ConnectType":"Online","D03102":1,"D03103":0,
"D03105":101,"D03106":1,"D0310A":2,"D0310C":0,"D0310D":1,"D03110":0,"D03211":0,"D03112":0,"D03115":0,"D0311F":0,
"D03120":1,"D03221":1,"D03224":241,"D03125":46,"D0312A":1,"D0312B":1,"D0312C":7,"D03130":0,"D03134":1,"D03135":1,
"D03136":0,"D03137":1,"D03240":0,"D03180":1,"D03182":1,"D0313B":20,"D03R81":"BQEBAgIBAgMD\n","D05102":3,
"D05207":720,"D05408":9600,"D0520D":601,"D0540E":2870, ...}
```

(The trailing `"name"`, `"modelid"`, `"pwr"`, `"pm25"`, `"rh"`, `"temp":24.1` fields in the post are aliases added
by the openHAB binding, not sent by the device. `D03224` 241 = 24.1 degC, `D03125` 46 = 46 % RH, `blelog` hints at
a BLE-capable "Combo" Wi-Fi module.)

Firmware pairs reported in forums:

| Model | Device FW | Wi-Fi FW | Date | Local CoAP | Source |
|---|---|---|---|---|---|
| AC3210/12 | 0.2.3 | AWS_Philips_AIR_Combo@86 | 2026-10 | yes | OH#9 |
| AC3220/10 (AU) | 0.2.3 | AWS_Philips_AIR_Combo@86 | 2026-04 | no reply (unresolved) | HA#470 |
| AC4220 | 0.2.3 | n/a | 2025-12 | yes (not on guest Wi-Fi) | HA#461/#462 |
| "AC3360/11", AC4220/12 | 0.2.1 "latest ... auto-updated" | n/a | 2026-11 | read + light only on Homey | Homey 160059/7 |
| HU4209/00 | 0.7.7 | AWS_Philips_AIR_Combo@86 | 2026-09 | yes, read and write via aioairctrl (`set -I D03128=30`, `set -I D03102=0`) | Homey#277, #279 |
| AMF765/10 | 0.8.5 | AWS_Philips_AIR@76 | 2023-01 | yes | HA#386 |
| AC2939/10 | Ms2106 / 1.0.6 | AWS_Philips_AIR@79 | 2026-10 | yes | OH#24 |
| AC4236/14 | Ms4418 / 4.1.8 | AWS_Philips_AIR@75.3 (2024-10) | 2024-2026 | yes | simon42 6072/7, Homey#286 |
| AC3829/50 | 1.4.0 | @69.1 (2022-04), @91.1 (2025-09) | | yes | HA#285, openHAB 153475/35 |
| AC2889/10 | 1.0.7 / 1.0.8 | @62.1, @67.5, 68.3, @73.1, 91.1 | 2021-2026 | yes | HA#192, #214, #240, #396, #434, Homey#282 |
| AC3033/10 | Ms3331 / 3.3.1 | @68.3, @69.1 | 2021-2024 | yes | HA#235, #434 |
| AC0650/10 | 0.1.9 | 1.6.4 (MAC E4:BC:96) | 2025-03 | no, port closed | HA#448 |
| AC1715 | 0.0.9 | n/a | 2025-10 | "Cannot connect" | HA#453 |
| AC2729 | 0.1.0 / 0.1.4 | "8" | 2022-2024 | HTTP only | HA#374, #428 |

Mode codes for the newer register generation as observed by a Homey user (160059/7): "modes are reported via fan
speed codes like "AUTO", "17" for Sleep, "t" for Turbo, while `purifier_mode` remains `null`" (these are the Homey
app's capability names, not device keys). [A]

---

## 10. Open questions the forums do not answer

1. Why did the Australian AC3220/10 (0.2.3 / `Combo@86`) return nothing to `aioairctrl` (HA#470)? Network, push-only
   first frame, or a regional firmware difference? No follow-up exists.
2. Which firmware does a late-2026 Dutch AC3220/10 ship with or auto-update to, and does it still behave like
   0.2.3 / `Combo@86`? HA#468 gives no version numbers.
3. Does the current Air+ app open a local CoAP session when the phone is on the same LAN, and does that disturb a
   second client? Asserted by READMEs, never demonstrated in a forum post.
4. Is the AC1715 change to cloud-only a firmware migration or a hardware revision? If it is firmware, the same
   could in principle happen to the AC3220.
5. Which cloud endpoints must be blocked to stop OTA while keeping DHCP/NTP harmless, and does the device degrade
   (LED state, reconnect loops, reboots) when it cannot reach the cloud for months? Long-term users report no
   problems but give no detail.
6. Is WPA3-transition incompatibility real for the `Combo` Wi-Fi module of the AC3220, or only for older MXCHIP
   modules (the report is for AC1214-era hardware)?
7. Tweakers/GoT and most of Reddit could not be read; Dutch-language experience with the AC3220 may exist there.

---

## 11. Design implications for a new HA integration (from the forum evidence)

1. **Availability must not depend on receiving frames.** Treat silence as normal; mark the device unavailable only
   when an explicit, cheap probe goes unanswered (openHAB: check after 30-60 s of silence, offline after 2x;
   ioBroker: probe every 5 min in standby, "lost" after ~5 min). Keep last known values while reachable.
2. **Setup must not require a status frame.** Config flow should succeed on a successful key-sync / device-info
   exchange and tell the user to press a button on the purifier if no status arrives, instead of "cannot connect".
   This single change addresses the most common forum complaint (timeouts at setup that vanish when the device is
   toggled).
3. **Never poll with a fresh sync per request; one long-lived session, one command at a time, timeouts on
   everything, exponential backoff (30/60/120 s ...) on reconnect, and a quiet log** (log "lost" once and
   "restored" once). Repeated syncs are what users and maintainers associate with hung devices and CPU storms.
4. **Per-device state**: own sync counter, own lock, own backoff per purifier (Homey's shared counter was a bug
   source with multiple devices).
5. **Persist the detected model/profile** so commands work immediately after a restart, and choose the command
   set by register style and family (`D01S04` = "Unicorn"), not by exact model string with region suffix.
6. **Tolerate garbage**: truncated or undecryptable frames and invalid JSON must be dropped and counted, never
   raise.
7. **Debounce noisy sensors** (PM2.5 can update every 2-3 s) to protect the recorder.
8. **Optimistic command handling with confirmation**: after a write, wait for the confirming frame; if a stale
   frame arrives first, do not flip the UI back (the "button turns off again" report).
9. **Diagnostics that answer forum questions without a debug session**: Wi-Fi firmware string, device firmware,
   RSSI, `Runtime` (device uptime - detects silent reboots), seconds since last frame, reconnect count, last probe
   result, and whether the firmware looks push-only.
10. **Repairs/README guidance from the field**: dedicated 2.4 GHz WPA2 SSID, no guest network or client isolation,
    DHCP reservation, UDP 5683 both ways across VLANs, do not run a second local client, how to power-cycle, and
    the trade-off of blocking internet (stops OTA and the app). Offer a config-entry reload button/service rather
    than making users restart HA.
11. **Discovery**: DHCP matching (hostname `mxchip`, MXCHIP OUIs) only works on a flat network; always offer manual
    host entry and re-discovery by device id so a changed IP repairs itself.
12. **Do not plan on a cloud fallback.** Maintainers of sibling projects declined to carry the unofficial cloud API,
    and HomeID tooling does not see these devices.

---

## 12. Source index

HA forum
- https://community.home-assistant.io/t/philips-air-purifier/53030 (posts cited as HA#n)
- https://community.home-assistant.io/t/philips-cx3550-fan-integration/750048
- https://community.home-assistant.io/t/philips-cx3550-current-best-way-to-connect/1022131
- https://community.home-assistant.io/t/device-on-other-vlan/968133
- https://community.home-assistant.io/t/best-ha-compatible-air-purifier/752984
- https://community.home-assistant.io/t/which-smart-air-purifier-would-you-recommend/1012454
- https://community.home-assistant.io/t/philips-homeid-integration-control-your-philips-airfryers-air-purifiers-multicookers-locally/998744
- https://community.home-assistant.io/t/philips-airfryer-nutriu-integration-alexa-only/544333
- https://community.home-assistant.io/t/philips-airpurifier-with-coap/982874

Homey
- https://community.homey.app/t/app-pro-philips-air-purifiers-humidifier-app-healthy-air-always/32151
- https://community.homey.app/t/philips-luchtreiniger/127966
- https://community.homey.app/t/app-pro-philips-homeid-community-app-and-device-testing/160059

openHAB
- https://community.openhab.org/t/philips-air-binding-5-2-0-0-5-3-0-0/170501
- https://community.openhab.org/t/philips-air-binding-improved-coap-connectivity-4-0-0-0-5-0-0-0/153475
- https://community.openhab.org/t/philips-air-binding-4-0-0-0-5-0-0-0/149855
- https://community.openhab.org/t/philips-air-binding-3-0-0-0-4-0-0-0/128356
- https://raw.githubusercontent.com/openhab/openhab-addons/main/bundles/org.openhab.binding.philipsair/README.md

ioBroker / Domoticz / simon42
- https://forum.iobroker.net/topic/84797 (posts https://forum.iobroker.net/post/<pid>)
- https://forum.domoticz.com/viewtopic.php?t=34116
- https://community.simon42.com/t/probleme-philips-luftreiniger-einbinden/33946
- https://community.simon42.com/t/welchen-luftreinger-nehmen/61216
- https://community.simon42.com/t/anzeige-ueber-den-zustand-in-farben-philips-series-2000i-in-dashboard-purifire-card/6072

Reddit (via pullpush.io archive only)
- https://www.reddit.com/r/homeassistant/comments/1uzsdy2/philips_air_purifier_home_assistant_more_dynamic/
- https://www.reddit.com/r/homeassistant/comments/1ism7ww/philips_air_purifier_600_series_integration/
- https://www.reddit.com/r/homeassistant/comments/1iqyovn/best_home_assistant_smart_air_purifiers/
- https://www.reddit.com/r/homebridge/comments/1qs007r/philips_air_600800i_integration/p908rdl/

READMEs read as primary text
- `src/kongo09_philips-airpurifier-coap/README.md:18-20, 62, 96`
- `src/tinkerologie_ha-philips-airpurifier/README.md:18, 97-98, 167`
- https://raw.githubusercontent.com/HuisAutomatisering/fix-philips-airpurifier-coap/master/README.md
- https://raw.githubusercontent.com/renaudallard/homeassistant_philips_homeid/main/README.md
- https://raw.githubusercontent.com/atdr/homebridge-philipsair-platform/main/README.md
- https://raw.githubusercontent.com/1RandomDev/philips-cx3550-homeassistant/main/README.md and
  `.../main/reverse-engineering/PROTOCOL.md`

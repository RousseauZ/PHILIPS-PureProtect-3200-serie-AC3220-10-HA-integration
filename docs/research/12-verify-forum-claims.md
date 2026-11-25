# 12 - Verification of the round-1 forum and cloud-path claims (U1-U11)

Research date: 2026-11-22. Role: skeptical verifier. Each claim was taken back to the primary text and I tried to refute it.

## 0. Method and limits

Fresh downloads made for this note are in `scratchpad/dl12/` (not the round-1 copies in `scratchpad/forum/`):

| Source | How read | Saved under |
|---|---|---|
| HA forum thread 53030 | `https://community.home-assistant.io/posts/by_number/53030/<n>.json` (field `raw` = verbatim post, plus `username`, `created_at`, `reply_to_post_number`) and `/raw/53030/<n>` | `dl12/ha/` |
| openHAB thread 170501 | `https://community.openhab.org/posts/by_number/170501/<n>.json`, all posts 1-42 | `dl12/oh/` |
| Homey threads 127966, 160059, 32151 | `/t/<id>.json?include_raw=true`, `/posts/by_number/32151/<n>.json` | `dl12/homey/` |
| ioBroker topic 84797 | `https://forum.iobroker.net/api/topic/84797` (+ `?page=2`), all 36 posts, HTML stripped | `dl12/iob/all_posts.txt` |
| openHAB binding, merged code | `https://raw.githubusercontent.com/openhab/openhab-addons/main/bundles/org.openhab.binding.philipsair/...` | `dl12/ohsrc/`, `dl12/ohreadme/` |
| Philips product data AC3220/10 | `https://www.philips.co.uk/prx/product/B2C/{en_GB,nl_NL}/CONSUMER/products/AC3220_10.{specification,features,summary,disclaimers}` | `dl12/prx/` |
| Official manuals (siblings) | `https://dam.versuni.com/m/44aa19ee699082ed/original/CC_2024_AC4220_AC4221_User-manual_EU.pdf`, `.../401de6328bb7985e/original/CC_2025__AC2220_AC2221_UM_ANZ_v1-0.pdf`, `pdftotext` | `dl12/manuals/` |
| GitHub PR/issue pages | WebFetch only (model-written summary; quotes limited to about 125 characters) | not saved |

Labels: **[V]** verbatim from a primary endpoint I fetched today. **[WF]** WebFetch summary of a GitHub page (quotes are short; the rest is paraphrase). **[git]** file in a local clone, path relative to `scratchpad/src`. **[A]** archive copy only (Reddit through pullpush.io). **[I]** my inference.

Not readable: **tweakers.net / gathering.tweakers.net** (WebSearch: "The following domains are not accessible to our user agent: ['tweakers.net']"; `allowed_domains: gathering.tweakers.net` in extended mode returned "No links found"; WebFetch: "unable to fetch from gathering.tweakers.net"; curl gets the DPG Media WAF page). **reddit.com** (WebSearch: "not accessible to our user agent: ['reddit.com']"). Reddit was read only through the incomplete pullpush.io archive.

## 1. Verdict table

| Id | Verdict | One-line reason |
|---|---|---|
| U1 | confirmed | Post, author, date and wording are exact. "this integration" is not named; the post replies to #458, which quotes the kongo09 README. |
| U2 | confirmed | Exact. No follow-up by the poster anywhere on the forum; nobody replied. |
| U3 | confirmed | Dump found and copied below. "Works" means status updates are received; control was never confirmed by the owner. |
| U4 | partly confirmed | ioBroker: yes, with a log-based test, but on a CX7550/01 fan. openHAB: yes for the probe, but no log was posted and it has no 30/60/120 s backoff. |
| U5 | partly confirmed | Refusals and the FUSION platform are documented. "Not a firmware regression" is inference; for the AC1715 the cause is unknown. Absence claim holds. |
| U6 | partly confirmed | "Automatic" rests on hedged posts about older models; the AC3220 manual says the upgrade is done in the Air+ app. One long-term no-internet user, not several, and none on this family. |
| U7 | confirmed | Quote, author and date exact. "Several times a day" on 3200/4200 units is one owner. |
| U8 | partly confirmed | Closed unmerged on 2026-11-19: yes. The "unofficial API" sentence is Bluefox's, not the maintainer's, and the PR covered AC0650/AC0651/AC07xx/AC17xx, not the AC3220's cloud. |
| U9 | confirmed | `README.md:40`, identical upstream today. |
| U10 | confirmed | Fresh fetch, en_GB and nl_NL. |
| U11 | partly confirmed | True for forums and for the AC3220 family. Not true as "nowhere": GitHub has a measured observer takeover on an AMF870/15. |

## 2. Per claim

### U1. HA#468, AC3220/10 bought in the Netherlands, "working perfectly fine"

**[V]** `https://community.home-assistant.io/posts/by_number/53030/468.json`: `username` jochemsiegel, `created_at` 2026-01-15T15:00:03.878Z, `reply_to_post_number` 458. Full post:

> I've just purchased a AC3220/10 in the Netherlands, and this integration is working perfectly fine, no issues with firmwares.

**[V]** Post #458 (aceindy, 2025-12-15T16:06:09Z) is a quote of the kongo09 README: "## [Supported models](https://github.com/kongo09/philips-airpurifier-coap#supported-models)", "Note: Some of these models seem to have a newer firmware that does not allow local connections anymore. If you buy the device with the intention to manage it via Home Assistant, make sure you can return it, if the integration doesn't work for you", " * AC3220". Post #457 (SMAW, 2025-12-15) is the question it answers: "is there someone who knows if Philips PureProtect 3200-serie AC3220/10 will work?".

Attempts to refute: the integration is not named in #468. It is a reply to the kongo09 README quote, so kongo09 is the natural reading **[I]**. A WebSearch summary today attributed the post to the GeorgeSG HTTP integration; nothing in the primary text supports that.

Limits of the evidence: no firmware numbers, no duration ("just purchased"), one user. It says nothing about long-run stability.

Verdict: **confirmed**.

### U2. HA#470, Australian AC3220/10 on 0.2.3 / Combo@86, nothing from aioairctrl

**[V]** `.../53030/470.json`: `username` fredskis, `created_at` 2026-04-02T05:53:49.204Z, `reply_to_post_number` 468. Full post:

> Sad, I purchased one here in Australia. (3200 AC3220/10)
> Running Wi-Fi Firmware: AWS_Philips_AIR_Combo@86 and
> Device Firmware: 0.2.3
>
> no luck :( can't even get anything through aioairctrl

Unresolved: **[V]** `https://community.home-assistant.io/user_actions.json?username=fredskis&filter=4,5` lists this as the user's only post in the thread and the latest of all their posts. The thread ends at #474 (2026-08-31); #471 to #474 are about other models. Nobody answered.

Things the post does not say: the command used, any output or log, the network layout, or which aioairctrl version. Possible confound **[I]**: one month earlier, #469 (kongo09, 2026-03-02T22:17:08Z): "I've just done a new release with a major refactoring of the underlying `aioairctrl` library. Please report any issues if this breaks something."

Verdict: **confirmed**.

### U3. AC3210/12 dump with "Unicorn", 0.2.3, Combo@86; works on openHAB

**[V]** `https://community.openhab.org/posts/by_number/170501/9.json`: `username` ollo, `created_at` 2026-10-02T10:41:58.242Z (edited 10:47:15Z), `reply_to_post_number` 5, thread title "Philips Air Binding [5.2.0.0;5.3.0.0)". Complete post, verbatim:

```
Hi Marcel,

thanks, with the new jar I'm finally able to receive updates from my AC3210. I'm using the CoAP and received updates for PM25, Temp, Humidity and IAQL. AQIT stays NULL and so does the Error channel.

`2026-10-02 12:45:19.796 [DEBUG] [nnection.PhilipsAirCoapAPIConnection] - Status from 192.168.178.77: {"D01102":0,"D01S03":"Schlafzimmer","D01S04":"Unicorn","D01S05":"AC3210/12","D01107":0,"D01108":3,"D01109":3,"D0110A":0,"D0110C":19,"D01S0D":"688001001383","D0110F":3,"D01S12":"0.2.3","D01213":0,"ProductId":"<product_id E>","DeviceId":"<device_id C>","otacheck":false,"Runtime":328108,"rssi":-46,"wifilog":false,"blelog":-1,"free_memory":97904,"WifiVersion":"AWS_Philips_AIR_Combo@86","StatusType":"status","ConnectType":"Online","D03102":1,"D03103":0,"D03105":101,"D03106":1,"D0310A":2,"D0310C":0,"D0310D":1,"D03110":0,"D03211":0,"D03112":0,"D03115":0,"D0311F":0,"D03120":1,"D03221":1,"D03224":241,"D03125":46,"D0312A":1,"D0312B":1,"D0312C":7,"D03130":0,"D03134":1,"D03135":1,"D03136":0,"D03137":1,"D03240":0,"D03180":1,"D03182":1,"D0313B":20,"D03R81":"BQEBAgIBAgMD\n","D05102":3,"D05207":720,"D05408":9600,"D0520D":601,"D0540E":2870,"name":"Schlafzimmer","modelid":"AC3210/12","swversion":"0.2.3","pwr":"1","cl":false,"iaql":1,"pm25":1,"rh":46,"temp":24.1,"fltsts0":601,"fltsts1":2870}`
```

Reading of the dump **[I]**: device-reported keys end at `"D0540E":2870`. The fields from `"name"` onward (`name`, `modelid`, `swversion`, `pwr`, `cl`, `iaql`, `pm25`, `rh`, `temp`, `fltsts0`, `fltsts1`) are aliases the openHAB binding adds (`resolved.toClassic(reported)` in the binding). `D03224` 241 = 24.1 degC, `D03125` 46 = 46 % RH.

"Works" needs a qualifier:

- **[V]** The owner reports reading only: "I'm finally able to receive updates from my AC3210 ... received updates for PM25, Temp, Humidity and IAQL. AQIT stays NULL and so does the Error channel."
- **[V]** OH#25 (marcel_verpaalen, 2026-10-04T08:52:39Z): "AC3210/12 (thanks @ollo): the Error and Air Quality Threshold channels no longer stay NULL. Mode, fan speed and timer can now be read and controlled as well." and, in the same post: "The control commands follow the Philips app and the Home Assistant integration, and have **not** been confirmed on a real device yet. Please change **one setting at a time**." and "@ollo (AC3210/12): please try power, mode (auto / sleep), fan speed 1–5, medium and turbo, the timer, the air quality threshold, the displayed index, and the extra channels".
- **[V]** ollo's only later post (OH#28, 2026-10-04) reports a stale download link. No control result from an AC3210 owner exists in the thread (42 post numbers, last 2026-11-19).

Verdict: **confirmed** (dump and strings exact; "works" = status reading).

### U4. openHAB and ioBroker: push only on change, silent in standby, liveness probe, 30/60/120 s backoff

**ioBroker - confirmed with a log-based test, on a fan.**

- **[V]** pid 1352634 (TT-Tom, 2026-08-27), test plan: "2. Standby (Gerät aus, Strom dran) ... keine „connection lost/Connected"-Paare mehr, im Debug alle 5 min probing the device... → answered the probe"; "3. Stromlos ... nach ~5 min „lost", dann failed (attempt 1/2/3) mit 30/60/120 s Abstand als Fehler + einmal der Power-Cycle-Hinweis, ab Versuch 4 nur noch debug".
- **[V]** pid 1352841 (TT-Tom, 2026-08-29): "Dein Ventilator pusht nur, wenn sich etwas ändert. Die sechs Statusframes um 10:18 kamen exakt in der halben Minute, in der du am Gerät Einstellungen umgestellt hast; danach lief er 11 Minuten unverändert weiter und hat kein einziges Paket geschickt. Die Stille, die als „Verbindungsabbruch" im Log stand, war also nie ein Fehler — der Adapter hat sie nur falsch gedeutet." / "Phase 2 (Standby) ist der eigentliche Beleg: 69 Minuten lang kein Ton vom Gerät, 11 Nachfragen des Adapters, 11-mal geantwortet — und kein einziges „connection lost"." / "Phase 3 (stromlos) ... nach 5 Minuten „lost", Wiederholungen mit 30 / 60 / 120 Sekunden Abstand, Fehlermeldungen nur für die ersten drei Versuche".
- **[V]** The device in that log (pid 1352814, Dr. Bakterius): `"D01S04":"Babel"`, `"D01S05":"CX7550/01"`, `"D01S12":"0.2.9"`, `"WifiVersion":"AWS_Philips_AIR_Combo@86"` (10 status frames). It is a tower fan, not a purifier. Release note 2.1.0 (pid 1352845): "(betraf ruhige Geräte wie den CX7550/01, DrBakterius)".
- **[git]** `iobroker-community-adapters_ioBroker.philips-air/lib/coap.js` (v2.4.1, 2026-11-17): `:284-287` "Silence alone is NOT proof that the session is gone: a CX7550/01 sent a single status frame in 4.6 hours while answering all 26 /sys/dev/sync probes in the same log (#377)."; `:309` the probe is `await this.sync()`; `:322` on success "answered the probe, renewing the status subscription"; `:64` `this.staleTimeout = Math.max(this.aliveTimeout * 10, 120000)` (300 s with the default 30000); `:264` `Math.min(this.reconnectInterval * 2 ** (this._failedAttempts - 1), MAX_RECONNECT_INTERVAL)` with `:11` `MAX_RECONNECT_INTERVAL = 120000` and `:13` `LOUD_ATTEMPTS = 3`. So the backoff is 30, 60, 120, 120, ... s.
- Same file, a caveat the claim leaves out: `:291-292` "Firmwares that never answer /sys/dev/sync (e.g. AC2889 fw 1.0.7) therefore behave as before and cannot flap." And `:60-63` still describes classic devices as sending "a heartbeat every few minutes plus on change ... the observed ~3 min device heartbeat".

**openHAB - probe confirmed, the rest is not as worded.**

- **[V]** OH#5 (marcel_verpaalen, 2026-10-01T20:55:17Z): "CoAP devices in standby no longer go offline after two minutes. The binding pings them with a method they answer in standby, and restarts the observe relation when they respond again." / "CoAP status updates are pushed from the device to the handler. The old approach slept and polled on the shared scheduler."
- **[V]** README on `main` (`dl12/ohreadme/README.md:166-170`): "CoAP devices push their state changes, so they are not polled." / "When no update has arrived for the refresh interval (at least 30 seconds), the binding checks whether the device still answers." / "A device that sends no updates, for example in standby, stays online as long as it answers this check." / "The thing goes offline when the device neither sends an update nor answers within twice the refresh interval (at least 60 seconds)." Default `refreshInterval` 60 (`:158`).
- **[V]** Merged code (`dl12/ohsrc/PhilipsAirCoapAPIConnection.java`): `:69` `PING_TIMEOUT = 5000`; `:72-73` `MIN_PING_AFTER_MS = 30000`, `MIN_STALE_AFTER_MS = 60000`; `:154-155` "A device in standby only pushes changes and does not answer a status request, so the silence is only a failure if the device does not answer a ping either"; `:226-227` "Checks the device with a counter sync, which it also answers in standby. A device only pushes changes, so its last status is still valid as long as it answers."; `:259` the ping is `post(pingClient, host, COAP_PORT, RESOURCE_PATH_SYNC, ...)`; `:162-169` the observe relation is restarted only after a missed ping.
- No reconnect backoff exists in that class; the check simply runs at the refresh interval. "30/60/120 s" is ioBroker only. openHAB's 30 and 60 are minimum thresholds for "probe" and "offline".
- The maintainer posted no log showing push-on-change. The only log evidence in the thread is a user's (OH#24, Mclupo, 2026-10-04): "192.168.1.75 answered the ping, counter 780786140" at 09:53:46, 09:54:46 and 09:56:46, on a classic AC2939. He did not tie the behaviour to "newer firmware".
- "Stable": Mclupo (AC2939/10 + AC0950/10) "both devices are working perfectly" (OH#36, 2026-10-05); Fargi (AC2729 HTTP + AC3829 CoAP) "All values are updated with every change" (OH#15). Merged for openHAB 5.3 on 2026-10-14 (OH#40). No AC32xx owner reported standby behaviour. No flapping complaint after the rework through 2026-11-19.

Verdict: **partly confirmed**. Both projects use `POST /sys/dev/sync` as the probe and stopped treating silence as failure. The 30/60/120 s backoff, the "with logs" part and the standby measurement belong to ioBroker alone and were measured on a CX7550/01 (0.2.9 / Combo@86). "Stable" rests on maintainer statements and tests of hours to days.

### U5. Cloud-only models refuse UDP 5683, are a different platform; no report of a firmware update removing CoAP from AC32xx/AC22xx/AC42xx

Supported **[V]**:

- AC0650/10, HA#448 (martymarty004, 2025-03-06): `DEBUG:coap:Incoming error [Errno 111] Connection refused (ECONNREFUSED, received through errqueue) from <UDP6EndpointAddress 10.79.0.4 ...>`. HA#450 (BenjenJones, 2025-05-12): "also tried to scan for open ports on the device, but found none. I think philips might have killed support for local access."
- AC1715/11, HA#431 (Paul1865, 2024-12-16): "ConnectionRefusedError: [Errno 111] Connection refused (ECONNREFUSED, received through errqueue)".
- AC0651/10 **[A]** (pullpush copy of reddit comment `mry91tg`, u/BenjenJones, 2025-05-12): "Also tried the approach in the readme, to add my ac0651/10 but I get a connection refused."
- Platform **[git]** `renaudallard_homeassistant_philips_homeid/README.md:25`: "| **Air Purifiers** | AC0650, AC0651, AC1715 | MUJI | Cloud relay (FUSION MQTT), paired in the HomeID or Air+ app; AC0650 not yet tested on a device |".
- kongo09, HA#467 (2026-01-04): "This is not supported because it doesn't use encrypted CoAP for local connections in the way most other devices do. It's unclear to me if it offers local connections at all. I'm not aware of anyone who ever got it to work with any local method."

Corrections:

1. Not every report is a refusal. HA#416 (kongo09, 2024-02-16) on the AC0650: "apparently the device did not reply to any data request"; Homey#120 (Edwin_Biemond, 2024-06-27): "this device never responds back". HA#423 (3x AC1715/10), #453 (AC1715 "on 0.0.9") and #454 only say "Cannot connect to device".
2. "Not a firmware regression" is inference. The AC0650 owner himself wrote "it probably has an updated firmware" (HA#448) without ever having had it working. For the AC1715 both kinds exist: Homey#121 (DirkG, 2024-06-27) "I added my Philips AC1715/11 last Friday and I had no problems."; an AC1715 on Wi-Fi 91.1 still talks CoAP in Nov 2026 (tinkerologie #214, per note 11); HA#431 is an AC1715/11 that refuses. Whether that is firmware or hardware is unknown.
3. A firmware-driven move to cloud-only is a documented mechanism at this vendor **[git]** `renaudallard_homeassistant_philips_homeid/README.md:38`: "do not accept firmware updates from the Philips app: the FUSION migration is offered as an ordinary update and cannot be undone." (airfryers). It cannot be excluded for purifiers.

Absence claim: HA forum search today (`/search.json?q=`) for AC3220, AC3210, AC3221, AC4220, AC4221, AC2210, AC2220, AC2221, PureProtect returned only #457 and #461. A scan of all saved thread dumps (HA, Homey, openHAB, ioBroker, simon42) for those models next to firmware/update wording gave 22 posts, none saying local control stopped after an update. Closest: HA#461 (rik-c, 2025-12-27) "I have a new AC4220 here with FW 0.2.3 and it isn't connecting", resolved the next day as a guest-Wi-Fi problem (HA#462); and HA#470 (never worked, cause unknown).

Verdict: **partly confirmed**.

### U6. Updates automatic; blocking internet avoids them; local control works without internet

Forum statements **[V]**:

- HA#430 (GSzabados, 2024-12-10): "No of those apps has an update firmware function, it happens automatically, as I remember. But make sure that you have not blocked internet access to the device." / "for forcing an update, as I recall, you need to unplug the device, wait a minute, plug it back and turn it on."
- HA#389 (RT1080, 2023-02-12): "Not to my knowledge, Philips pushes them out. ... Personally I set my purifiers up on a no internet vlan to avoid further fw updates".
- HA#277 (RT1080, 2022-04-10): "To avoid further firmware upgrades following the last f*-up by Philips i blocked all internet communication." HA#290 (same day): "Biggest challenge is setting up the purifier which can only be done whilst maintaining an internet connection." / "Past 3 months this has been running smoothly."
- HA#442 (RT1080, 2025-01-01): "If you want to prevent it from updating its firmware then best to block internet access". HA#452 (RT1080, 2025-07-17): "I have 4 purifiers at home, 2 coap, 2 http based. Only recommendation I would make is to prevent the machine from communicating over the internet. This breaks the Philips app but avoids firmware updates which have in the past been known to break certain functionality."
- HA#340 (fakemoth, 2022-04-22): "I have two AC2729/50, in a different VLAN with no internet, wasn't a problem."
- **[A]** Reddit 2026-07-18, u/-3rdPlace- (4000i), as quoted in note 05.

Against the claim as worded:

1. The official manual for this family says the upgrade is done in the app. EU user manual AC3210/AC3220/AC3221 (`scratchpad/dl09/manual/um_eu.txt:40-41`, from another round-2 agent's download; identical sentence in the AC4220/AC4221 EU manual and the AC2220/AC2221 ANZ manual I downloaded today): "To ensure the best performance, kindly suggest the firmware of your purifier is upgraded to the latest version. You can do this upgrade via the Air+ app." Both forum statements that the apps have no update function are hedged ("as I remember", "Not to my knowledge") and are about older models.
2. "Automatic" on this family rests on one phrase **[V]** Homey 160059/7 (medenjara, 2026-11-16): "Firmware: Latest official Air+ / HomeID firmware 0.2.1 (auto-updated)" for an "AC3360/11" and an AC4220/12. That is the poster's label, not an observation of an update.
3. "Several long-term users" is one documented long-term user (RT1080, 2022 to 2025, models not named in those posts) plus two point-in-time statements. None is an AC32xx or a Combo@86 device.
4. A counter-anecdote **[V]** HA#197 (woockie, 2021-10-05): "I forgot to block the internet connection of one of my air purifiers. It upgraded itself the firmware and from that time I can't see it in my home assistant. The weird thing is that even the original air matters application sees it offline if I don't enable the internet connection for it again." HA#200: "After I saw it updated the firmware and it doesn't work I blocked it's internet access. Now I removed the block and it works again properly locally too."

Verdict: **partly confirmed**. Blocking internet as an update-avoidance measure with local control intact is real but thinly evidenced and untested on the AC3220 family. Whether the AC3220 updates silently, or only when the user starts it in the app, is not established.

### U7. "Het werkt niet stabiel helaas" and Homey crashes

**[V]** `https://community.homey.app/t/127966.json?include_raw=true`, title "Philips luchtreiniger", 8 posts.

- #1 Edwin58, 2025-01-16T14:39:32Z: "Is er een app waarmee ik de PHILIPS PureProtect 3200-serie AC3220/10 luchtreiniger kan uitlezen ? (met de Philips app die er is, voor luchtreinigers, lukt het namelijk niet)"
- #5 Walty, 2025-11-08: "De Philips Air app installeren, apparaat toevoegen (Purifier >= 2020) en het IP adres invullen."
- #6 Edwin58, 2025-11-13: "Klopt, dank het werkt"
- #7 Lars_Dz, 2026-03-12: "Ik kan het apparaat via ip adres toevoegen. Ik zie dan ook in homey dat alle sensoren werken. Flows starten echter niet.."
- #8 Edwin58, 2026-03-13T12:03:22Z: "Hallo, / Het werkt niet stabiel helaas. / Gr Ed"

Crashes **[V]** (thread 32151): #243 NickW, 2026-03-26: "several Philips Air purifiers (3x AC3200 & 1x AC4200). The app is working properly, but it's crashing multiple times a day for no reason ... even with one device it keeps crashing." #163 Joseph (AC3220/10 owner per #152), 2025-01-21: "Both this one and the regular version indicate in Homey "crashed" regularly." #248 Rasket787, 2026-04-07: AC3421/13, "frequent crashes — multiple times a day". #249 Anton_Wierenga, 2026-04-08: AC3420/10, "App crashes regularly ... I have the impression the app only crashes when the device is in off/inactive state".

Notes: "multiple times a day" on 3200/4200 units is one owner (NickW, who gives series names, not model numbers). The other "multiple times a day" is an AC3421/13. What crashes is the Homey app, which its developer attributes to his own code and the network: #251 "I see a lot of corrupted or half messages , invalid hash etc.", #289 (2026-10-25) "try to fix the cpu bug and aggressive retries on sync, plus every device has it own sync counter." Edwin58 writes Dutch; his country is not stated.

Verdict: **confirmed**.

### U8. ioBroker.philips-air PR #406 closed unmerged on 2026-11-19

**[WF]** `https://github.com/iobroker-community-adapters/ioBroker.philips-air/pull/406`: title "feat: add Philips Cloud support with email-code login", author reloxx13, head `feature/philips-cloud`; "tt-tom17 closed this Nov 19, 2026", not merged. Closing comment begins "I am closing this PR, and the reason is not the code." and says "The decision was made in the German forum thread." Earlier, tt-tom17 (Nov 2): "I cannot support the cloud path." / "I have no Air+ account and no cloud-capable device."; reloxx13 (Nov 4): "I can't commit to a formal co-maintainer role or ongoing responsibility for Cloud issues and forum support."

**[V]** Forum: pid 1363630 (TT-Tom, 2026-11-16): "Die Cloud-Erweiterung für den Adapter, ich kann den Support dafür nicht leisten und der Ersteller kann es auch nicht komplett." pid 1363794 (Bluefox, 2026-11-18): "Technisch habe ich im PR nichts mehr, was dagegen spricht. ... Die Frage ist aber nicht der Code, sondern wer das danach pflegt. Das ist eine Cloud-API, die nicht offiziell ist. Wenn Versuni dort etwas ändert, landen die Issues bei dir, und das kann man dir nicht aufbürden." pid 1364071 (TT-Tom, 2026-11-19T18:18:12Z): "Die Supportfrage hatte ich ihm auch schon im PR gestellt, seine Antwort und deine Einschätzung bringen mich zu dem Entschluss, dass wir den PR nicht mergen werden."

Corrections:

1. The "unofficial cloud API" sentence is Bluefox's (ioBroker project lead, reviewer), not the adapter maintainer's. TT-Tom's own reason is that neither he nor the author can support it.
2. The PR is not about the AC3220's cloud. **[WF]** description: "Add Philips Cloud support alongside local HTTP/CoAP for devices already paired with Philips Air+."; "Sign in with a Home.ID email verification code and an explicitly selected country."; "Cloud profiles cover AC0650, AC0651, AC0710/AC0720/AC0721 and the AC17 family, including AC1715."; "only AC0651 has live evidence so far." Those are the cloud-only small models. The decision says nothing about the feasibility of a cloud path for the AC3220.

Verdict: **partly confirmed**.

### U9. HomeID integration does not support CoAP purifiers

**[git]** `renaudallard_homeassistant_philips_homeid/README.md:40` (clone at `27e2db0`, 2026-11-19; the same line is in `main` on raw.githubusercontent.com today):

> **Not supported:** Philips air **humidifiers** (for example HU5710, the "Air Humidifier" series) are not supported, and neither are the older Philips air devices that use the local encrypted **CoAP** protocol (many of the models in the Air+ or Clean Home+ apps). The newer Air+ purifiers that register in the Philips cloud as FUSION devices do work here (the AC0650/AC0651/AC1715 above), whether they were paired in the Philips HomeID/NutriU app or the standalone **Air+** app (`com.philips.air`); older CoAP-only purifiers do not. For CoAP-based air purifiers and humidifiers, use a dedicated integration such as [kongo09/philips-airpurifier-coap](https://github.com/kongo09/philips-airpurifier-coap) or the [ruaan-deysel/ha-philips-airpurifier](https://github.com/ruaan-deysel/ha-philips-airpurifier) fork; both work locally with no cloud account and list HU5710 among supported models.

The README calls CoAP devices "older". The AC3220 is a 2024 model, but it is a CoAP device and is not in the supported list (`:25`), so the statement applies.

Verdict: **confirmed**.

### U10. Official product data for AC3220/10

**[V]** fetched today, HTTP 200, `success: true`.

- en_GB specification: "Internet connectivity: Yes", "Wi-Fi range: 2.4 GHz", "Voice control: Yes (Google, Alexa)", "Scheduler: Yes (in app)", "Automatic mode: Yes", "Sleep mode: Yes", "Speed settings: Yes (5 levels)", "Ambient night light: Yes", "Air quality sensors: PM2.5, Allergens", "Air quality feedback: Colour ring, numerical", "Child lock: Yes".
- nl_NL specification: "Internetverbinding: Ja", "Wi-Fi-bereik: 2,4 GHz", "Spraakbediening: Ja (Google, Alexa)", "Planner: Ja (in app)".
- en_GB features, "Smart control with Air+ app": "Pair the air purifier with the Air+ app for indoor and outdoor air quality monitoring, remote control and voice commands via Google and Alexa. In the app, select Auto+ mode for AI technology that adapts to your routine while minimising noise and energy use." "Smart scheduling function": "Choose Fresh Wake-up to slowly ramp up purification speed before your set wake-up time. At night, Fresh Bedtime cleans your room thoroughly before you come to bed and welcomes you with a cosy, warm night light."
- Case-insensitive counts over all eight JSON documents: matter 0, homekit 0, apple 0, siri 0, smartthings 0, ifttt 0, bluetooth 0, zigbee 0, thread 0; alexa 4, google 4.

Caveat: silence in marketing data is not proof of absence. The EU manual shows the data is incomplete: it lists "Bluetooth version 5.2 (LE)" (used for pairing), which the product data never mentions.

Verdict: **confirmed**.

### U11. "A second local client or the app breaks sessions" is asserted but demonstrated nowhere

Assertions **[git]**:

- `tinkerologie_ha-philips-airpurifier/README.md:167` "Stop other local CoAP clients that access the same device."; `:188` "Stop other local CoAP clients, such as a second Home Assistant instance."; `:206` "Stop the integration for that device before running another local CoAP client."
- HuisAutomatisering fork README (`scratchpad/dl05/readmes/HuisAutomatisering_fix-philips-airpurifier-coap.md:47-48`): "Using the Philips app at the same time as Home Assistant tends to make this worse, because both compete for the same encrypted session."
- atdr homebridge README (`scratchpad/dl05/readmes/atdr_homebridge-philipsair-platform.md:138`): "These purifiers serve **one connection at a time**"; `:533-535` "these purifiers serve only one connection and two arriving together were measured losing one of them at a sleeping device." The author claims a measurement and shows none.

Forum posts **[V]**:

- Homey#287 (Edwin_Biemond, 2026-09-14): "don't use philips-airctrl , pull the plug for some minutes, restartt the homey app." Homey#288 (wd3003, same day, AC4236/14): "I then completely stopped `philips-airctrl`, so there was no other CoAP client connected. ... Unfortunately, Homey still does not populate most of the capabilities." The second client was not the cause there.
- HA#67 (inso22, 2020-01-10, HTTP era): "I can definitely use both the app and the hass integration to control the device at the same time".
- HA#216 (kongo09, 2021-12-08): "when I change something in the AirMatters app, it is immediately reflected in Home Assistant."
- HA#407 (kongo09, 2023-09-15): "The Philips app connects to the cloud and the device connects to the same cloud, so they don't talk directly even if on the same network." HA#276 (2022-04-10): "The Clean Home+ app is not using the local CoAP connection but the cloud."

No forum post demonstrates a second client or the app breaking a session.

Where "nowhere" fails (GitHub, outside the forums):

- **[WF]** kongo09 #396 (mbreitkreuz, opened Oct 12, 2026, open; AMF870/15, `AWS_Philips_AIR_Combo@86`): "The device keeps one observer per source IP and the newest observe GET wins"; a second client on the HA host "takes over the integration's notifications until its watchdog re-registers"; "Same mechanism as the DHCP probe in #389". The issue page itself describes no trial for this; the timing table is in the PR #389 comment quoted in note 11 (three HA starts, two takeovers).
- Scope of that evidence: one model, same source IP, observe takeover. It is not about the Philips app and not about clients on different hosts.
- For the AC3220 family the only data point points the other way (tinkerologie #132, per note 11: two clients on an AC2220 `@86` "both worked").
- kongo09's statement that the app only talks to the cloud is contradicted for current firmware by kongo09 #328 (per note 11: a tcpdump showed the phone connecting to the purifier on port 5683). I did not re-fetch #328.

Verdict: **partly confirmed**. Correct for forums and READMEs, and undetermined for the AC3220. Too strong as a general statement.

## 3. New findings

1. **An HA custom integration already reaches the AC3220/10 through the Air+ cloud.** `https://github.com/NikGro/philips-air-plus-homeassistant` (clone `NikGro_philips-air-plus-homeassistant` at `2d240bf`, 2026-11-20, release v1.1.9; first "functional Air+ Unicorn cloud integration" commit `eaad0c1` on 2026-10-12). Round 1 said no cloud project lists the AC3220 by name; that is out of date.
   - **[git]** `README.md:12` "**PureProtect 3200 Series (AC3210/12), 3200i (AC3220/10 / AC3221)** and **AC2221/13**"; `:19` "| PureProtect 3200 / 3200i, reported as AC3210/12 / AC3220/10 / Unicorn | **Air+ cloud: email + verification code (recommended)** | Separate Air+ API, automatic token renewal and AWS MQTT shadows |".
   - **[git]** `docs/ac3221-cloud-investigation.md:238-243`: "The user's official iOS capture shows successful (`meta.code: 0`) token, device-list and MQTT-info replies. The account's purifier is represented in the cloud as **AC3220/10**, type **Unicorn**, firmware **0.2.3**, service region **eu-central-1**." `:253-255`: "Observed reported-state keys include `D03102`, `D0310C`, `D0310D`, `D03221`, `D03120`, `D05207`, `D0520D`, `D05408`, `D0540E`, `WifiVersion`, and diagnostic fields. The desired state was empty." `:348-350`: "The APK routes Unicorn through `h11 -> d11 -> c01 -> e01`, its MxChip appliance implementation."
   - **[git]** `custom_components/philips_airplus/airmatters_model.py:12-17`: modes `"Auto": 0, "Sleep": 17, "Turbo": 18, "Medium": 19, "Speed1": 1 ... "Speed5": 5`; power `D03102`, mode `D0310C`, fan level `D0310D`, PM2.5 `D03221`, allergen index `D03120`, filters `D05207`/`D0520D`/`D05408`/`D0540E`.
   - What this changes: the round-1 inference that the AC3220 sits on the MxChip/FogCloud backend with the same D0xxxx keys in an AWS IoT shadow is now a third-party observation of an EU unit on 0.2.3. It also gives an independent source for the mode codes.
   - Why it does not change the local-first conclusion: `README.md:3-8` "Vibe-coded community project: ... has not been broadly tested on real hardware ... a verified read-only cloud connection; full control and long-term operation still need validation"; `docs/...:263` "Controls have **not** been exercised against this purifier."; `README.md:61-63` setup "retrieves a signing value from a pinned, SHA-256-verified research reference" and needs GitHub raw to be reachable. I did not run any of it.
2. **Probe design details from the two projects that fixed flapping (primary code, see U4).** Both probe with `POST /sys/dev/sync`. openHAB: after max(refresh, 30 s) of silence, 5 s timeout, offline at max(2 x refresh, 60 s), observe restarted only after a missed probe, no backoff. ioBroker: after 300 s of silence, on success re-subscribe quietly, on failure reconnect with 30/60/120 s capped backoff, error log for three attempts then debug, one power-cycle hint. Measured figure: "a single status frame in 4.6 hours while answering all 26 /sys/dev/sync probes" (CX7550/01, 0.2.9 / Combo@86).
3. **Sync is not a universal probe.** ioBroker code comment: "Firmwares that never answer /sys/dev/sync (e.g. AC2889 fw 1.0.7)". Irrelevant to Unicorn firmware as far as known, but a new integration should not assume it for every model.
4. **On this family the firmware upgrade is described as an app function.** EU manual AC3210/AC3220/AC3221: "You can do this upgrade via the Air+ app." Round 1's "the apps have no update control" came from posts about older models. If true for the AC3220, not tapping the upgrade may be enough to stay on a working firmware, without blocking internet. Unverified on a device.
5. **The official spec lists only "PM2.5, Allergens" as sensors** for the AC3220/10, although the sibling dump carries temperature (`D03224`) and humidity (`D03125`), and openHAB's README marks `humidity`, `temperature` as "read only" for the `unicorn` profile. Treat temperature and humidity as present but undocumented by Philips for this model; check plausibility on the device.
6. **EU firmware level.** The NikGro capture shows an EU-region AC3220/10 on device firmware 0.2.3 in October 2026, the same as the Australian unit in HA#470 (2026-04) and the AC3210/12 in OH#9 (2026-10). The Dutch unit in HA#468 gave no version.
7. **Homey's developer now lists the family for control**: Homey#283 (Edwin_Biemond, 2026-09-13) "reading for sure ... already support these. 'AC3220/10', ''AC3210/12', AC3221/13".
8. **Tweakers and Reddit add nothing usable.** Tweakers could not be read by any tool. The Reddit archive has no AC3220 or PureProtect 3200 post about Home Assistant or Homey experience; the nearest is a 2025-05-01 r/AirPurifiers comment by a buyer in the Netherlands who had not bought yet ("It is important to integrate it with Home Assistant ... Philips PureProtect 3200 and Philips Air Performer 7000").

## 4. Could not verify

- Any Tweakers / Gathering of Tweakers content.
- Reddit beyond the pullpush.io archive (the AC0651 "connection refused" comment and the 2026-07-18 no-internet report are archive copies).
- The full text of PR #406 and of kongo09 #396 (WebFetch gives short quotes only); the PR #389 timing table and kongo09 #328 were taken from note 11, not re-fetched.
- Philips' terms of service sentence about remote updates: a search snippet mentioned it, but the URL now serves the generic website terms (last update July 2026) with no such sentence.
- Whether the AC3220 installs firmware without the user starting it in the app.

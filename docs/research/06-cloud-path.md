# 06 - The cloud route (Philips "Air+" app / Versuni cloud) for the PureProtect 3200 AC3220/10

Research date: 2026-11-22. Angle: how the Air+ cloud works, whether the AC3220 is reachable through it, and whether a new Home Assistant integration should have a cloud path next to local CoAP.

Nothing here was tested against a real AC3220 or a real account. Everything comes from reading source code, a few unauthenticated requests to public endpoints, official product data, and issue trackers.

## 0. Evidence tags and limits

| Tag | Meaning |
|---|---|
| [V-code] | Read by me in cloned source. Paths are relative to `scratchpad/src` unless stated. |
| [V-live] | Result of my own unauthenticated request on 2026-11-22. |
| [V-web] | Official Philips product data fetched directly as JSON (not summarised by a model). |
| [WF] | GitHub or web page read through WebFetch, which returns a summary written by a small model. Short quotes are probably verbatim, the rest is paraphrase. |
| [H] | Hearsay: forum post or a claim inside a third-party repo that I could not check. |
| [I] | My inference. |

Limits: `api.github.com` and raw GitHub HTML are blocked here, so all issue and PR content is [WF]. I did not log in anywhere, so every statement about authenticated responses rests on the cited projects.

Secrets: two values that the projects publish (the OIDC client secret and the MxChip HMAC signing secret) are not copied here. I give the file and line instead.

Sources cloned for this angle (all read, none executed):

| Local directory | Upstream | Last commit |
|---|---|---|
| `kwesolowski_node-red-contrib-philips-airplus` | github.com/kwesolowski/node-red-contrib-philips-airplus (npm 0.2.0) | 2026-11-15 |
| `MaddogWarner_homebridge-philips-air-purifier-complete` | github.com/MaddogWarner/homebridge-philips-air-purifier-complete (npm 4.2.0) | 2026-11-21 |
| `ShorMeneses_philips-airplus-homeassistant` | github.com/ShorMeneses/philips-airplus-homeassistant (v1.0.11) | 2026-07-05 |
| `Ka3seBr0t_HA_Philips_Air_Plus` | github.com/Ka3seBr0t/HA_Philips_Air_Plus (v0.3.2) | 2026-07-06 |
| `renaudallard_homeassistant_philips_homeid` | github.com/renaudallard/homeassistant_philips_homeid (2026.11.1) | 2026-11-19 |
| `scratchpad/dl06/hb-airplus/package` (npm tarball) | npm `homebridge-philips-airplus` 0.1.0, repo kerdofficial/homebridge-philips-airplus | published 2026-09-22 |

## 1. Summary

1. **There are two different Philips/Versuni clouds behind the one Air+ app, and the existing projects each speak only one of them.**
   - Backend A, "MxChip / FogCloud" (also called gaoda or air-matters in the app code): REST at `www.api.air.philips.com`, MQTT on a plain AWS IoT endpoint in `eu-central-1`, state in a classic AWS IoT device shadow.
   - Backend B, "Versuni DaConnect / FUSION": REST at `prod.eu-da.iot.versuni.com`, MQTT at `ats.prod.eu-da.iot.versuni.com` with a custom authorizer, state on an "NCP port" channel.
2. **The AC3220 almost certainly lives on backend A.** This is an inference from four independent pieces of evidence (section 6), not a test. No cloud project lists the AC3220 by name.
3. **On backend A the cloud carries exactly the same data as local CoAP.** The shadow's `reported` object is the local status JSON: same `D0xxxx` keys, same `DeviceId`, `ProductId`, `WifiVersion`, `StatusType`, `ConnectType`. Commands are a shadow `desired` patch with the same keys and integer values that local CoAP writes use.
4. **Backend A authentication does not need OAuth at all after the first login.** A one-time email code gives the account UID. From then on a 7-day JWT is obtained from the UID plus one app-wide HMAC secret. There is no refresh token to lose. The price: that secret is not handed out by any API, it has to come from the app (or from a project that publishes it).
5. **The cloud has the same "push on change" staleness as local CoAP**, plus its own failure modes (presigned URL valid 1 hour and single use, intermittent 503 and error 16002, one MQTT session per client id). It does offer one thing local CoAP lacks: a shadow `get` makes an online device send a fresh full report within 1 to 2 s (measured on an AC3737, not on an AC3220).
6. **Official third-party routes are Alexa and Google only.** Official product data for the AC3220/10 says "Voice control: Yes (Google, Alexa)". I found no Matter, HomeKit, SmartThings, IFTTT or public API for it.
7. **Recommendation:** build the integration local-first and local-only for the first release. Keep the transport behind an interface so that an optional, opt-in cloud transport for backend A can be added later. Do not put the cloud in the critical path, and do not ship the app secret in the repository.

## 2. The two backends side by side

| | Backend A: MxChip / FogCloud ("gaoda", "air-matters") | Backend B: Versuni DaConnect ("FUSION", tenant `da`) |
|---|---|---|
| REST base | `https://www.api.air.philips.com` (Cloudflare) | `https://prod.eu-da.iot.versuni.com/api` (AWS API Gateway); `prod.us-da...`, `prod.ap-da...`; app uses `prod.global-da.iot.versuni.com` |
| REST auth | `Authorization: jwt <7-day JWT>`; JWT from a signed `getToken` | `Authorization: Bearer <home.id access token>` (1 hour) |
| Device list | `GET /enduser/deviceList/` | `GET /da/user/self/device` |
| MQTT host | `a2gv4wmvb0sdt5-ats.iot.eu-central-1.amazonaws.com` (value comes from `mqttInfo`) | `ats.prod.eu-da.iot.versuni.com:443/mqtt` |
| MQTT auth | SigV4 presigned WSS URL from `POST /enduser/v2/mqttInfo/`, 1 hour, single use | AWS IoT custom authorizer headers: signature from `GET /da/user/self/signature` + access token |
| MQTT client id | issued by `mqttInfo` | `{userId}_{uuid}`; `userId` from `POST /da/user/self/get-id {idToken}` |
| Thing name | 32-hex FogCloud `device_id` (same as `DeviceId` in local status) | `da-<uuid>` |
| State | Whole status in the classic shadow: `$aws/things/<id>/shadow/...` | `da_ctrl/<thing>/from_ncp` (ports `Status`, `Config`, `filtRd`); shadow only for `powerOn`, firmware, errors |
| Commands | shadow `update` with `{"state":{"desired":{"D03102":1}}}` | `da_ctrl/<thing>/to_ncp` with `{"cn":"setPort","data":{"portName":"Control","properties":{...}}}`; power via shadow `desired.powerOn` |
| Devices seen on it | AC3737/10 "Carnation", CX3550/01 "Trident", HU1509/HU1510, AC3210 (one user report) | AC0650, AC0651, AC1715, airfryers, espresso machines |
| Wi-Fi platform | MXCHIP module, `WifiVersion: AWS_Philips_AIR...`, local CoAP on UDP 5683 | ESP32 / Versuni MAC `E4:BC:96`, no local CoAP |
| Projects | node-red-contrib-philips-airplus, Ka3seBr0t/HA_Philips_Air_Plus, homebridge-philips-airplus | ShorMeneses/philips-airplus-homeassistant, MaddogWarner homebridge (`airplus-cloud`), renaudallard/homeassistant_philips_homeid, ioBroker PR #406 |

Evidence for the split:

- [V-code] The node-red package started on backend B (copied from ShorMeneses) and switched to backend A three days later because its AC3737 was not there. First commit `d42d981:lib/constants.js` has `API_HOST = 'prod.eu-da.iot.versuni.com'` and `TOPIC_CONTROL = 'da_ctrl/{deviceId}/to_ncp'`. Commit `14d62ab` (2026-01-09) is titled "docs: fix protocol endpoints - v3 uses MxChip/AWS IoT, not versuni".
- [V-code] `Ka3seBr0t_HA_Philips_Air_Plus/README.md:15-18`: "Not the upstream Versuni/HomeID integration (e.g. ShorMeneses/philips-airplus-homeassistant). That one returns "no devices found" for the CX3550 - it targets a different backend".
- [V-code] `Ka3seBr0t_HA_Philips_Air_Plus/notes/progress_methodb.md:25-26`: with a valid Air+ token, `GET /user/self/device` returned `[]` for an account that owns two CX3550 fans.
- [V-code] `dl06/hb-airplus/package/README.md:3-5`: "using the MxChip/FogCloud service ... Other models and the Versuni/DaConnect backend are not supported."
- [V-live] Both backends answered today. `GET https://www.api.air.philips.com/enduser/deviceList/` without a token: HTTP 200, body `{"data": {}, "meta": {"code": 10001, "message": "Lack of JWT Authorization"}}`, headers `server: cloudflare`, `x-ratelimit-limit: 10`, `retry-after: 1`. `GET https://prod.eu-da.iot.versuni.com/api/da/user/self/device` without a token: HTTP 401 `{"message":"Unauthorized"}` with `x-amzn-errortype: UnauthorizedException`.

## 3. Identity layer: home.id on SAP CDC (Gigya)

Both backends hang off the same Philips "home.id" account system, which is SAP Customer Data Cloud (Gigya).

### 3.1 Constants

| Item | Value | Source |
|---|---|---|
| Gigya API key / OIDC tenant | `4_JGZWlP8eQHpEqkvQElolbA` | [V-code] node-red `lib/constants.js:7`; ShorMeneses `const.py:50`; Ka3seBr0t `oneid_login.py:25` |
| Gigya base | `https://cdc.accounts.home.id` | same |
| OIDC issuer | `https://cdc.accounts.home.id/oidc/op/v1.0/4_JGZWlP8eQHpEqkvQElolbA/` | [V-live] discovery document |
| Air+ app client id | `-XsK7O6iEkLml77yDGDUi0ku` | [V-code] node-red `lib/constants.js:11`; MaddogWarner `philips_air_api.py:56`; ShorMeneses `const.py:97` |
| Air+ redirect URI | `com.philips.air://loginredirect` | [V-code] node-red `lib/constants.js:10` |
| Air+ client secret | published at node-red `lib/constants.js:12`, sent as `client_secret_post` (`lib/oauth.js:38-44`) | [V-code]. Not needed: MaddogWarner and ShorMeneses exchange and refresh with PKCE and no secret (`scripts/airplus_setup.py:77-85`, `philips_air_api.py:772-778`) |
| HomeID app client id | `-u6aTznrxp9_9e_0a57CpvEG`, redirect `com.philips.ka.oneka.app.prod://oauthredirect` | [V-code] ShorMeneses `const.py:60-61` |
| Scopes requested | `openid email profile address DI.Account.read DI.Account.write DI.AccountProfile.read DI.AccountProfile.write DI.AccountGeneralConsent.read DI.AccountGeneralConsent.write DI.GeneralConsent.read subscriptions profile_extended consents DI.AccountSubscription.read DI.AccountSubscription.write` | [V-code] node-red `lib/constants.js:13-30` |
| Android package | `com.philips.ph.homecare` (User-Agent `MxChip&Fog&Hyj#com.philips.ph.homecare#_v3.16.1`) | [V-code] node-red `lib/constants.js:38` |

[V-live] The OIDC discovery document (`.../.well-known/openid-configuration`) lists: `authorization_endpoint .../authorize`, `token_endpoint .../token`, `device_authorization_endpoint .../device_authorization`, `revocation_endpoint .../revoke`, `userinfo_endpoint`, `grant_types_supported` = authorization_code, implicit, refresh_token, client_credentials, jwt-bearer, token-exchange; `code_challenge_methods_supported` = plain, S256; `token_endpoint_auth_methods_supported` = client_secret_basic, client_secret_post; `scopes_supported` includes `offline_access` and `VoiceProvider.write` (neither is requested by any project).

### 3.2 Login flows found in the projects

**Flow 1: browser, authorization code + PKCE, copy the redirect.** The user opens the authorize URL, logs in, and the browser is redirected to `com.philips.air://loginredirect?code=...`, which a desktop browser cannot open. The user must fish the URL out of the address bar or the DevTools network tab and paste it back.
- [V-code] node-red `README.md:44-49`; ShorMeneses `README.md:64-79` ("open browser DevTools and switch to the Network tab").
- This flow is fragile. [V-code] MaddogWarner `CHANGELOG.md:171-200` (v3.2.4 and v3.2.5, 2026-06-15): some browsers land on `accounts.home.id/authui/client/proxy?mode=afterConsent&...` instead; `CHANGELOG.md:156-158` (v3.3.0): users "could only copy a home.id web-client code, which SAP CDC rejects as invalid_grant when exchanged with the Philips Air app client".
- [V-code] node-red tried the OAuth device-code grant: commit `47e841c` (2026-01-08) "Add device code flow attempt (blocked by Philips server)". Its CLI therefore drives a Playwright browser (`bin/philips-airplus-auth.js:163-254`), which is not an option inside Home Assistant.

**Flow 2: email one-time code, no browser.** Two Gigya REST calls:

```
POST https://cdc.accounts.home.id/accounts.auth.otp.email.sendCode
     form: email, apiKey=4_JGZWlP8eQHpEqkvQElolbA, format=json        -> { errorCode: 0, vToken }
POST https://cdc.accounts.home.id/accounts.auth.otp.email.login
     form: email, code, vToken, apiKey, format=json                   -> { errorCode: 0, UID, sessionInfo.cookieValue }
```

- For backend A that is the whole login: `UID` is the user id. [V-code] Ka3seBr0t `oneid_login.py:1-19, 34-72`; hb-airplus `dist/cloud.js:35-60`.
- For backend B three more steps turn the Gigya session into OIDC tokens: `GET {issuer}/authorize?...&prompt=none` (read `context` from the `Location` header), `POST {gigya}/socialize.getIDs {APIKey, includeTicket=true}` (returns `gmidTicket`), `GET {issuer}/authorize/continue?context&login_token&gmidTicket&client_id` (redirect carries `code`), then `POST {issuer}/token`. [V-code] MaddogWarner `scripts/airplus_setup.py:224-272, 360-397`; Ka3seBr0t `notes/architecture.md:46-59`.
- Known failure cases: Gigya `errorCode 206001` "account pending registration" for accounts created by social login that never finished sign-up (Ka3seBr0t `oneid_login.py:62-66`); Apple private-relay addresses may never receive the code (MaddogWarner `CHANGELOG.md:146-148`); calling `accounts.socialize.getIDs` instead of `socialize.getIDs` gives "Permission denied" (MaddogWarner `CHANGELOG.md:94-98`).

### 3.3 Token lifetimes

| Token | Lifetime | Evidence |
|---|---|---|
| home.id access token | about 3600 s | [V-code] node-red `docs/oauth-findings.md:16`; MaddogWarner commit `51e5673` "The Air+ access token lives 3600s and AWS IoT drops the WebSocket when it expires"; [WF] ShorMeneses issue #5 "The access token is valid for ~60 minutes." |
| home.id refresh token | Unknown. It rotates on use. Claimed to die on password change or "long inactivity" | [V-code] node-red `lib/oauth.js:191-199`, `nodes/airplus-account.js:87-88` ("a second refresh with the same refresh token can fail as invalid_grant once the first one rotates it"); `RELIABILITY.md:30` says "~30 days of inactivity" without evidence. [WF] ShorMeneses issue #20: maintainer says a Home Assistant that was off longer than the token validity needs a new login; issue #40 (open): authorization lost "every time my internet goes down". |
| Backend A JWT | 7 days (`exp = orig_iat + 604800`); re-issued any time from UID + app secret | [V-code] node-red `docs/api-reverse-engineered.md:111-124`; Ka3seBr0t `notes/auth_refresh.md:6-15, 42-48` |
| Backend A presigned WSS URL | `X-Amz-Expires=3600`, and single use | [V-code] Ka3seBr0t `notes/auth_refresh.md:13-14, 79-83`; node-red `lib/constants.js:77-78` (reconnect at 50 min) |
| Backend B MQTT signature | fetched per connection; the connection dies when the access token expires | [V-code] MaddogWarner `philips_air_api.py:879-913` |

The mobile app sends both `refresh_token` and `access_token` in its refresh request and serialises refreshes with a mutex (node-red `docs/oauth-findings.md:32-49`, from decompiled `OneIdAuth.java`). The open-source clients send only the refresh token.

## 4. Backend A in detail (the one that matters for the AC3220)

### 4.1 REST API

Base `https://www.api.air.philips.com`. Every response is `{"data": ..., "meta": {"code": <int>, "message": "..."}}` and success is `meta.code == 0`, also when the HTTP status is 200 with an error inside.

| Call | Request | Response | Source |
|---|---|---|---|
| `GET /device/serverTime/` | no auth | `data.timestamp1` (epoch s) | [V-live] HTTP 200, `x-ratelimit-limit: 5`, `retry-after: 1`; [V-code] node-red `lib/api.js:77-92` |
| `POST /enduser/v2/getToken/` | JSON `{"timestamp":"<s>","username":"PHILIPS:<UID>","app_id":"9fd505fa9c7111e9a1e3061302926720"}`, header `Signature: <hex>` | `data.token` (JWT), `data.enduser_id` | [V-code] node-red `lib/api.js:99-160`; Ka3seBr0t `airmatters_auth.py:96-117`; hb-airplus `dist/cloud.js:86-100` |
| `GET /enduser/deviceList/` | `Authorization: jwt <JWT>` | array of `{device_id, enduser_id, app_id, registration_id, is_push, device_info:{...}}` | [V-code] node-red `docs/api-reverse-engineered.md:443-477`, `lib/api.js:203-211` |
| `POST /enduser/v2/mqttInfo/` | `Authorization: jwt <JWT>`, JSON `{"device_id":["<id>", ...]}` | `data.mqttinfos[] = {host, endpoint, path, client_id, device_id}` | [V-code] node-red `docs/api-reverse-engineered.md:352-380`; Ka3seBr0t `airmatters_auth.py:141-173` |
| `POST /enduser/updateLanguage/` | `{"lan_code","country_code"}` | - | node-red `docs/api-reverse-engineered.md:144-165` |
| others named in the APK | `enduser/bindDevice/`, `enduser/share/*`, `enduser/grantDevice/`, `enduser/login/` | not explored by anyone | [V-code] Ka3seBr0t `notes/finding_fan_architecture.md:69-76` |

`device_info` fields in the AC3737 capture (node-red `docs/api-reverse-engineered.md:457-473`): `device_alias`, `binding_time`, `activate_time`, `product_id`, `mac`, `modelid` ("AC3737/10"), `name`, `record_time`, `type` ("Carnation"), `is_online`, `service_region` ("eu-central-1"), `activate_ip` (the public IP at activation), `device_id`, `swversion`, `isAISetup`.

Signature (identical in three independent implementations, node-red `lib/api.js:25-39`, Ka3seBr0t `airmatters_auth.py:64-68`, hb-airplus `dist/cloud.js:8-13`):

```
username  = "PHILIPS:" + UID
params    = "app_id=" + APP_ID + "&timestamp=" + ts + "&username=" + urlencode(username)
hmac1     = hex( HMAC-SHA256(key = mSecret,  msg = params) )
Signature = hex( HMAC-SHA256(key = username, msg = hmac1) )
```

- `mSecret` is one string shared by every installation of the app, in the form `a_` + 32 hex characters. node-red publishes it (`lib/constants.js:37`, obtained with a Frida hook on `HttpRequestManager.setSecret()`, `docs/api-reverse-engineered.md:66-71`). Ka3seBr0t deliberately does not: its config flow asks the user to upload their own APK and extracts the value with a regex over the dex files (`apk_extract.py`, pattern `a_[0-9a-f]{32}`). hb-airplus asks the user to type it in (`README.md:12-14`).
- Without the `PHILIPS:` prefix `getToken` still returns a token, but in another namespace, and `mqttInfo` then answers `code 16002 "Not binding to the device"` (Ka3seBr0t `notes/auth_refresh.md:74-75`).
- Only `getToken` is signed. `deviceList` and `mqttInfo` need only the JWT.

Security observation [I, from V-code]: the request that mints the JWT contains nothing that is specific to the logged-in session. The UID plus the app-wide secret are enough, forever (Ka3seBr0t `notes/auth_refresh.md:10`: "user_id (32-hex, einmalig aus dem OneID-Login, läuft nie ab)"). For an integration this means the stored UID is a permanent credential for the account's devices and must be treated like a password: keep it out of logs and redact it in diagnostics.

Server behaviour reported by the projects:
- Intermittent HTTP 503 from the load balancer; the app hides it with silent retries (Ka3seBr0t `notes/auth_refresh.md:84-86`, `airmatters_auth.py:71-93` retries 5 to 8 times with 2 s pauses).
- `mqttInfo` sporadically returns `16002` for correctly bound devices and succeeds on retry (Ka3seBr0t `CHANGELOG.md:61-64`).
- Rate limits: `serverTime` 5 per second, `deviceList` 10 per second (node-red `docs/api-reverse-engineered.md:328-333`; the two header values are [V-live]). A burst of requests during a reverse-engineering session ran into a "429 storm" (Ka3seBr0t `notes/properties.md:86, 261`).
- [I] The `app_id` is a version-1 UUID whose embedded timestamp is 2019-07-02. The FogCloud app registration is therefore from the Clean Home+ era, which suggests this API has been stable for years. Ka3seBr0t `README.md:57-58` claims the signing value "is the same across app versions/regions" [H].

### 4.2 MQTT

- Transport: MQTT 3.1.1 over WebSocket (TLS, port 443) to the URL returned by `mqttInfo`. The whole query string is an AWS SigV4 presigned URL (`X-Amz-Algorithm`, `X-Amz-Signature`, `X-Amz-Security-Token`, `X-Amz-Expires=3600`). No custom authorizer, no client certificate.
- Client settings used by the projects: `clientId = mqttInfo.client_id`, `clean = true`, `keepalive = 30`, automatic reconnect off (node-red `lib/mqtt.js:428-434`; Ka3seBr0t `device_connection.py:86-111`; hb-airplus `dist/session.js:9-12`).
- paho adds an `Origin` header that AWS rejects; strip it (Ka3seBr0t `device_connection.py:95-101`). The path must be passed byte-identical, without re-encoding (Ka3seBr0t `notes/auth_refresh.md:93-94`).
- One URL is good for one connection. After any disconnect a new `mqttInfo` call is required. node-red got this wrong until 2026-11-15: commit `79bf5a3` describes how the 50-minute refresh "connected with that expired URL and timed out until Node-RED restarted".
- Credentials are per device: one MQTT connection per device (node-red commit `6f69605`, `lib/mqtt.js:231-235`).
- Reconnect policies in the wild: node-red exponential 1 s to 5 min plus a circuit breaker that opens after 10 consecutive failures for 5 min (`lib/mqtt.js:89-92, 266-307`); Ka3seBr0t 2 s to 300 s (`const.py:86-87`); hb-airplus up to 60 s with jitter (`dist/session.js:115`).

Topics (thing name = `device_id`):

```
$aws/things/<id>/shadow/get                 publish "{}" (or {"clientToken": "..."}) to request the shadow
$aws/things/<id>/shadow/get/accepted        full document: state.reported, state.desired, metadata, version, timestamp
$aws/things/<id>/shadow/get/rejected
$aws/things/<id>/shadow/update              publish {"state":{"desired":{...}}}
$aws/things/<id>/shadow/update/accepted     also carries the device's own reports
$aws/things/<id>/shadow/update/rejected
$aws/things/<id>/shadow/update/delta        desired vs reported difference
$aws/things/<id>/shadow/update/documents    {"previous":{...},"current":{...}} after every change
```

node-red subscribes to get/accepted, get/rejected, update/accepted, update/rejected, update/delta (`lib/mqtt.js:337-343`). Ka3seBr0t and hb-airplus use update/documents instead of delta (`device_connection.py:156-163`; `dist/session.js:22`). A wildcard subscription gets the client disconnected (Ka3seBr0t `notes/finding_fan_architecture.md:58`).

### 4.3 What the shadow contains

Real `reported` object of a CX3550/01 (Ka3seBr0t `notes/properties.md:34-58`, identifiers redacted by that author):

```json
{"state":{"reported":{
  "ConnectType":"Online","DeviceId":"<device_id>","StatusType":"status",
  "D01102":2,"D01S03":"Fan1","D01S04":"Trident","D01S05":"CX3550/01",
  "D01107":0,"D01108":3,"D01109":3,"D0110A":0,"D0110B":1,"D01S0D":"000000000000","D0110F":3,
  "D01S12":"0.1.7","D01213":0,"ProductId":"b3d240e5b11711ee88c206d016384e4a",
  "otacheck":false,"Runtime":161799392,"rssi":-67,"wifilog":false,"blelog":-1,"free_memory":95536,
  "WifiVersion":"AWS_Philips_AIR_Combo@86",
  "D03102":1,"D03105":0,"D0310A":1,"D0310C":2,"D0310D":2,"D0320F":23040,"D03110":0,"D03211":0,"D03130":0,"D0313B":20
}}}
```

Real `reported` object of an AC3737/10 (node-red `docs/message-structure.md:10-33`): `D01102`, `D01S03`, `D01S04` "Carnation", `D01S05` "AC3737/10", `ProductId`, `DeviceId`, `StatusType` "status", `ConnectType` "Online", `D03102`, `D03103`, `D03105`, `D0310C`, `D03120`, `D03221`, `D03224`, `D03125`, `D03128`, `D05102`, `D0540E`, `rssi`, `free_memory`, `Runtime`.

Compare the local CoAP status of an AC3220/10 from kongo09 issue #181 (quoted in `research/02-kongo09-integration.md` section 2.2): the same envelope keys (`ProductId`, `DeviceId`, `otacheck`, `Runtime`, `rssi`, `wifilog`, `blelog`, `free_memory`, `WifiVersion`, `StatusType`, `ConnectType`) and the same `D01xxx` / `D03xxx` / `D05xxx` families. **The cloud shadow is the local status document.** [V-code for the two cloud samples; I for the AC3220.]

Also in the shadow document:
- `metadata.reported.<key>.timestamp` (epoch seconds): when the device last reported each key. node-red uses it to tell fresh values from old ones (`lib/parser.js:249-266`); hb-airplus marks a device unavailable when the newest sensor timestamp is older than 10 minutes (`dist/state.js:86-94`).
- `version`: monotonically increasing; hb-airplus drops documents older than the one it holds (`dist/state.js:66`).
- In the AC3737 shadow `reported.DeviceId` equals the thing name (`docs/message-structure.md:16, 51-53`).

Caution: node-red `docs/api-reverse-engineered.md:397-425` shows a "Shadow Document Structure" with `powerOn`, `productState`, `ncpFirmwareVersion`. That block is a leftover from the backend B model the author started from. The measured AC3737 structure is the one in `docs/message-structure.md`. `lib/parser.js:45-58, 114-125` still parses those backend B fields.

### 4.4 Commands

Publish to `$aws/things/<id>/shadow/update`:

```json
{"state":{"desired":{"D03102":1}}}
```

- Keys and values are the local CoAP ones: power `D03102` 0/1, mode `D0310C` (0 auto, 17 sleep, 18 turbo, small integers for manual speeds on the AC3737), child lock `D03103`, display `D03105`, target humidity `D03128` (node-red `lib/parser.js:182-224`). hb-airplus writes `D03135` (lamp 0/1/2), `D03137` (ambient effect 1 to 4), `D03105` (0/115/123), `D03110` (timer, 0 or hours+1), `D03130`, `D03134` to HU1509/HU1510 (`dist/state.js:2-13`). These are the same constants kongo09 calls `NEW2_*`.
- Values are JSON integers, as with CoAP.
- Confirmation: `update/accepted` with a higher `version`; the device then reports the new value. hb-airplus treats a command as done only when a newer `reported` state matches the patch, with an 8 s deadline (`dist/session.js:134-136, 176-199`).
- After a cloud write `StatusType` goes "status" -> "control" -> "status" (Ka3seBr0t `notes/properties.md`, section 3e). The same flip was seen in local CoAP status after app commands on an AC4221 (kongo09 #416, see `research/04-github-issues.md`). So cloud commands are visible to a local observer.
- The device publishes its reports with `desired: null`, which clears the desired section (Ka3seBr0t `notes/auth_refresh.md:96-98`). [I] That makes it unlikely that an old cloud command is replayed later and overrides a local change, the usual hazard of device shadows.
- Read and write values can differ. On the CX3550 oscillation is read as 23040 but must be written as 90; writing 23040 is rejected (Ka3seBr0t `const.py:41-46`). Any AC3220 mapping has to be verified per key.

### 4.5 Push behaviour and polling

- node-red measurement on an AC3737: "Reports the device sends on its own were more than 13 min apart" and "An online AC3737 answers a get with a fresh report within 1-2 s" (`docs/message-structure.md:92-96`). Each `get` produces two messages: the stored shadow (possibly old), then the device's fresh report on `update/accepted`. node-red now sends a `get` every 60 +/- 15 min per device (`lib/constants.js:84-87`, commit `f92942e`).
- Ka3seBr0t on a CX3550: "the Philips cloud doesn't reliably deliver shadow/update/documents pushes for physical changes", fixed in v0.3.2 with a `shadow/get` every 30 s (`CHANGELOG.md:8-16`, `const.py:89-95`).
- hb-airplus polls with `get` every 60 s (`dist/session.js:91`) and warns: "A cloud response is not proof of a fresh measurement ... An unchanged device that does not send fresh telemetry can therefore appear unavailable until it reports again." (`README.md`, "Connection and privacy").
- A connected MQTT socket says nothing about the device. Ka3seBr0t uses `reported.ConnectType == "Online"` for availability (`coordinator.py:44-61`, `CHANGELOG.md:73-80`).

So the cloud is push-on-change too. What it adds is the documented, cheap "ask for a fresh report" operation.

## 5. Backend B in brief (not the AC3220's backend)

Included because two of the projects named in the task use it and because it explains user reports of "no devices found".

- REST (Bearer access token): `GET /api/da/user/self/device` (list; fields `id`/`uuid`, `ctn`, `friendlyName`, `macAddress`, `thingName`), `GET /api/da/user/self/signature` -> `{"signature": "..."}`, `POST /api/da/user/self/get-id {"idToken": ...}` -> `{"userId": "..."}`. [V-code] ShorMeneses `const.py:8-21`, `api.py:76-140`; MaddogWarner `philips_air_api.py:54-60, 804-860`.
- MQTT over WSS to `ats.prod.eu-da.iot.versuni.com:443/mqtt` with headers `x-amz-customauthorizer-name: CustomAuthorizer`, `x-amz-customauthorizer-signature: <signature>`, `token-header: Bearer <access_token>`, `tenant: da`, `content-type: application/json`, and no `Origin` header. [V-code] MaddogWarner `philips_air_api.py:904-912`; ShorMeneses `mqtt_client.py:93-102`.
- Client id must start with the `userId` from `get-id` (`{userId}_{uuid}`), otherwise the connect is silently refused. MaddogWarner made this a breaking change in 4.0.0 on 2026-08-24 (`CHANGELOG.md:110-121`).
- Topics `da_ctrl/da-<uuid>/to_ncp` and `.../from_ncp`. Command envelope: `{"cid":"<8 hex>","time":"<ISO Z>","type":"command","cn":"setPort"|"getPort"|"getAllPorts","ct":"mobile","data":{"portName":"Control","properties":{"D0310C":17}}}`. Ports `Status`, `Control`, `Config`, `filtRd`, `filtWr`. Power is a shadow write `{"state":{"desired":{"powerOn":true}}}`. [V-code] ShorMeneses `mqtt_client.py:347-402`, `models.yaml:4-41`; MaddogWarner `philips_air_api.py:142-167, 995-1060`.
- The broker can deliver several JSON objects concatenated in one frame (ShorMeneses `mqtt_client.py:125-159`).
- Same client id as the phone app means the two sessions kick each other out (ShorMeneses commit `1dfa91a`, 2026-04-20, fixed with an `_ha` suffix; MaddogWarner `CHANGELOG.md:78-82` describes leaked daemons "each one holding its own MQTT session against the same device").
- Devices are registered per OAuth client. A purifier paired in the Air+ app is invisible to a token of the HomeID app client and the other way round (renaudallard `README.md:175`).

## 6. "v1 / v2 / v3" and where the AC3220 falls

### 6.1 What the versions mean

They are **datapoint-key generations inside the Air+ app**, not cloud API versions. node-red `docs/v3-protocol-reference.md:78-94` quotes the decompiled base class (`g7/a.java`), where each device class has a protocol version field:

```java
if (3 == i10)      { w2("D03102", z10 ? 1 : 0); }        // V3: int 1/0
else if (2 == i10) { z2("D03-02", z10 ? "ON" : "OFF"); } // V2: strings
else               { z2("pwr", z10 ? "1" : "0"); }       // V1: legacy keys
```

| node-red name | Keys | kongo09 name | Example |
|---|---|---|---|
| v1 | `pwr`, `mode`, `om`, `pm25`, `rh`, `temp`, `iaql`, `cl`, `uil` | first generation | AC2729, AC2889, AC4236 |
| v2 | `D03-02` = "ON"/"OFF", `D03-33`, ... | "NEW" | AC0850, AC1715 local |
| v3 | `D03102` = 1/0, `D0310C`, `D03221`, ... | "NEW2" | AC3737, CX3550, AC22xx/AC32xx/AC42xx |

node-red "supports v3 only" because commit `ab04361` (2026-01-07) removed the v1/v2 fallbacks from its parser, and it has only been tested on an AC3737 (`README.md:14-18, 183-186`).

**The AC3220 is v3 by this definition**: its local status uses `D03102`, `D0310C`, `D03221` with integer values, and kongo09 puts it in the NEW2 class family (`PhilipsAC3220 -> PhilipsAC3210 -> PhilipsAC22xx -> PhilipsNew2GenericFan`). [V-code] `kongo09_philips-airpurifier-coap/custom_components/philips_airpurifier_coap/const.py:446` `NEW_POWER = "D03-02"`, `:456` `NEW2_POWER = "D03102"`; `philips.py:799, 1173, 1179`; `philips.py:640` `class PhilipsAC1715(PhilipsNewGenericFan)`.

Note that "v3" does not select a backend. Backend B devices (AC0650) also use `D0310C`/`D0310D`. The backend is decided by the Wi-Fi platform.

MaddogWarner's own classification is by transport (`README.md:386-392`): `coap` (default) for "AC2xxx, AC3xxx, AC4xxx", `http` for AC1xxx, `homeid-http`, and `airplus-cloud` for "Devices registered in the Philips Air+ app" with the setup section titled "Air+ Cloud Setup (AC0650, AC1715)". By that table the AC3220 is a `coap` device, and that plugin's cloud mode (backend B) would not find it.

### 6.2 Is the AC3220 listed anywhere?

No. A case-insensitive search for `AC3220|AC3210|AC3221|AC32..|Unicorn|PureProtect|AC42|AC22` over the four cloned cloud repositories returned nothing, and the hb-airplus package filters for `HU1509`/`HU1510` only (`dist/cloud.js:105`).

Explicit statements about support:

| Project | Statement |
|---|---|
| node-red-contrib-philips-airplus | "AC3737 and other v3 protocol devices only" (`README.md:16`). The status node passes the raw `reported` object through (`payload.raw`) and the control node accepts a raw `{state:{desired:{...}}}` payload (`nodes/airplus-control.js:42-44`), so an untested v3 device can be read and written with raw keys. Its friendly fields are AC3737-specific (fan speed clamped to 1 to 2, `lib/parser.js:201-205`). |
| Ka3seBr0t/HA_Philips_Air_Plus | Verified on CX3550/01 only. No model filter: it sets up every device in `deviceList` as a fan (`__init__.py:84-116`). |
| ShorMeneses/philips-airplus-homeassistant | AC0650/10, AC0651/10, AC1715/11, /70, /71 (`README.md:17-25`). Its README tells owners of CoAP models to look at kongo09 first (`README.md:27`). |
| renaudallard/homeassistant_philips_homeid | Purifiers AC0650, AC0651, AC1715 only. "Not supported: ... the older Philips air devices that use the local encrypted CoAP protocol" (`README.md:25, 40`). The forum title's "Air Purifiers ... locally" does not cover the AC3220. |
| MaddogWarner homebridge `airplus-cloud` | AC0650, AC1715 (`README.md:398`). |

### 6.3 Evidence that the AC3220 is on backend A

1. **Platform.** AC3220/10 local status: `WifiVersion: AWS_Philips_AIR_Combo@3.0` (2024, kongo09 #181) and `AWS_Philips_AIR_Combo@86` with device firmware 0.2.3 (2026-04-02, HA forum thread 53030 post #470, an AC3220/10 bought in Australia). The CX3550/01 that Ka3seBr0t reads from the backend A shadow reports `WifiVersion: AWS_Philips_AIR_Combo@86` in that shadow (`notes/properties.md:55`). [V-code + H]
2. **Product registry.** `ProductId` values are version-1 UUIDs. Decoding them:

   | Device | ProductId | UUIDv1 time | clock seq | node |
   |---|---|---|---|---|
   | AC3737 "Carnation" (backend A, node-red) | `32681542d91811eda99406d016384e4a` | 2023-04-12 09:55:46 | 0x2994 | `06d016384e4a` |
   | CX3550 "Trident" (backend A, Ka3seBr0t) | `b3d240e5b11711ee88c206d016384e4a` | 2024-01-12 06:56:25 | 0x08c2 | `06d016384e4a` |
   | AC3220 "Unicorn" (local dump, kongo09 #181) | `768643a2b11811ee88c206d016384e4a` | 2024-01-12 07:01:52 | 0x08c2 | `06d016384e4a` |

   The AC3220 product id was generated by the same node, with the same clock sequence, 327 seconds after the CX3550 one. [I] Both products were created in the same registry in one sitting, and the CX3550 is confirmed on backend A.
   The `DeviceId` values are also UUIDv1. The AC3737 device id decodes to 2023-11-30 16:43:33, matching `activate_time: "2023-11-30-16"` in its `deviceList` entry. So the `DeviceId` a device shows over local CoAP is assigned by FogCloud at activation, and it is the cloud thing name. The AC3220 dump's `DeviceId` decodes to 2024-10-29, four days before that issue was opened.
3. **A sibling was found on backend A.** [WF] Ka3seBr0t issue #1 (opened 2026-08-25, no reply): the reporter has "my Philips AC3210 air purifier", says the integration "worked on first try without a glitch", and "I can only see the fan control (on/off, with speed)". The AC3210 is the same kongo09 class family as the AC3220. The fan-only result fits the code, which maps only the fan keys.
4. **A sibling is absent from backend B.** [WF] ShorMeneses issue #41, comment of 2026-10-31: an AC2221/13 that works in the Air+ app returns an empty device list from `/da/user/self/device` with both OAuth and email-code login. Same result for a CX3550/11 with an MXCHIP Wi-Fi chip in issue #21.

Confidence: high that the AC3220 is on backend A, medium that every step in section 4 behaves on it as on the AC3737/CX3550 (key meanings and write values are per model).

## 7. Cloud and local at the same time

**Does the device serve both at once? Yes.**
- [V-code] The CX3550/01 on `@86` firmware is read from the cloud shadow by Ka3seBr0t and over local CoAP by kongo09 (PR #365, issue #205; see `research/04-github-issues.md`). [WF] In ShorMeneses #21 a packet capture shows a CX3550/11 pushing CoAP on UDP 5683 while the Air+ app controls it.
- [V-code] The AC3220 local dump has `ConnectType: "Online"`. Old firmware dumps in py-air-control show `"ConnectType": "Localcontrol"`, `"StatusType": "localcontrol"` and an all-zero `DeviceId` (`rgerganov_py-air-control/Examples.md:104, 160`). [I] `ConnectType` in the local status reflects the device's own cloud link, which makes it a free "cloud connected" diagnostic.
- [H] hemtjanst/klimat README (AC3829): "these devices automatically send all their sensor data to Philips using AWS IoT, regardless of whether you are logged in to a Philips account ... you can isolate the device in its own VLAN and deny it access to the outside world. Everything will keep working".
- [H] kongo09, HA forum thread 53030: "The Philips app connects to the cloud and the device connects to the same cloud, so they don't talk directly even if on the same network." Against that: the Air+ APK bundles the Californium CoAP library next to Paho MQTT (node-red `docs/api-reverse-engineered.md:534-539`), and an AC4221 user reports the app still working with the purifier's internet access blocked (kongo09 #293). The app probably has a local path too. Unresolved.

**Does using the cloud disturb local CoAP sessions? No evidence that it does.**
- I found no report of a cloud MQTT client breaking a local observation. The reports go the other way: opening the app makes a silent device push again (see `research/04-github-issues.md`), which fits "a cloud command or a shadow get triggers a report".
- Cloud commands show up locally (`StatusType` flips to "control"), so a local observer stays consistent when the app or a cloud client changes something.
- The conflicts that are documented are cloud client against cloud client: one session per MQTT client id. Ka3seBr0t `README.md:101-103`: "Close the Philips phone app while Home Assistant is connected. If both hold a connection with the same client identity, AWS IoT disconnects one (rc 128)". The same author also writes that `mqttInfo` hands out a new `client_id` on every call (`notes/auth_refresh.md:48, 90-92`). These two statements do not fit together and nobody has measured it. Treat "HA cloud session and phone app at the same time" as untested on backend A.
- Blocking the purifier's internet access is the usual forum advice to stop firmware updates, and it obviously removes the cloud path. A design that needs the cloud therefore fights with the most common hardening step of local users.

**Open, and worth one experiment:** whether a cloud `shadow/get` also makes the device emit a local CoAP notification. If it does, the cloud could serve as a side-effect-free nudge for the push-on-change problem. Nobody has tested this.

## 8. Survey of projects that talk to the Air+ cloud

| Project | Backend | Platform | Devices tested | Auth UX | Status on 2026-11-22 |
|---|---|---|---|---|---|
| kwesolowski/node-red-contrib-philips-airplus (npm 0.2.0, 2026-02-08) | A | Node-RED | AC3737/10 | Playwright CLI or paste redirect URL; OAuth refresh kept although backend A does not need it | Active in git (17 reliability fixes on 2026-11-14/15), npm release is 9 months older; 1 issue ever |
| Ka3seBr0t/HA_Philips_Air_Plus (0.3.2, 2026-07-06) | A | HA custom, domain `philips_airplus`, `iot_class: cloud_push` | CX3550/01; user report AC3210 | upload own APK, email + code | No commits since 2026-07-06; issues #1, #3, #4 unanswered |
| kerdofficial/homebridge-philips-airplus (npm 0.1.0, 2026-09-22) | A | Homebridge | HU1509, HU1510 | type signing key, email + code | single release |
| ShorMeneses/philips-airplus-homeassistant (1.0.11) | B | HA custom, domain `philips_airplus` (same domain as Ka3seBr0t, they cannot coexist) | AC0650, AC0651, AC1715 | email + code, or paste redirect URL | No commits since 2026-07-05; 10 open issues; a user on 2026-11-09: "seems its no longer updated" [WF] |
| MaddogWarner/homebridge-philips-air-purifier-complete (4.2.0, 2026-11-03) | B (plus local CoAP/HTTP) | Homebridge, Python daemon | AC0650, AC1715 | email + code wizard | Active |
| renaudallard/homeassistant_philips_homeid (2026.11.1) | B (plus local HTTPS for kitchen devices) | HA custom | AC0650 (untested), AC0651, AC1715, airfryers | email + code | Very active |
| ioBroker.philips-air PR #406 "feat: add Philips Cloud support with email-code login" | B | ioBroker | AC0651 | email + code | [WF] Closed unmerged 2026-11-19. Maintainer: "with an unofficial API, the issues land on me the day Versuni changes something" |

Not found: any Python library on PyPI for either backend (`philips-airplus`, `pyairplus`, `aioairplus`, `philips-air-cloud`, `philips-homeid` all return 404), any Homey or openHAB cloud binding.

## 9. Viability for Home Assistant

### 9.1 Login UX

- Feasible as a normal config flow: email -> six-digit code -> pick device. For backend A that is two HTTP calls and yields the UID.
- The awkward part is the signing secret. Options seen: ship it (node-red), have the user upload the APK (Ka3seBr0t; needs the `file_upload` dependency and a sideloaded APK, hard for iPhone users, see Ka3seBr0t issue #3), or have the user paste the key (hb-airplus).
- Do not use the paste-the-redirect flow. Three projects moved away from it within weeks.
- Reauth must exist: Gigya errors, a changed account, or a rotated secret.

### 9.2 Token and connection robustness

Backend A is structurally simpler than backend B: no refresh token, a 7-day JWT that can always be re-minted, a 1-hour URL. The failures seen in the projects are client lifecycle bugs:

| Date | Project | Bug |
|---|---|---|
| 2026-01-07 | node-red `b2c3762` | client id collision while reconnecting for fresh credentials |
| 2026-02-07 | node-red `5acd33d`, issue #1 | refresh token revoked, node showed "Token expired" with no recovery |
| 2026-07-04 | Ka3seBr0t 0.3.0 | transient `16002`, treated as fatal |
| 2026-07-04 | Ka3seBr0t 0.3.0 | entities "available" while the device was offline |
| 2026-07-06 | Ka3seBr0t 0.3.2 | physical button changes not seen without polling |
| 2026-11-14 | node-red `619ce9b` | a failed first fetch at boot left the node dead until restart |
| 2026-11-15 | node-red `79bf5a3` | expired presigned URL reused after 50 min, dead until restart |

Rules a cloud transport would need: fetch `mqttInfo` for every connect; never reuse a URL; reconnect proactively before 60 min; retry 503 and 16002 with backoff; single-flight the JWT fetch; availability from `ConnectType` and from `metadata` timestamps, not from the socket; reconcile with `shadow/get`; confirm commands by a newer `reported` state.

### 9.3 How often did Philips change things?

- I found no breakage in 2026 that was caused by a change on Philips' side of backend A. The `app_id` dates from 2019.
- Air+ app releases come every 4 to 8 weeks (App Store NL listing [WF]: 3.21 on 23 Oct 2026, 3.20.0 on 7 Sep, 3.19.1 on 27 Jul, 3.19.0 on 8 Jun, 3.18.1 on 21 Apr, 3.18 on 18 Mar, 3.17 on 28 Jan). The one account-level change in the history is 3.7.0 on 2023-12-19, "Account service upgrade", asking users to sign in again. [I] That is the move to home.id.
- Backend B shows more churn in the clients (login handshake details, the `id_token`/`get-id` requirement, the HomeID profile endpoint returning HTTP 500, regional hosts), but that is not the AC3220's backend.
- Structural risks for backend A: one static app secret (Versuni can rotate it with an app update and every third-party client stops), Cloudflare in front of the API (bot rules can change), and the direction of travel: new models are ESP32 devices on backend B without local CoAP (`research/04-github-issues.md`, AC0650/AC0720). renaudallard `README.md:618-623` documents kitchen devices that lose their local API through an ordinary-looking firmware update. Nothing shows this happening to MXCHIP purifiers.

### 9.4 Latency

- Cloud: fresh report 1 to 2 s after a `get` (AC3737); MaddogWarner claims "State updates push within ~2 seconds" on backend B (`CHANGELOG.md:386`); hb-airplus allows 8 s for a command to be confirmed.
- Local CoAP for comparison: control writes answered in 109 to 211 ms, pushes 0.1 to 0.8 s after a change (`research/04-github-issues.md`, section F1).

### 9.5 Terms of service and legal position

- [WF] home.id Terms of Service (Versuni Nederland B.V., Dutch law, footer "(c) 2026 Versuni"): no clause on reverse engineering, automated access or unofficial clients was found in the terms themselves; the app software is "licensed and governed by the conditions of use" (a separate licence I did not read). Versuni "may (a) suspend or terminate your rights to access or use the Services" if it believes in good faith that the terms were violated.
- Ka3seBr0t `README.md:22-28` relies on the EU interoperability exception (Directive 2009/24/EC Art. 6) and for that reason refuses to distribute the secret. That is that author's reading, not legal advice.
- I found no report of an account being blocked for using these projects.
- Practical consequence: a cloud path that needs an extracted app secret cannot go into Home Assistant core, and committing the secret to a public repository is the one step the more careful authors avoid.

### 9.6 Privacy

- [WF] Versuni privacy notice for the app (last updated March 2024): the cloud processes "Device Data, including Device ID, running mode, power on/off, fan speed, scheduler, and control commands" and air quality data (allergen index, PM2.5, temperature, gas, humidity), plus the router's IP address at pairing. Storage "in Europe, US, Latin-American, Tokyo or Sydney and China". Location goes to AirMatters for outdoor air quality when that permission is on.
- [V-code] `deviceList` returns `activate_ip` and `mac`; redact both in diagnostics.
- A cloud transport adds an account email (sent to Gigya), a stored UID and a stored app secret to the Home Assistant config entry.
- The device reports to the cloud by itself as long as it has internet access, so using the cloud path does not create a new data flow from the device. Staying local-only and blocking the device's internet access is the only setup that stops it, and that setup excludes the cloud path.

## 10. Official third-party routes

| Route | Finding | Evidence |
|---|---|---|
| Amazon Alexa | Supported. Spec line "Voice control: Yes (Google, Alexa)" / "Spraakbediening: Ja (Google, Alexa)". The skill is called "the Philips Air Purifier skill", available "in some countries". | [V-web] Philips PRX product API, `https://www.philips.co.uk/prx/product/B2C/en_GB/CONSUMER/products/AC3220_10.specification` and the `nl_NL` variant; feature text "remote control and voice commands via Google and Alexa". [WF] privacy notice |
| Google Home / Assistant | Supported, same spec line. | same |
| Matter | No evidence of support. The words Matter, HomeKit, SmartThings and IFTTT occur zero times in the official summary, features, specification and disclaimers data for AC3220/10 in en_GB and nl_NL. A CSA certified-products search for "versuni" showed no entries, but I could not confirm the search filter was applied. | [V-web]; [WF] csa-iot.org |
| Apple Home / HomeKit | No official support found. Only through Homebridge or Home Assistant. | [V-web] absence |
| SmartThings | Nothing found. | [V-web] absence |
| IFTTT | kongo09 wrote in 2022 that "IFTTT uses it as well". I found no IFTTT service for Philips air purifiers today. | [H] HA forum 53030 post #276; web search |
| Public API or partner programme | None found. kongo09, 2022: "the API is not public ... I've written to Philips and asked for access but they haven't even replied." The OIDC provider advertises a `VoiceProvider.write` scope, which is how Alexa and Google are linked. | [H]; [V-live] |

Voice assistants as a bridge into Home Assistant: forum users drive the purifier through the Google Assistant SDK integration with text commands. On/off works, mode changes work for some models, nothing comes back ("You don't get the data back", thread 53030 posts #445 to #447, 2025). It is one-way, cloud-dependent and slow. Not a basis for an integration.

App-only features on the AC3220 according to the official feature list [V-web]: "Auto+ mode" ("AI technology that adapts to your routine"), "Scheduler: Yes (in app)" with "Fresh Wake-up" and "Fresh Bedtime", outdoor air quality. None of the cloud projects exposes schedules or Auto+, and I do not know whether they are stored on the device or in the cloud.

## 11. Recommendation

**Should the new integration include a cloud path? Not in the first release, and never in the critical path. Design for it, do not depend on it.**

Reasons against making the cloud a core part:
1. It gives no extra data. The shadow is the local status. Outdoor AQI comes from AirMatters, a different signed API, and Home Assistant has better sources. Filter ordering, schedules and Auto+ are not exposed by any known call.
2. It does not fix the main reliability problem. The cloud is push-on-change as well and needs polling.
3. It needs an app secret that cannot be obtained cleanly, which hurts the setup experience and blocks any path to Home Assistant core.
4. Every cloud project found is a single-maintainer effort, two of the three Home Assistant ones have been silent since July 2026, and the ioBroker maintainers rejected a cloud extension on maintenance grounds three days ago.
5. Local control is faster by an order of magnitude, private, and works with the device cut off from the internet.

Reasons to keep the door open:
1. Backend A is cheap to speak: about 150 lines for auth, a standard AWS shadow client, and the same DID vocabulary the integration already has.
2. It is a real fallback for cases local CoAP cannot solve: the device on another VLAN or guest network, or a future firmware that changes local behaviour. Section 9.3 explains why that is a watch item, not a present fact.
3. `shadow/get` gives a side-effect-free "send me a full report" request. The local equivalents are write-a-setting nudges.
4. `metadata` timestamps and `ConnectType` are a second opinion on availability.

Concrete design consequences:
- Model state as "dictionary of DIDs plus a source and a timestamp". Put a transport interface underneath: `connect()`, `subscribe(callback(status: dict, source, reported_at))`, `write(patch: dict)`, `request_refresh()`, `available`. The local CoAP transport implements it first. A cloud transport can then be added without touching entities, because both speak the same keys.
- Use `DeviceId` from the status as the config entry unique id and device identifier. It is the same value on both paths, so a later cloud transport attaches to the same device.
- Expose `ConnectType` as a diagnostic entity ("Cloud connection").
- If a cloud transport is added: opt-in per config entry, labelled experimental, email-code login, user-supplied signing key, reauth flow, redacted diagnostics (UID, key, `activate_ip`, `mac`, presigned URLs), `iot_class` stays `local_push` for the integration as a whole.
- Arbitration when both transports run: local wins when fresh; cloud fills in when local has been silent longer than a threshold; writes go local first and fall back to cloud only when the local write fails.

Suggested proof of concept before writing any cloud code (needs the user's device and account, about an hour):
1. Read `DeviceId`, `ProductId`, `WifiVersion`, `ConnectType` from the local status.
2. With a throwaway script: email code -> UID -> `getToken` -> `deviceList`. Check that the AC3220 is listed with `modelid` "AC3220/10", `type` "Unicorn" and the same `device_id`.
3. `mqttInfo` -> connect -> `shadow/get`. Diff `reported` against the local status.
4. While a local CoAP observation is running, publish `shadow/get` and see whether a local notification arrives.
5. Keep the phone app open during step 3 and watch for disconnects (rc 128).
6. Write one harmless key (for example the beep, `D03130`) through the shadow and watch the local status, including `StatusType`.

Steps 2 and 3 settle section 6. Step 4 decides whether the cloud is useful as a nudge.

## 12. Open questions

1. Is the AC3220/10 really in `enduser/deviceList` of backend A? Strong inference, not observed.
2. Does a cloud `shadow/get` trigger a local CoAP notification on the AC3220?
3. Can the phone app and a third-party client hold backend A sessions for the same device at the same time? The only source contradicts itself.
4. Lifetime of the home.id refresh token, and whether requesting `offline_access` changes it. Only relevant for backend B.
5. Does the Air+ app talk local CoAP to MXCHIP devices on current firmware, and is that the RSA/AES-GCM handshake from kongo09 PR #384?
6. Where do schedules and Auto+ live, and do they appear as DIDs?
7. Does `mSecret` differ by app version or region? One author says no; unverified.
8. Is there a Matter roadmap for PureProtect? No public statement found.
9. Which regions exist for backend A besides `eu-central-1`? The capture mentions `fog-da.philips.com.cn`.

## 13. Sources

Code (cloned or unpacked under `scratchpad/src` and `scratchpad/dl06`): see the table in section 0.

Web:
- https://registry.npmjs.org/node-red-contrib-philips-airplus , https://registry.npmjs.org/homebridge-philips-airplus , https://registry.npmjs.org/homebridge-philips-air-purifier-complete
- https://cdc.accounts.home.id/oidc/op/v1.0/4_JGZWlP8eQHpEqkvQElolbA/.well-known/openid-configuration (fetched 2026-11-22)
- https://www.api.air.philips.com/device/serverTime/ and /enduser/deviceList/ (unauthenticated, 2026-11-22)
- https://prod.eu-da.iot.versuni.com/api/da/user/self/device (unauthenticated, 2026-11-22)
- https://www.philips.co.uk/prx/product/B2C/en_GB/CONSUMER/products/AC3220_10.specification , `.features`, `.summary`, `.disclaimers`, and the same for `nl_NL` (saved in `scratchpad/web06/prx`)
- https://www.home-appliances.philips/nl/nl/p/AC3220_10 (JavaScript shell only)
- https://www.philips.com/a-w/mobile-privacy-notice/clean-home-app.html
- https://www.home.id/policy/terms-of-service
- https://apps.apple.com/nl/app/philips-air/id1487415423
- https://github.com/Ka3seBr0t/HA_Philips_Air_Plus/issues/1 and /issues/3
- https://github.com/ShorMeneses/philips-airplus-homeassistant/issues (list), /issues/5, /20, /21, /25, /38, /39, /40, /41
- https://github.com/kongo09/philips-airpurifier-coap/issues/205 and /issues/181
- https://github.com/iobroker-community-adapters/ioBroker.philips-air/pull/406
- https://github.com/MaddogWarner/homebridge-philips-air-purifier-complete/issues
- https://github.com/kwesolowski/node-red-contrib-philips-airplus/issues
- https://raw.githubusercontent.com/hemtjanst/klimat/master/README.md
- https://community.home-assistant.io/t/philips-air-purifier/53030 (posts #276, #445 to #447, #468, #470; from the copy another agent saved in `scratchpad/forum`)
- https://community.home-assistant.io/t/philips-homeid-integration-control-your-philips-airfryers-air-purifiers-multicookers-locally/998744
- https://community.home-assistant.io/t/philips-cx3550-current-best-way-to-connect/1022131
- https://csa-iot.org/csa-iot_products/ (keyword search, inconclusive)

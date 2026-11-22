# Metingen op een echte AC3220/10

Dit logboek houdt bij wat op een echte luchtreiniger is gemeten met [het meetprogramma](../tools/probe/README.md). Het vult [het onderzoeksrapport](onderzoek.md) aan: wat daar een aanname was en hier staat, is nu gemeten op één apparaat.

| | |
|---|---|
| Apparaat | AC3220/10, platform `Unicorn`, nieuw (filtertellers nog op de beginwaarde) |
| Apparaatfirmware | `0.2.3` |
| Wifi-firmware | `AWS_Philips_AIR_Combo@86` |
| Client | Meetprogramma 0.1.0 op macOS, Python 3.14, zelfde subnet |

## 22 november 2026

### Meting 1: `quick`, apparaat aan op Turbo

| Onderwerp | Uitkomst |
|---|---|
| Info-aanvraag | 2 van 3 beantwoord, mediaan 488 ms. Antwoord: `modelid` AC3220/10, `type` Unicorn, `swversion` 0.0.0, `option` 119 |
| Sync | 3 van 3, mediaan 122 ms |
| Lege CoAP-ping | 3 van 3, mediaan 25 ms |
| Verzoeken met ontvangstbevestiging | Info en sync worden beantwoord |
| Identiteit | `device_id` uit de info-aanvraag is gelijk aan `DeviceId` in de status |
| Statusbericht | 1942 bytes, gefragmenteerd, zonder ontvangstbevestiging, Max-Age 60 |
| Statusaanvraag zonder abonnement | Niet beantwoord binnen 5 s |
| Stroom terwijl het apparaat draait | 12 berichten in 60 s, langste stilte 28 s |
| Sleutels | 58, waaronder `D03112`, `D03115`, `D03134`, `D03137`, `D03125`, `D03224` |

Het eerste statusbericht kwam 1,2 s na de abonnementsaanvraag. Omdat het apparaat toen uit zichzelf elke paar seconden iets stuurde, bewijst dat geen direct antwoord. Meting 2 laat zien dat het toeval was.

Waarden uit de status die voor het ontwerp tellen: `D0310C` 18 en `D0310D` 18 op Turbo; `D03134` 0 (sensoren in stand-by uit); `D03105` 101; `D03135` 2; `D03137` 4; `D0311F` 1 (in eerdere dumps van anderen 0; betekenis onbekend).

### Meting 2: `quick`, apparaat in stand-by

| Onderwerp | Uitkomst |
|---|---|
| Info-aanvraag | 3 van 3, mediaan 519 ms |
| Sync | 3 van 3, mediaan 91 ms |
| Lege CoAP-ping | 3 van 3, mediaan 112 ms |
| Abonnementsaanvraag | Geen antwoord in 70 s |
| Schrijven van het kinderslot (`D03103` naar 1 en terug naar 0) | Beide keren `success`, na 77 en 13 ms. Geen statusbericht in de 60 s daarna. |
| Teller | Elke sync geeft een nieuwe, niet-oplopende waarde (`75A6BB10`, daarna `0F6C0B91`) |

### Meting 3: `set D03102=1`, apparaat in stand-by

| Onderwerp | Uitkomst |
|---|---|
| Antwoord op de schrijfopdracht | `success` na 12 ms |
| Het apparaat | Ging aan |
| Statusbericht | 1,09 s na de opdracht, op een abonnement dat in stand-by was aangevraagd |
| `StatusType` in dat bericht | `status`, niet `control` |

## Wat dit vastlegt

| Bevinding | Gevolg voor het ontwerp |
|---|---|
| In stand-by is het apparaat bereikbaar maar stil: alle drie de controles antwoorden, een abonnement niet | Bevestigt de kern van hoofdstuk 6: bereikbaarheid los van de statusstroom meten, nooit op een statusbericht wachten, de laatst bekende toestand bewaren |
| Een abonnement dat in stand-by is aangevraagd, levert zodra er iets verandert | Abonneren bij het opstarten heeft zin, ook als het apparaat uit staat |
| Aanzetten vanuit stand-by werkt, met een terugmelding na ongeveer een seconde | De ventilator-entiteit kan het apparaat inschakelen; een deadline van 5 s voor de bevestiging is ruim |
| De terugmelding van een schrijfopdracht heeft `StatusType` `status` | `StatusType` is niet bruikbaar om een bericht aan een commando te koppelen |
| Het kinderslot schrijven in stand-by geeft `success` maar geen statusbericht | Nog uitzoeken of de waarde dan wel wordt opgeslagen. Zo niet, dan moeten instellingen in stand-by niet bedienbaar zijn; zo ja, dan mag een uitblijvende terugmelding in stand-by geen fout zijn. |
| De info-aanvraag is traag (ongeveer een halve seconde) en miste één keer | Geschikt voor herkenning, minder voor een frequente bereikbaarheidscontrole. Ping en sync zijn sneller. |
| Verzoeken met ontvangstbevestiging worden beantwoord | Commando's kunnen met ontvangstbevestiging worden gestuurd, wat verlies op netwerkniveau zichtbaar maakt |
| De status komt gefragmenteerd aan | Fragmenten moeten tussen Home Assistant en het apparaat worden doorgelaten |

## Nog te meten

| Vraag | Opdracht |
|---|---|
| Blijft een abonnement zonder vernieuwing leveren? | `lapse` |
| Wordt een instelling die in stand-by is geschreven wel opgeslagen? | In stand-by `set D03103=1`, daarna aanzetten en de status bekijken |
| Welke schrijfopdrachten werken? | `write-matrix` |
| Hoe vernieuw je een abonnement, en met welk kenmerk? | `refresh` |
| Welke controle blijft antwoorden gedurende uren stilte? | `liveness` in stand-by |
| Eén of meer abonnees per adres; gedeelde teller? | `second-client` |
| Wordt afmelden gerespecteerd? | `deregister` |
| Gedrag na een stroomonderbreking | `power-cycle` |
| Storen de app en een lokale client elkaar? | `app` |
| Vindbaar via broadcast of multicast? | `discover` |

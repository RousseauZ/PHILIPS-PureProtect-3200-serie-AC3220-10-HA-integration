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

### Meting 4: `lapse`, apparaat aan

Eén abonnement, zonder vernieuwing en zonder enig ander verkeer van de client.

| Controlepunt | Uitkomst |
|---|---|
| 3, 5, 10 en 20 minuten | Het abonnement leverde telkens nog, zonder dat een knopdruk nodig was |

### Meting 5: kinderslot in stand-by en daarna

Zes losse `set`-opdrachten achter elkaar.

| # | Toestand | Opdracht | Antwoord | Statusbericht |
|---|---|---|---|---|
| 1 | Stand-by | `D03103=1` | `success` na 13 ms | Geen |
| 2 | Stand-by | `D03102=1` | `success` na 13 ms | Na 0,19 s, `StatusType` `control`; het apparaat ging aan |
| 3 | Aan | `D03103=0` | `success` na 12 ms | De status toonde vooraf al 0. Toch een bericht na 0,12 s, `StatusType` `control` |
| 4 | Aan | `D03103=1` | `success` na 11 ms | Na 0,62 s, `StatusType` `control`; het kinderslot ging aan |
| 5 | Aan | `D03103=0` | `success` na 8 ms | Na 0,10 s, `StatusType` `control`; het kinderslot ging uit |
| 6 | Aan | `D03102=0` | `success` na 16 ms | Na 0,11 s, `StatusType` `control`; het apparaat ging uit |

Regel 3 laat zien dat de opdracht uit regel 1 niet is uitgevoerd: na het aanzetten stond het kinderslot nog uit. De eigenaar zag hetzelfde op het apparaat.

## Wat dit vastlegt

| Bevinding | Gevolg voor het ontwerp |
|---|---|
| In stand-by is het apparaat bereikbaar maar stil: alle drie de controles antwoorden, een abonnement niet | Bevestigt de kern van hoofdstuk 6: bereikbaarheid los van de statusstroom meten, nooit op een statusbericht wachten, de laatst bekende toestand bewaren |
| Een abonnement dat in stand-by is aangevraagd, levert zodra er iets verandert | Abonneren bij het opstarten heeft zin, ook als het apparaat uit staat |
| Aan- en uitzetten vanaf het netwerk werkt. Aanzetten vanuit stand-by wordt na 0,2 tot 1,1 s teruggemeld, uitzetten na 0,1 s | De ventilator-entiteit kan het apparaat in- en uitschakelen; een deadline van 5 s voor de bevestiging is ruim |
| De terugmelding van een schrijfopdracht heeft meestal `StatusType` `control` (na 0,1 tot 0,6 s), maar één keer `status` (na 1,09 s) | `StatusType` is niet betrouwbaar om een bericht aan een commando te koppelen. Een deadline van 5 s voor de bevestiging is ruim. |
| Een instelling die in stand-by wordt geschreven, krijgt `success` maar wordt niet uitgevoerd (gemeten voor het kinderslot) | Instellingen zijn in Home Assistant niet bedienbaar terwijl het apparaat uit staat. `success` is geen bewijs dat een opdracht is uitgevoerd. |
| Een abonnement blijft minstens 20 minuten leveren zonder vernieuwing, terwijl het apparaat draait | Het verloop na ongeveer 150 s dat bij een AC4220/12 is gemeld, treedt hier niet op. Vernieuwen is een vangnet, geen noodzaak. |
| Een opdracht met de waarde die al gold, geeft met het apparaat aan toch een statusbericht (na 0,12 s) | Anders dan bij de AMF870 uit het onderzoek. Dit is een manier om zonder bijwerking een verse status op te vragen. Of het ook in stand-by werkt, is nog niet gemeten. |
| De info-aanvraag is traag (ongeveer een halve seconde) en miste één keer | Geschikt voor herkenning, minder voor een frequente bereikbaarheidscontrole. Ping en sync zijn sneller. |
| Verzoeken met ontvangstbevestiging worden beantwoord | Commando's kunnen met ontvangstbevestiging worden gestuurd, wat verlies op netwerkniveau zichtbaar maakt |
| De status komt gefragmenteerd aan | Fragmenten moeten tussen Home Assistant en het apparaat worden doorgelaten |

## Nog te meten

| Vraag | Opdracht |
|---|---|
| Blijft een abonnement ook leveren na lange stilte in stand-by? | `lapse` in stand-by, met de aan/uit-knop als verandering |
| Geeft een opdracht met de huidige waarde ook in stand-by een statusbericht? | In stand-by `set D03102=0` |
| Welke schrijfopdrachten werken? | `write-matrix` |
| Hoe vernieuw je een abonnement, en met welk kenmerk? | `refresh` |
| Welke controle blijft antwoorden gedurende uren stilte? | `liveness` in stand-by |
| Eén of meer abonnees per adres; gedeelde teller? | `second-client` |
| Wordt afmelden gerespecteerd? | `deregister` |
| Gedrag na een stroomonderbreking | `power-cycle` |
| Storen de app en een lokale client elkaar? | `app` |
| Vindbaar via broadcast of multicast? | `discover` |

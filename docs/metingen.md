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

Zeven losse `set`-opdrachten achter elkaar.

| # | Toestand | Opdracht | Antwoord | Statusbericht |
|---|---|---|---|---|
| 1 | Stand-by | `D03103=1` | `success` na 13 ms | Geen |
| 2 | Stand-by | `D03102=1` | `success` na 13 ms | Na 0,19 s, `StatusType` `control`; het apparaat ging aan |
| 3 | Aan | `D03103=0` | `success` na 12 ms | De status toonde vooraf al 0. Toch een bericht na 0,12 s, `StatusType` `control` |
| 4 | Aan | `D03103=1` | `success` na 11 ms | Na 0,62 s, `StatusType` `control`; het kinderslot ging aan |
| 5 | Aan | `D03103=0` | `success` na 8 ms | Na 0,10 s, `StatusType` `control`; het kinderslot ging uit |
| 6 | Aan | `D03102=0` | `success` na 16 ms | Na 0,11 s, `StatusType` `control`; het apparaat ging uit |
| 7 | Stand-by | `D03102=0` | `success` na 8 ms | Geen, in 10 s |

Regel 3 laat zien dat de opdracht uit regel 1 niet is uitgevoerd: na het aanzetten stond het kinderslot nog uit. De eigenaar zag hetzelfde op het apparaat.

### Meting 6: `watch`, rondgang door de Air+ app

Het meetprogramma luisterde zeven minuten mee terwijl de eigenaar in de app instellingen wijzigde. Het abonnement bleef al die tijd leveren; de app en een lokale client vanaf een ander adres zitten elkaar dus niet in de weg.

| Sleutel | Waargenomen waarden | Betekenis |
|---|---|---|
| `D03102` | 0, 1 | Uit, aan |
| `D0310C` | 0, 17, 19, 18 | Auto, slaap, medium, turbo |
| `D0310C` | 1, 2, 3, 4, 5 | Handmatige snelheid 1 tot 5 |
| `D0310C` | -16 | Waarde terwijl het apparaat uit staat |
| `D0310D` | 1, 2, 3, 4, 18; 0 als het apparaat uit staat | Werkelijk toerental. Snelheid 5 en turbo geven allebei 18; snelheid 3 en medium geven allebei 3; auto en slaap gaven 1 |
| `D03180` | 0, 1 | Auto+ |
| `D03115` | 0, 1 | Allergie-slaap |
| `D03134` | 0, 1 | Sensoren in stand-by |
| `D03130` | 100, 0 | Pieptoon aan, uit |
| `D03103` | 0, 1 | Kinderslot |
| `D03110` | 0; 2 tot 13 | Timer uit; 1 tot 12 uur |
| `D03211` | 60, 120, tot 720; daarna 719, 718 | Resterende timertijd in minuten. Telt elke minuut af, dus met een lopende timer komt er elke minuut een statusbericht |
| `D03105` | 101, 123, 115, 0 | Helderheid: automatisch, fel, laag, uit |
| `D03135` | 0, 1, 2 | Lampfunctie: uit, luchtkwaliteit, sfeerlicht |
| `D03137` | 1, 2, 3, 4 | Lichtscène |
| `D03112` | 0, 1 | Een schakelaar in de app; naam nog na te vragen |
| `D0311F` | 0, 1 | Onbekend. Werd 1 ongeveer 30 s nadat snelheid 5 was gekozen (2 minuten na het aanzetten) en ging terug naar 0 bij het uitzetten |
| `D0520D` | 719 naar 720 | De teller voor het reinigen van het filter sprong terug naar de beginwaarde; oorzaak nog na te vragen |

Samenhang die de app zelf aanbrengt:

- Helderheid "uit" zette in hetzelfde bericht ook de lampfunctie uit (`D03105` 0 en `D03135` 0).
- Het kiezen van sfeerlicht zette de helderheid terug op automatisch (`D03105` 101, `D03135` 2) en koos een scène.
- Uitzetten zette de timer en `D0311F` terug op 0.
- Na een wijziging van de stand volgt het toerental 0,1 tot 1 s later in een apart bericht.

Niet veranderd tijdens de rondgang: `D0312A`, `D0312B`, `D0312C`, `D03106`, `D03136`, `D0313B`, `D03182`, `D03R81`, `D05102` en de `D011xx`-reeks.

### Meting 7: tweede rondgang, licht en display, met toelichting van de eigenaar

| Waarneming | Uitkomst |
|---|---|
| `D03112` | Is de schakelaar "Display" in de app. Stond op 0 bij een brandend display en werd 1 bij uitzetten: 0 is aan, 1 is uit |
| Helderheid van het sfeerlicht | Geen eigen sleutel. Het is `D03105`, met dezelfde vier waarden (automatisch 101, fel 123, laag 115, uit 0), voor elke scène en ook voor de lampfunctie luchtkwaliteit |
| Helderheid "uit" | Zet telkens ook de lampfunctie uit (`D03135` naar 0) |
| Een scène of lampfunctie kiezen | Zet de helderheid terug op automatisch (`D03105` naar 101) en de lampfunctie op 2 (sfeerlicht) of 1 (luchtkwaliteit) |
| De sprong van `D0520D` in meting 6 | Was de knop "filter gereinigd" in de app. De app kan de reinigingsteller dus terugzetten, en dat is lokaal zichtbaar |
| Meldingen en weekschema wijzigen in de app | Lokaal veranderde er niets |
| `D0311F` | Werd weer 1, nu op hetzelfde moment als een wijziging van het display, en bleef 1 bij verder schakelen. Hangt dus niet aan het display. Twee verklaringen passen: ongeveer twee minuten na het aanzetten, of een halve minuut op het hoogste toerental |

### Meting 8: `refresh`, apparaat aan

| Onderwerp | Uitkomst |
|---|---|
| Eerste statusbericht na een nieuw abonnement | Na 0,2 s |
| Vernieuwen met hetzelfde kenmerk | De ene vernieuwing die te beoordelen was (het was stil vlak ervoor) kreeg geen antwoord binnen 1,5 s. Twee waren niet te beoordelen. |
| Na een verandering | 5 berichten, geen dubbele |
| Abonneren met een nieuw kenmerk vanaf dezelfde poort | Daarna 0 berichten op het oude kenmerk en 4 op het nieuwe: het nieuwe abonnement vervangt het oude |

### Meting 9: `second-client`, twee clients vanaf dezelfde computer

| Onderwerp | Uitkomst |
|---|---|
| Client B abonneert vanaf een andere poort | Daarna ontvangt A niets meer en B alles: de nieuwste abonnee verdringt de oudste |
| Verzonnen teller | `failed`: het apparaat controleert de teller |
| A synct, B synct, A schrijft, B schrijft | A `failed`, B `success`: de laatste sync bepaalt de geldige teller voor alle clients vanaf dit adres |

### Meting 10: `deregister`

| Onderwerp | Uitkomst |
|---|---|
| Afmelden (Observe 1) | Niet gerespecteerd: er kwamen nog 4 berichten |
| Een statusbericht beantwoorden met een reset | Niet gerespecteerd: er kwamen nog 2 berichten |

### Meting 11: `discover`

Vijf rondes; per ronde gingen vier info-aanvragen tegelijk uit.

| Doel | Beantwoord door de luchtreiniger |
|---|---|
| Broadcast 255.255.255.255 | 2 van 5 |
| Broadcast van het subnet | 2 van 5 |
| Multicast 224.0.1.187 | 0 van 5 |
| Rechtstreeks | 3 van 5 |

Een ander apparaat in het netwerk, een LG-televisie, antwoordde ook op de broadcast en de multicast, met een antwoord zonder `modelid`, `type` of `device_id`.

### Eerste statusbericht na een nieuw abonnement, over alle metingen

| Toestand | Tijd tot het eerste bericht |
|---|---|
| Aan (zes metingen) | 0,2 s, 0,8 s, 1,2 s, 1,4 s, 1,9 s en 1,9 s |
| Stand-by (twee metingen) | Geen bericht in 70 s; geen bericht tot het apparaat werd aangezet |

Zes keer binnen twee seconden is geen toeval: met het apparaat aan beantwoordt het een nieuw abonnement vanaf een nieuwe poort binnen ongeveer twee seconden. In stand-by niet.

## Wat dit vastlegt

| Bevinding | Gevolg voor het ontwerp |
|---|---|
| In stand-by is het apparaat bereikbaar maar stil: alle drie de controles antwoorden, een abonnement niet | Bevestigt de kern van hoofdstuk 6: bereikbaarheid los van de statusstroom meten, nooit op een statusbericht wachten, de laatst bekende toestand bewaren |
| Een abonnement dat in stand-by is aangevraagd, levert zodra er iets verandert | Abonneren bij het opstarten heeft zin, ook als het apparaat uit staat |
| Aan- en uitzetten vanaf het netwerk werkt. Aanzetten vanuit stand-by wordt na 0,2 tot 1,1 s teruggemeld, uitzetten na 0,1 s | De ventilator-entiteit kan het apparaat in- en uitschakelen; een deadline van 5 s voor de bevestiging is ruim |
| De terugmelding van een schrijfopdracht heeft meestal `StatusType` `control` (na 0,1 tot 0,6 s), maar één keer `status` (na 1,09 s) | `StatusType` is niet betrouwbaar om een bericht aan een commando te koppelen. Een deadline van 5 s voor de bevestiging is ruim. |
| Een instelling die in stand-by wordt geschreven, krijgt `success` maar wordt niet uitgevoerd (gemeten voor het kinderslot) | Instellingen zijn in Home Assistant niet bedienbaar terwijl het apparaat uit staat. `success` is geen bewijs dat een opdracht is uitgevoerd. |
| Een abonnement blijft minstens 20 minuten leveren zonder vernieuwing, terwijl het apparaat draait | Het verloop na ongeveer 150 s dat bij een AC4220/12 is gemeld, treedt hier niet op. Vernieuwen is een vangnet, geen noodzaak. |
| Een opdracht met de waarde die al gold, geeft met het apparaat aan toch een statusbericht (na 0,12 s), maar in stand-by niet | Anders dan bij de AMF870 uit het onderzoek. Met het apparaat aan is dit een manier om zonder bijwerking een verse status op te vragen. In stand-by bestaat die manier niet: de integratie toont dan de bewaarde toestand tot er iets verandert. |
| De info-aanvraag is traag (ongeveer een halve seconde) en miste één keer | Geschikt voor herkenning, minder voor een frequente bereikbaarheidscontrole. Ping en sync zijn sneller. |
| Verzoeken met ontvangstbevestiging worden beantwoord | Commando's kunnen met ontvangstbevestiging worden gestuurd, wat verlies op netwerkniveau zichtbaar maakt |
| De status komt gefragmenteerd aan | Fragmenten moeten tussen Home Assistant en het apparaat worden doorgelaten |
| Het apparaat bedient één abonnee per adres; de nieuwste aanvraag wint | De integratie opent nooit een tweede abonnement. Elk ander programma dat vanaf de Home Assistant-computer abonneert (een oude integratie, een test op de opdrachtregel) neemt de stroom over. De periodieke vernieuwing haalt hem dan terug. |
| Een nieuw kenmerk vervangt het oude direct | Overstappen op een nieuw kenmerk kan zonder overgangsperiode |
| Afmelden en een reset worden genegeerd | Bij het stoppen valt er niets af te melden. Het apparaat blijft naar de laatste abonnee sturen tot een nieuwe zich meldt; dat is onschadelijk. |
| Clients vanaf hetzelfde adres delen één teller; de laatste sync telt | Bevestigt: sync direct vóór elk commando, onder één slot. Een sync als bereikbaarheidscontrole kan de teller van een andere client ongeldig maken; de ping heeft dat nadeel niet. |
| Met het apparaat aan beantwoordt het een nieuw abonnement binnen ongeveer 2 s; een vernieuwing met hetzelfde kenmerk niet | Bij het opstarten van Home Assistant komt de status vanzelf binnen als het apparaat aan staat. Vernieuwen met hetzelfde kenmerk is alleen een vangnet en levert zelf geen status op. |
| De info-aanvraag wordt vaak niet beantwoord, zeker bij meerdere tegelijk (7 van 15) | Herkenning vraagt drie tot vijf pogingen, één tegelijk, met een seconde ertussen |
| Het apparaat is vindbaar via broadcast, niet via multicast; een ander apparaat in het netwerk antwoordt ook op poort 5683 | Automatisch zoeken via broadcast met herhalingen. Elk antwoord streng controleren op `device_id`, `product_id` en een bekend model. |

## Functiedekking

Doel: elke functie die het apparaat lokaal prijsgeeft, is beschikbaar in de integratie. Deze tabel houdt bij hoe ver dat is aangetoond op het echte apparaat.

| Functie | Sleutel | Lezen | Bedienen |
|---|---|---|---|
| Aan en uit | `D03102` | Gemeten | Gemeten |
| Kinderslot | `D03103` | Gemeten | Gemeten (alleen met het apparaat aan) |
| Standen auto, slaap, medium, turbo | `D0310C` | Gemeten | Nog te meten |
| Handmatige snelheden 1 tot 5 | `D0310C` | Gemeten | Nog te meten |
| Werkelijk toerental | `D0310D` | Gemeten | Alleen-lezen |
| Allergie-slaap | `D03115` | Gemeten | Nog te meten |
| Auto+ | `D03180` | Gemeten | Nog te meten |
| Fijnstof, allergenenindex, temperatuur, vochtigheid | `D03221`, `D03120`, `D03224`, `D03125` | Gemeten | Alleen-lezen |
| Filter: resterende levensduur en reiniging | `D0540E`, `D05408`, `D0520D`, `D05207` | Gemeten | De app zet de reinigingsteller terug naar de beginwaarde (gezien: 719 naar 720); of dat lokaal te schrijven is, is nog te meten |
| Pieptoon | `D03130` | Gemeten | Nog te meten |
| Timer | `D03110`, `D03211` | Gemeten | Nog te meten |
| Sensoren in stand-by | `D03134` | Gemeten | Nog te meten |
| Weergegeven index op het display | `D0312A` | In de status; niet als instelling in de app gezien | Nog te meten |
| Drempel voor meldingen | `D0312C` | In de status; meldingen wijzigen in de app veranderde de waarde niet | Nog te meten |
| Helderheid van het licht, ook van het sfeerlicht | `D03105` | Gemeten | Nog te meten; op verwante modellen alleen-lezen. De app schrijft "uit" samen met lampfunctie uit |
| Display aan of uit | `D03112` (0 aan, 1 uit) | Gemeten | Nog te meten |
| Lampfunctie van de lichtring | `D03135` | Gemeten | Nog te meten |
| Lichtscène | `D03137` | Gemeten | Nog te meten; op verwante modellen niet schrijfbaar. De app schrijft een scène samen met helderheid en lampfunctie |
| Storing of foutcode | `D03240` | In de status | Alleen-lezen |
| Wifi-signaal, firmwareversies, looptijd | `rssi`, `D01S12`, `WifiVersion`, `Runtime` | Gemeten | Alleen-lezen |

Niet lokaal beschikbaar: het weekschema en de instellingen voor meldingen (gemeten: wijzigen in de app verandert lokaal niets), en voor zover bekend ook de luchtkwaliteit buiten, grafieken en firmware-updates. Die lopen via de app en de cloud. Home Assistant heeft daar eigen middelen voor (automatiseringen, geschiedenis, een weerdienst).

Sleutels zonder bekende betekenis: `D03106`, `D0311F`, `D03136`, `D0313B`, `D03182`, `D03R81`, `D05102` en de `D011xx`-reeks. Behalve `D0311F` veranderde geen ervan tijdens de rondgang door de app; het zijn dus vermoedelijk geen instellingen die de gebruiker bedient.

## Nog te meten

| Vraag | Opdracht |
|---|---|
| Blijft een abonnement ook leveren na lange stilte in stand-by? | `lapse` in stand-by, met de aan/uit-knop als verandering |
| Welke schrijfopdrachten werken, ook de combinaties die de app voor het licht gebruikt? | `write-matrix` |
| Zijn de filtertellers lokaal te schrijven? | Met het apparaat aan `set D0520D=719`, daarna `set D0520D=720` |
| Welke controle blijft antwoorden gedurende uren stilte? | `liveness` in stand-by |
| Bedient het apparaat abonnees vanaf verschillende adressen tegelijk? | `observe` op twee computers tegelijk |
| Gedrag na een stroomonderbreking | `power-cycle` |
| Storen de app en een lokale client elkaar? | Tijdens de rondgang niet; `app` test daarnaast of onze controles de app hinderen |

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
| Abonneren met een nieuw kenmerk vanaf dezelfde poort | Daarna 0 berichten op het oude kenmerk en 4 op het nieuwe: het nieuwe abonnement vervangt het oude. Of de aanvraag zelf werd beantwoord was niet te beoordelen |

Kanttekening bij deze meting: het venster voor een antwoord was 1,5 s, terwijl een nieuw abonnement vanaf een nieuwe poort tot 1,9 s nodig had. "Vernieuwen met hetzelfde kenmerk wordt niet beantwoord" steunt dus op één waarneming met een te kort venster. De meting is daarom herschreven (venster 3 s, zes rondes, met een vergelijkingsvenster zonder aanvraag) en moet opnieuw.

### Meting 9: `second-client`, twee clients vanaf dezelfde computer

| Onderwerp | Uitkomst |
|---|---|
| Client B abonneert vanaf een andere poort | Binnen 1,5 s geen antwoord op de aanvraag zelf. Daarna ontvangt A niets meer en B alles: de nieuwste abonnee verdringt de oudste |
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

### Meting 12: `liveness`, acht uur in de nacht

Bedoeld als meting van stilte in stand-by, maar het apparaat stond aan: de terugblik toont aan/uit 1, handmatige snelheid 1 en "sensoren in stand-by" uit, de hele nacht ongewijzigd. Stilte in stand-by is dus nog niet gemeten.

| Onderwerp | Uitkomst |
|---|---|
| Sync | 960 van 960 beantwoord, mediaan 125 ms, traagste 483 ms |
| Info-aanvraag | 960 van 960 beantwoord, mediaan 660 ms, traagste 1294 ms |
| CoAP-ping | 960 van 960 beantwoord, mediaan 126 ms, traagste 449 ms |
| Statusberichten | 8859 in acht uur, gemiddeld één per 3,3 s; langste periode zonder wijziging 85 s |
| Berichten die alleen de bekende status herhaalden | 10 van de 8859 |
| Vernieuwen met hetzelfde kenmerk, elke minuut | 480 keer verstuurd; het abonnement bleef acht uur leveren. Binnen 3 s volgde 261 keer een bericht, nooit een herhaling van de status. Op 479 momenten zonder aanvraag: 264 keer een bericht, 4 keer een herhaling. **Niet beantwoord.** |
| Wat de berichten veroorzaakte | De temperatuur (`D03224`) veranderde 8534 keer, gemiddeld elke 3 s: ze springt heen en weer tussen twee tienden van een graad. Fijnstof 247 keer, vochtigheid 164 keer, allergenenindex 26 keer |
| Tijd tussen statusberichten | Mediaan 1,3 s, 95% binnen 11,2 s, langste 85 s |
| Eerste aanvraag | Binnen 3 s geen leesbaar bericht. Zes berichten in de nacht waren niet te lezen; waarom, toont de terugblik sinds 23 november |
| Sync-teller | Bij elke sync een andere, niet oplopende waarde |

Terugkijken op een afgeronde meting kan zonder opnieuw te meten:

```bash
python -m pureprotect_probe.inspect_run metingen/20261122-214359-liveness
```

Dat toont of het apparaat aan stond, welke waarden hoe vaak veranderden en wat er op elke vernieuwing volgde.

### Meting 13: `refresh`, apparaat aan

Per soort zes vensters van 3 s, elk begonnen na 4 s stilte.

| Soort | Vensters met een bericht | Waarvan een herhaling van de bekende status |
|---|---|---|
| Zonder aanvraag (vergelijking) | 1 van 6 | 0 |
| Vernieuwen met hetzelfde kenmerk | 4 van 6 | 1 |
| Nieuw kenmerk vanaf dezelfde poort | 0 van 6 | 0 |

- Eerste abonnement: beantwoord na 2,1 s.
- Een nieuw kenmerk vanaf dezelfde poort wordt **niet beantwoord**, maar neemt de stroom wel over: op de vervangen kenmerken kwam daarna niets meer.
- Het programma noemde vernieuwen met hetzelfde kenmerk "beantwoord", op zes vensters en precies op de drempel. De acht uur van meting 12 (480 keer, geen enkele herhaling) wegen zwaarder: **niet beantwoord**.

### Meting 14: `write-matrix`, apparaat aan

Alle gewijzigde instellingen zijn daarna teruggezet en bevestigd.

| Onderwerp | Uitkomst |
|---|---|
| Aan en uit, standen, snelheden 1 tot 5 | Alles teruggemeld, meestal na 0,2 tot 0,6 s. Eén keer 4,7 s: slaapstand, met `StatusType` `status` |
| Lampfunctie, helderheid, scène, display, alleen en in de combinaties van de app | Alles teruggemeld, na 0,1 tot 0,6 s |
| Kinderslot, pieptoon, Auto+, Allergie-slaap, sensoren in stand-by | Alles teruggemeld |
| Timer (1 uur en weer uit) | Teruggemeld |
| Drempel voor meldingen `D0312C` | Teruggemeld (na 0,5 en 1,2 s, `StatusType` `status`) |
| Weergegeven index `D0312A` | `success`, maar **genegeerd**: de status bleef 1 |
| Filtertellers `D0520D` en `D0540E`, één uur lager en terug | Beide richtingen teruggemeld: beide tellers zijn lokaal te schrijven |
| Aanzetten met een stand in één opdracht | Beide toegepast, teruggemeld na 0,26 s |
| Een instelling direct na het antwoord op aanzetten | Toegepast, teruggemeld na 0,22 s |
| Een opdracht met de waarde die al gold | Toch een statusbericht, na 0,03 en 1,25 s |
| Werkelijk toerental bij de terugmelding | Loopt één bericht achter op de stand: medium 3, turbo 18, snelheid 1 tot 4 toerental 1 tot 4, zoals eerder gemeten |

### Meting 15: de verbindingslaag van de integratie, apparaat aan

`tools/session_check.py`, drie minuten.

| Onderwerp | Uitkomst |
|---|---|
| Bereikbaar | Direct |
| Eerste status | Na 1,0 s, 58 sleutels |
| Kinderslot aan en weer uit | Beide bevestigd na 0,24 en 0,29 s, in één poging |
| Daarna | 57 statusberichten in drie minuten, geen gemiste controle, geen weggegooid bericht, geen nieuwe socket |

### Meting 16: CoAP-ping naar de LG-televisie

0 van 10 beantwoord. De televisie antwoordt wel op een info-aanvraag via broadcast (meting 11), maar niet op een ping.

### Meting 17: de integratie in Home Assistant 2026.11.2, apparaat aan

Eerste installatie op 23 november 2026 om 20:36.

| Onderwerp | Uitkomst |
|---|---|
| Toevoegen met het IP-adres | Gelukt; model AC3220/10 en firmware 0.2.3 staan op de apparaatpagina |
| Entiteiten | Alle verwacht aanwezig, met waarden: allergenenindex, luchtvochtigheid, PM2.5, temperatuur, ventilatorsnelheid, filtertellers, licht, helderheid, scène, timer en de schakelaars |
| Bediend vanuit Home Assistant | Licht naar sfeerlicht, Auto Plus aan, Allergie-slaap aan, ventilator uit en weer aan: elke keer gevolgd door de nieuwe toestand |
| Ontbreekt | Het pictogram van de integratie ("logo not available") |

### Eerste statusbericht na een nieuw abonnement, over alle metingen

| Toestand | Tijd tot het eerste bericht |
|---|---|
| Aan (acht metingen) | 0,2 s, 0,8 s, 1,0 s, 1,2 s, 1,4 s, 1,9 s, 1,9 s en 2,1 s |
| Aan, meting 12 | Binnen 3 s geen leesbaar bericht; het apparaat meldde zich daarna elke paar seconden |
| Stand-by (twee metingen) | Geen bericht in 70 s; geen bericht tot het apparaat werd aangezet |

Met het apparaat aan beantwoordt het een abonnement vanaf een nieuwe poort vrijwel altijd binnen ongeveer twee seconden. In stand-by niet.

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
| Met het apparaat aan beantwoordt het een abonnement vanaf een nieuwe poort binnen ongeveer 2 s; een vernieuwing met hetzelfde kenmerk niet (meting 12) en een nieuw kenmerk vanaf dezelfde poort ook niet (meting 13) | Bij het opstarten van Home Assistant komt de status vanzelf binnen als het apparaat aan staat. Daarna levert geen enkele vorm van opnieuw abonneren een verse status; dat hoeft ook niet, want een draaiend apparaat meldt zich binnen seconden en elk bericht bevat de hele status. |
| De info-aanvraag wordt vaak niet beantwoord, zeker bij meerdere tegelijk (7 van 15) | Herkenning vraagt drie tot vijf pogingen, één tegelijk, met een seconde ertussen |
| Het apparaat is vindbaar via broadcast, niet via multicast; een ander apparaat in het netwerk antwoordt ook op poort 5683 | Automatisch zoeken via broadcast met herhalingen. Elk antwoord streng controleren op `device_id`, `product_id` en een bekend model. |
| Drie soorten controles bleven acht uur lang elke keer antwoorden (2880 van 2880), met het apparaat actief | De regel voor "onbereikbaar" (drie missers, drie minuten stilte en een tweede soort controle die ook faalt) heeft ruime marge. Voor uren stilte in stand-by is dit nog niet gemeten |
| De info-aanvraag antwoordt betrouwbaar als ze alleen wordt gesteld, maar traag (tot 1,3 s) | De identiteitscontrole wacht 2 s en vraagt nooit twee keer tegelijk |
| Een actief apparaat stuurt gemiddeld elke 3,3 s een statusbericht, vooral omdat de temperatuur heen en weer springt | Home Assistant mag niet bij elk bericht naar schijf schrijven, en een tijdstip-sensor mag niet elk bericht volgen. De temperatuursensor schrijft ongeveer 25.000 regels per dag in de geschiedenis |
| Elke instelling die de integratie gebruikt, is vanaf het netwerk te bedienen, ook helderheid, scène, display en de filtertellers (meting 14) | Anders dan bij verwante modellen. Het licht wordt geschreven zoals de app dat doet, en er is een knop "Filter gereinigd" |
| De weergegeven index `D0312A` wordt genegeerd | Geen entiteit voor |
| Aanzetten en een stand in één opdracht worden allebei toegepast | De ventilator stuurt ze samen: sneller, en zonder dat het apparaat even in de vorige stand draait |
| Een terugmelding duurde één keer 4,7 s | De deadline van 5 s is krap. Een draaiend apparaat meldt zich intussen meestal toch, en anders stuurt de integratie de opdracht één keer opnieuw; een opdracht met de waarde die al geldt, geeft met het apparaat aan altijd een statusbericht |
| De verbindingslaag van de integratie werkt tegen het echte apparaat (meting 15) | Eerste echte bevestiging buiten de nabootsing |
| De televisie antwoordt niet op een ping | Staat de televisie ooit op het adres van de luchtreiniger, dan gaat de integratie na drie minuten naar "onbereikbaar" in plaats van "bereikbaar" te blijven |


## Functiedekking

Doel: elke functie die het apparaat lokaal prijsgeeft, is beschikbaar in de integratie. Deze tabel houdt bij hoe ver dat is aangetoond op het echte apparaat.

| Functie | Sleutel | Lezen | Bedienen | In de integratie |
|---|---|---|---|---|
| Aan en uit | `D03102` | Gemeten | Gemeten | Ventilator |
| Standen auto, slaap, medium, turbo | `D0310C` | Gemeten | Gemeten | Keuzelijst "Stand", en de ventilator: auto en slaap als stand, medium en turbo als 60% en 100% |
| Handmatige snelheden 1 tot 5 | `D0310C` | Gemeten | Gemeten | Keuzelijst "Stand" en de ventilator |
| Werkelijk toerental | `D0310D` | Gemeten | Alleen-lezen | Sensor "Ventilatorsnelheid" |
| Kinderslot | `D03103` | Gemeten | Gemeten (alleen met het apparaat aan) | Schakelaar |
| Allergie-slaap | `D03115` | Gemeten | Gemeten | Schakelaar |
| Auto+ | `D03180` | Gemeten | Gemeten | Schakelaar |
| Pieptoon | `D03130` | Gemeten | Gemeten | Schakelaar |
| Sensoren in stand-by | `D03134` | Gemeten | Gemeten | Schakelaar |
| Display aan of uit | `D03112` (0 aan, 1 uit) | Gemeten | Gemeten | Schakelaar |
| Lampfunctie van de lichtring | `D03135` | Gemeten | Gemeten | Keuzelijst "Licht" |
| Helderheid van het licht, ook van het sfeerlicht | `D03105` | Gemeten | Gemeten | Keuzelijst "Helderheid licht" |
| Lichtscène | `D03137` | Gemeten | Gemeten | Keuzelijst "Scène sfeerlicht" |
| Timer | `D03110`, `D03211` | Gemeten | Gemeten | Keuzelijst en sensor "Timer loopt af" |
| Fijnstof, allergenenindex, temperatuur, vochtigheid | `D03221`, `D03120`, `D03224`, `D03125` | Gemeten | Alleen-lezen | Sensoren |
| Filter: resterende levensduur | `D0540E`, `D05408` | Gemeten | Gemeten (schrijfbaar) | Sensor, waarschuwing en knop "Nieuw filter geplaatst" (in de app niet gezien) |
| Filter: reinigen | `D0520D`, `D05207` | Gemeten | Gemeten (schrijfbaar) | Sensor, waarschuwing en knop "Filter gereinigd", zoals in de app |
| Weergegeven index op het display | `D0312A` | In de status | Genegeerd | Geen |
| Drempel voor meldingen | `D0312C` | In de status | Gemeten | Geen: meldingen lopen via de cloud |
| Storing of foutcode | `D03240` | In de status; nog geen storing gezien | Alleen-lezen | Waarschuwing en sensor |
| Wifi-signaal, firmwareversies, looptijd | `rssi`, `D01S12`, `WifiVersion`, `Runtime` | Gemeten | Alleen-lezen | Sensor en apparaatgegevens |

Niet lokaal beschikbaar: het weekschema en de instellingen voor meldingen (gemeten: wijzigen in de app verandert lokaal niets), en voor zover bekend ook de luchtkwaliteit buiten, grafieken en firmware-updates. Die lopen via de app en de cloud. Home Assistant heeft daar eigen middelen voor (automatiseringen, geschiedenis, een weerdienst).

Sleutels zonder bekende betekenis: `D03106`, `D0311F`, `D03136`, `D0313B`, `D03182`, `D03R81`, `D05102` en de `D011xx`-reeks. Behalve `D0311F` veranderde geen ervan tijdens de rondgang door de app; het zijn dus vermoedelijk geen instellingen die de gebruiker bedient.

## Nog te meten

| Vraag | Opdracht |
|---|---|
| Met welke servers praat de luchtreiniger? | DNS-logboek van AdGuard Home, gefilterd op 10.10.10.113 |
| Blijft hij lokaal goed werken zonder internet: wat meldt `ConnectType`, herstart de wifi-module zich, blijft de bediening werken, en blijft de app thuis werken? | Internet blokkeren in de router, daarna een dag de sensoren "Cloudverbinding" en "Laatst opgestart" en de diagnostiek bekijken |
| Blijft het apparaat meetwaarden sturen als het uit staat met "sensoren in stand-by" aan? De integratie toont ze dan; zonder deze schakelaar zijn ze "onbekend". | Zet "sensoren in stand-by" aan, zet het apparaat uit, en draai `watch --alles` een kwartier |
| Welke controle blijft antwoorden gedurende uren stilte in stand-by? | `liveness` in stand-by, met "sensoren in stand-by" uit |
| Waarom waren zes berichten in de nacht niet te lezen? | `python -m pureprotect_probe.inspect_run metingen/20261122-214359-liveness` opnieuw; de terugblik noemt nu de reden |
| Bedient het apparaat abonnees vanaf verschillende adressen tegelijk? | `observe` op twee computers tegelijk |
| Gedrag na een stroomonderbreking | `power-cycle` |
| Storen de app en een lokale client elkaar? | Tijdens de rondgang niet; `app` test daarnaast of onze controles de app hinderen |
| De betekenis van `D0311F` | Werd in meting 15 even 0 en weer 1, zonder dat er iets werd bediend |

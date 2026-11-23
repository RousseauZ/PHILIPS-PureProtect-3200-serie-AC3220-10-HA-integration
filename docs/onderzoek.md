# Onderzoek: Philips PureProtect 3200 (AC3220/10) en Home Assistant

Datum: 22 november 2026.

Dit rapport beantwoordt twee vragen: hoe communiceert de AC3220/10, en hoe bouwen we er een betrouwbare Home Assistant-integratie voor. Het is gebaseerd op de broncode van ruim twintig bestaande projecten, issue-trackers, fora, de officiële handleiding en productgegevens van Philips.

**Er is niets op een echte AC3220 getest.** Alles over het gedrag van jouw apparaat op de huidige firmware is afgeleid van verwante modellen. Hoofdstuk 7 beschrijft hoe we dat gat dichten; dat hoort vóór het bouwen van de integratie te komen.

Bewijsniveaus in dit rapport:

| Label | Betekenis |
|---|---|
| **[code]** | Zelf nagekeken in de broncode van het genoemde project. |
| **[gemeten: model]** | Door een derde gemeten op het genoemde model, teruggelezen in de bron. |
| **[aanname]** | Afgeleid van verwante modellen of documentatie; niet aangetoond op een AC3220. |

Het rapport is na het schrijven door drie onafhankelijke controleurs nagelopen; hun correcties zijn verwerkt (bijlage B). De onderliggende notities (Engels, met bronverwijzingen per bewering) staan in [`docs/research/`](research/README.md).

---

## 1. Samenvatting

**Hoe het apparaat communiceert.** De AC3220 is een CoAP-server op UDP-poort 5683 in je eigen netwerk. Er is geen koppeling en geen wachtwoord. De inhoud is versleuteld met een vaste, publiek bekende sleutelafleiding; dat is verhulling en geen beveiliging. Het apparaat praat daarnaast met de Philips-cloud, en ook de Air+ app gebruikt op het thuisnetwerk dit lokale protocol.

**Waarom de bestaande integraties haperen.** Op andere modellen met de recente wifi-firmware (`AWS_Philips_AIR_Combo@86`) is gemeten dat het apparaat de status alleen meldt wanneer er een waarde verandert. In stand-by is het stil, en een abonnementsaanvraag wordt pas bij de volgende verandering beantwoord. Voor de AC3220 is dat waarschijnlijk maar niet aangetoond. Beide HACS-integraties zien die stilte als een verbroken verbinding:

- `kongo09/philips-airpurifier-coap` breekt na 180 seconden stilte de hele verbinding af en bouwt haar opnieuw op. Verzoeken hebben geen time-out, dus één verloren pakketje kan een commando laten hangen. Na een herstart toont de integratie een oude, opgeslagen status als actueel.
- `tinkerologie/ha-philips-airpurifier` vernieuwt het statusabonnement elke 60 seconden en gooit het werkende abonnement weg als het apparaat niet binnen 10 seconden antwoordt. Op één AC2210 leverde dat 118 storingen per dag op, tegen 14 zonder die vernieuwing.

Daarnaast bevatten beide integraties voor de AC3220 een verkeerde sleutel (de keuzelijst "voorkeursindex" werkt nooit) en missen ze meerdere functies.

**Advies.** Bouw een nieuwe, kleine integratie die alleen deze generatie luchtreinigers bedient, met een eigen protocollaag:

1. Bereikbaarheid bepalen met een aparte, lichte controle en nooit uit stilte op de statusstroom.
2. Eén socket en één abonnement per apparaat. Het abonnement periodiek vernieuwen zonder een antwoord te eisen, en nooit iets afbreken omdat het stil is.
3. Elk verzoek een time-out en een beperkt aantal herhalingen geven.
4. Commando's bevestigen aan de hand van wat het apparaat terugmeldt, met een harde tijdslimiet.
5. De laatst bekende status en sleutelset bewaren, zodat na een herstart de entiteiten er direct zijn.
6. Geen cloud in het kritieke pad.

**Eerst meten.** Wat jouw apparaat precies doet, bepaalt een handvol ontwerpkeuzes. Een snelle controle van een halfuur met bestaande hulpmiddelen geeft de firmware, de sleutelset en de werkende schrijfopdrachten. De overige vragen (welke bereikbaarheidscontrole, hoe het abonnement te vernieuwen) vragen een eigen meetprogramma. Dat programma is de eerste bouwstap en meteen de basis van de protocollaag.

---

## 2. Het apparaat

### 2.1 Hardware en firmware

| Onderdeel | Bevinding | Bewijs |
|---|---|---|
| Wifi-module | Zeer waarschijnlijk MXCHIP EMC6069-P (2,4 GHz wifi 6 en Bluetooth LE 5.2) | Aangetoond door demontage van de AC0951 en CX3550; de radiospecificatie in de AC3220-handleiding komt overeen. Niemand heeft een AC3220 opengemaakt. **[aanname]** |
| Interne naam | `Unicorn` (veld `D01S04`). Dat is een platformnaam die ook de AC4221 en AC0951 dragen, dus geen modelherkenning. | Statusdumps |
| Twee firmwares | Apparaatfirmware (veld `D01S12`, bijvoorbeeld `0.2.3`) en wifi-firmware (veld `WifiVersion`, bijvoorbeeld `AWS_Philips_AIR_Combo@86`) | Statusdumps |
| Bekende versies AC3220 | `0.1.9` met `@3.0` (november 2024); `0.2.3` met `@86` (Australisch exemplaar, april 2026; een Europees exemplaar in de cloud, oktober 2026) | kongo09 issue #181, HA-forum, cloudproject NikGro |
| Koppelen | Eenmalig via de Air+ app, met Bluetooth, 2,4 GHz wifi en internet | Handleiding |
| Firmware-update | Volgens de handleiding "via de Air+ app". Of updates ook ongevraagd installeren, is niet vastgesteld. | Handleiding |

De wifi-module leest de hoofdprocessor ongeveer één keer per seconde uit en publiceert alleen bij een verandering. Daar komt het gedrag "meldt alleen bij verandering" vandaan.

### 2.2 Wat het apparaat kan

| Functie | Op het apparaat | Alleen in de app |
|---|---|---|
| Standen | Auto, Medium, Turbo, Slaap | Handmatige snelheden 1 tot 5, Allergie-slaap, Auto+ |
| Sensoren | Fijnstof (PM2.5), lichtsensor | |
| Verlichting | Display, lichtring met een knop voor de lampfunctie | Lichtscènes en helderheid |
| Overig | Kinderslot | Timer, weekschema, drempel voor meldingen |

Er is geen gassensor. De officiële specificatie van de AC3220/10 noemt geen temperatuur- en vochtsensor, maar de statusdump van een echte AC3220/10 bevat wel beide waarden (`D03224`, `D03125`). Behandel ze als aanwezig en controleer op je eigen apparaat of ze plausibel zijn.

---

## 3. Hoe het apparaat communiceert

### 3.1 Lokaal: CoAP op UDP-poort 5683

CoAP is een licht verzoek-antwoordprotocol over UDP, vergelijkbaar met HTTP. Het apparaat biedt vier adressen. **[code]** in vier onafhankelijke implementaties.

| Adres | Methode | Wat het doet | Versleuteld |
|---|---|---|---|
| `/sys/dev/info` | GET | Geeft model, naam en apparaat-id als leesbare JSON | Nee |
| `/sys/dev/sync` | POST | Handshake: de client stuurt 8 willekeurige hextekens, het apparaat antwoordt met een teller van 8 hextekens | Nee |
| `/sys/dev/status` | GET met Observe | Abonnement: het apparaat stuurt de volledige toestand, en daarna opnieuw bij elke verandering | Alleen het antwoord |
| `/sys/dev/control` | POST | Schrijfopdracht; antwoord is `{"status":"success"}` of `{"status":"failed"}` | Alleen het verzoek |

**Versleuteling.** AES-128-CBC. Sleutel en beginvector zijn de twee helften van `MD5("JiangPan" + teller)`. De teller staat onversleuteld vooraan in elk bericht, gevolgd door de versleutelde tekst en een SHA-256-controlegetal zonder geheim. Een onderzoeksagent heeft dit los van de bestaande libraries nagebouwd en daarmee twee vastgelegde apparaatberichten correct ontcijferd. Iedereen in je netwerk kan dus meelezen en commando's sturen; de integratie hoeft daardoor ook geen sleutel of account te beheren.

**Teller.** Vóór elke schrijfopdracht verhoogt de client de teller met één. Statusberichten ontcijferen staat los van de teller, want elk bericht draagt zijn eigen teller. Een nieuwe sync verstoort een lopend abonnement daarom niet. **[gemeten: AC2220/10]**

**Statusberichten.** Elk bericht is een volledige momentopname, geen verschil. Het bericht is ongeveer 1,9 tot 2,1 kB en past niet in één netwerkpakket; het komt vermoedelijk gefragmenteerd aan. **[aanname]** Firewalls en VLAN-regels tussen Home Assistant en het apparaat moeten IP-fragmenten doorlaten.

**Schrijfopdrachten.** De inhoud is `{"state":{"desired":{"CommandType":"app","DeviceId":"","EnduserId":"", <sleutel>: <waarde>}}}`. Waarden moeten als geheel getal worden gestuurd. Als tekst gestuurde waarden anders dan "0" worden genegeerd, terwijl het apparaat soms toch "success" antwoordt; de tekst "0" (uitzetten) werkte wel. **[gemeten: CX3120]**

### 3.2 Gedrag van de firmware

Dit is het deel dat de betrouwbaarheid bepaalt. De tabel geeft per eigenschap het sterkste bewijs en wat dat voor de AC3220 betekent.

| Eigenschap | Sterkste bewijs | Voor de AC3220 |
|---|---|---|
| Status alleen bij verandering, geen hartslag | **[gemeten: AMF870/15]** met netwerkopname over vier dagen: stiltes van 12 minuten tot 2 uur, ongeveer 18 keer per dag. **[gemeten: AC2220/10, firmware 0.2.3 met @86]**: stil tot 14 minuten op een lopend abonnement. | **[aanname]**, waarschijnlijk |
| Een abonnementsaanvraag wordt pas bij de volgende verandering beantwoord; een statusaanvraag zonder abonnement helemaal niet | **[gemeten: AC2220/10]**: 6,5 tot 64 seconden in vijf metingen, één keer 9 minuten na een stroomonderbreking. **[gemeten: AC2210]**: 47% van 414 vernieuwingen onbeantwoord binnen 10 seconden. | **[aanname]**, waarschijnlijk |
| Sync blijft antwoorden tijdens stilte | **[gemeten: AC2220/10]** ongeveer 100 ms; **[gemeten: CX7550/01]** 26 van 26 controles in 4,6 uur met één statusbericht. Op de AMF870 bleef sync een enkele keer een paar minuten onbeantwoord. | **[aanname]** |
| Schrijven werkt tijdens stilte | **[gemeten: AMF870/15]** 4 van 4 binnen 109 tot 211 ms | **[aanname]** |
| Een schrijfopdracht met de waarde die al gold geeft geen statusbericht | **[gemeten: AMF870/15]**: bevestigd, maar geen bericht binnen 45 seconden. Een gewijzigde waarde gaf na 0,3 seconde een volledig bericht. | **[aanname]** |
| Na een schrijfopdracht kan de stroom haperen | **[gemeten: AMF870/15]**: bij 4 van ongeveer 40 commando's kwamen daarna 0 of 1 berichten; de volgende verandering kwam pas 2 tot 4 minuten later, na een herverbinding. | Onbekend |
| Abonnement verloopt na ongeveer 150 seconden zonder vernieuwing | **[gemeten: AC4220/12]**, twee sessies op één apparaat; de oorzaak is volgens het issue zelf "niet bevestigd" | Onbekend |
| Eén abonnee per bron-IP, de nieuwste wint | **[gemeten: AMF870/15]**. Op een AC2220 werkten twee clients naast elkaar. | Onbekend |
| Beschadigde berichten uit het apparaat zelf | **[gemeten: AMF870/15]**: één op de 1.800 tot 18.000 statusberichten bevat nul-bytes bij een geldig controlegetal; ook gezien op een AC0850. Ongeveer één op de 700 tot 2.000 sync-antwoorden bevat een met nul-bytes aangevulde teller, waarna alle commando's falen tot de volgende sync. | **[aanname]** |
| Apparaat negeert een deel van de broadcast-ARP-verzoeken | **[gemeten: AMF870/15 op één UniFi-netwerk]**: 61% beantwoord. Van 32 verloren sync-verzoeken hadden er 31 de Home Assistant-computer nooit verlaten. | Onbekend |
| Berichtnummers van het apparaat zijn onbetrouwbaar | Meerdere oudere modellen stuurden steeds hetzelfde nummer (melding uit 2021). De AC2220/10 toonde oplopende volgnummers. | Onbekend |

Eén melding uit dezelfde serie past niet in dit beeld: een AC3221-eigenaar schreef dat het apparaat "bereikbaar kan zijn en momentopnamen van de status teruggeeft, terwijl een nieuw abonnement stil blijft". Het gedrag verschilt dus per model en firmware, en moet op jouw apparaat worden gemeten.

Er is geen aanwijzing gevonden dat een firmware-update lokale toegang heeft verwijderd op de 2200-, 3200- of 4200-serie. De AC0650 en AC0651 zijn een ander hardwareplatform met een ESP32-module en zonder lokaal protocol. Voor de AC1715 is niet opgehelderd of hardware of firmware de oorzaak is, en bij Philips-airfryers is een overgang naar alleen-cloud via een update wel gedocumenteerd. Uitsluiten kan dus niemand het.

### 3.3 Ontdekken in het netwerk

- Een verwant model op `@86` (AC0950/10) beantwoordt een onversleuteld `GET /sys/dev/info` binnen ongeveer 200 ms wanneer het naar het broadcast-adres en/of naar multicast-adres 224.0.1.187 wordt gestuurd. **[gemeten: AC0950/10]**
- Het antwoord bevat `device_id`, en dat is dezelfde waarde als `DeviceId` in de versleutelde status. Een apparaat is dus te vinden en eenduidig te herkennen zonder sync en zonder abonnement. Op een AC32xx is dit niet aangetoond.
- Het veld `swversion` in dat antwoord is op deze generatie altijd `0.0.0`. Firmwareversies komen alleen uit de status.
- MXCHIP heeft acht MAC-voorvoegsels: `B0F893`, `047863`, `849DC2`, `80A036`, `6879C4`, `88A68D`, `D0BAE4`, `C89346`. De twee bekende `@86`-apparaten zitten in `6879C4`. De tinkerologie-integratie herkent dat voorvoegsel niet. Van geen enkele AC3210, AC3220 of AC3221 is een MAC-adres of DHCP-hostnaam gepubliceerd.

### 3.4 Cloud en app

De Air+ app heeft twee verschillende cloud-backends.

| | Backend A (MxChip/FogCloud) | Backend B (Versuni DaConnect) |
|---|---|---|
| Apparaten | Modellen met MXCHIP-module en lokaal CoAP, waaronder de AC3220 | AC0650, AC0651, AC1715, airfryers |
| Gegevens | Dezelfde sleutels en waarden als lokaal | Ander formaat |
| Aanmelden | E-mailcode, daarna een token dat is afgeleid van een geheim uit de app | E-mailcode en OAuth |

Een bestaand cloudproject (NikGro/philips-air-plus-homeassistant) meldt een Europese AC3220/10 op backend A met firmware `0.2.3` en dezelfde sleutels als lokaal. Dat project noemt zichzelf experimenteel en heeft besturing niet gevalideerd.

De cloud geeft dezelfde sleutels en waarden als lokaal en meldt uit zichzelf ook alleen bij verandering. Eén ding kan de cloud wel dat lokaal ontbreekt: een opvraging levert binnen 1 tot 2 seconden een verse, volledige status (**[gemeten: AC3737]**, niet aangetoond op een AC3220). Daartegenover staat dat aanmelden een geheim vereist dat uit de app moet worden gehaald. De cloud hoort daarom niet in het kritieke pad, maar blijft een mogelijke aanvulling voor later.

De app zelf gebruikt op het thuisnetwerk het lokale protocol: op een AC4221/11 met `@86` is verkeer van telefoon naar luchtreiniger op poort 5683 vastgelegd, en de app bleef werken met het internet van het apparaat geblokkeerd. **[gemeten: AC4221/11]** Er zijn losse meldingen uit 2022 en 2026 dat een niet-reagerend apparaat weer tot leven komt zodra de app wordt geopend; niemand heeft dat op pakketniveau onderzocht.

Officieel ondersteunt Philips alleen Alexa en Google voor spraakbediening. Er is geen Matter, HomeKit, SmartThings of openbare API gevonden.

---

## 4. Waarom de bestaande integraties onbetrouwbaar zijn

### 4.1 kongo09/philips-airpurifier-coap

Laatste wijziging op 26 juli 2026; de verbeteringen voor betrouwbaarheid staan als niet-samengevoegde pull requests open of zijn gesloten. Alle punten hieronder: **[code]**.

| Probleem | Gevolg |
|---|---|
| Geen time-out op enig verzoek; verzoeken worden één keer en zonder ontvangstbevestiging verstuurd | Een commando kan onbeperkt hangen (gemeld: 1 uur 46 minuten). Een herverbinding hangt tot de bewaking 180 seconden later opnieuw afgaat; meerdere verloren pakketjes op rij tellen op. |
| Entiteiten zijn altijd "beschikbaar" en starten met de status die bij het toevoegen is opgeslagen | Na een herstart zie je mogelijk maanden oude waarden als actueel |
| Enige herstel: na 180 seconden stilte de hele client afbreken en opnieuw opbouwen | Op stille firmware gebeurt dat de hele dag door |
| De ontvangstlus heeft geen foutafhandeling | Eén beschadigd bericht stopt alle updates tot de volgende herverbinding |
| Het resultaat van commando's wordt niet gecontroleerd | De gevraagde waarde wordt getoond, ook als het apparaat haar negeerde |
| De DHCP-ontdekking opent een tweede sessie naar een al ingesteld apparaat | Kan de lopende sessie haar meldingen afnemen |
| Dubbel afsluiten van de verbinding | De integratie blijft hangen in "afsluiten mislukt" tot Home Assistant herstart; gemeld op een AC3210/12 (issue #397, open) |

### 4.2 tinkerologie/ha-philips-airpurifier

Zeer actief onderhouden door één persoon, niet in de standaardcatalogus, geen migratiepad vanaf kongo09. Sterke punten: time-outs, stapsgewijs wachten bij herverbinden, goede diagnostiek, en herkenning op MAC-adres vóór enig netwerkverkeer.

| Probleem | Gevolg | Bewijs |
|---|---|---|
| Abonnement wordt elke 60 seconden vernieuwd; blijft het antwoord 10 seconden uit, dan vervalt het werkende abonnement | Reeksen van korte storingen op stille firmware | **[code]** |
| Bij herverbinden wordt eerst de client gesloten en is een statusantwoord binnen 30 seconden vereist | Tijdens een storing falen ook commando's | **[code]** |
| Bij een herhaald commando wordt het oude versleutelde bericht opnieuw verstuurd | Herhalingen na een nieuwe sync kunnen niet slagen | **[code]** |
| De truc om een statusbericht af te dwingen bestaat niet voor de AC3210/AC3220/AC3221 | Geen oplossing voor de stilte op dit model | **[code]** |
| De acties `set_child_lock` en `filter_reset` kennen alleen oudere sleutels | Doen niets op een AC3220 | **[code]** |

Metingen van gebruikers met verwante modellen op `@86`:

| Model | Vergelijking | Uitkomst |
|---|---|---|
| Eén AC2210 | tinkerologie 2026.10.3 (met vernieuwing) tegen 2026.10.2 (zonder), elk 24 uur | 118 tegen 14 storingen; 10 uur 22 minuten tegen 3 uur 21 minuten onbeschikbaar |
| Eén AC2220/10 | tinkerologie 2026.11.1 gedurende 30 uur tegen kongo09 v0.37 gedurende 8,5 dag | 56 tegen 5 periodes onbeschikbaar |

Het weglaten van de vernieuwing is dus niet genoeg: ook zonder was het apparaat ruim drie uur per dag onbeschikbaar. De stiltebewaking zelf is de andere helft van het probleem. Het lage getal bij kongo09 zegt weinig, omdat die integratie entiteiten vrijwel nooit als onbeschikbaar markeert en in plaats daarvan oude waarden toont.

### 4.3 Fouten voor de AC3220 in beide integraties

| Fout | kongo09 | tinkerologie |
|---|---|---|
| Keuzelijst "voorkeursindex" gebruikt sleutel `D03-42` van een oudere generatie; het apparaat meldt `D0312A` | Ja, permanent "onbekend" | Ja |
| Allergie-slaap (`D03115`) ontbreekt | Ja | Ja |
| Sensoren in stand-by (`D03134`) ontbreken | Ja | Ja |
| Displayhelderheid als dimbare lamp, terwijl het vier vaste standen zijn | Ja | Ja |
| Ventilatorpercentage is leeg in een voorkeuzestand | Ja | Ja |
| Filterpercentage rondt af naar 0% terwijl er nog uren over zijn | Ja | Ja |
| Looptijd als attribuut van de ventilator, wat bij elk bericht een regel in de database schrijft | Ja | Nee |

### 4.4 Voorlopig advies zolang er geen nieuwe integratie is

- Gebruik één integratie tegelijk, en draai geen losse testprogramma's vanaf de Home Assistant-computer terwijl een integratie actief is.
- Op één AC2220/10 gaf kongo09 v0.37 de minste zichtbare storingen, met als prijs dat waarden verouderd kunnen zijn en dat de integratie bij een herstart kan vastlopen (issue #397). Bij tinkerologie is versie 2026.10.2 de laatste zonder de vernieuwing.
- Geef het apparaat een vast IP-adres via een DHCP-reservering.
- Zet het op een 2,4 GHz-netwerk dat Home Assistant rechtstreeks kan bereiken: geen gastnetwerk en geen client-isolatie.

---

## 5. Wat andere platforms doen

De broncode van zeven implementaties buiten Python is gelezen.

| Implementatie | Bereikbaarheidscontrole | Abonnement vernieuwen | Opmerking |
|---|---|---|---|
| openHAB (officiële binding, oktober 2026) | Sync na minstens 30 seconden stilte; offline na minstens 60 seconden | Alleen na een gemiste controle | Doet vóór elk commando een sync onder één slot. Besturing van deze generatie is nog niet op hardware bevestigd. |
| ioBroker 2.4.1 | Sync na 300 seconden stilte | Opnieuw abonneren na elke geslaagde controle | Herverbinden met 30, 60 en 120 seconden wachten |
| ESP32-logger (chayuto) op een AC2220/10 met `@86` | Sync per stille periode | Dezelfde aanvraag opnieuw na 75 seconden stilte, zonder antwoord te verwachten | Beste meting op een verwant model: 14,8 uur, 1.599 statusberichten |
| Homey-app | Geen | Beëindigt elk abonnement na 600 seconden | Eén beschadigd bericht beëindigt de sessie. AC3220-eigenaren melden instabiliteit. Op een AC3221/13 werken aan/uit en snelheid sinds een testversie van augustus 2026; één gebruiker meldt dat ook de kleur van de lichtring te wijzigen is. |

Twee dingen komen overal terug waar het stabiel werd: stilte wordt niet als fout behandeld, en bereikbaarheid wordt gemeten met de sync-handshake. Over het vernieuwen van het abonnement zijn de implementaties het oneens, en geen ervan is op een AC3220 getest.

---

## 6. Advies: zo bouwen we het

### 6.1 Strategie

**Een nieuwe, gerichte integratie, met een eigen protocollaag.** De afweging:

| Optie | Voor | Tegen |
|---|---|---|
| Een bestaande integratie gebruiken | Geen werk | Beide passen structureel niet bij deze firmware |
| Bijdragen aan tinkerologie | Onderhouder verwerkt kleine verbeteringen snel | De echte oplossing raakt de kern van zijn ontwerp en van zijn library |
| Tinkerologie afsplitsen | Volledige controle | 7.000 regels integratie en 64 modellen meedragen voor één apparaat; het domein moet toch veranderen |
| **Nieuw en gericht** | Eén generatie; het juiste bereikbaarheidsmodel vanaf het begin | Eigen protocollaag schrijven en testen |

De kleine, goedkope verbeteringen (de sleutel `D0312A`, de acties voor deze generatie, opnieuw versleutelen bij een herhaling) zijn het waard om daarnaast bij de bestaande projecten aan te bieden.

### 6.2 Opbouw in lagen

```
Home Assistant-platforms     fan, sensor, binary_sensor, switch, select, button, diagnostics
        │
Coordinator                  geeft status door aan entiteiten, voert commando's uit
        │
Sessielaag                   toestandsmachine: abonnement, bereikbaarheid, herstel, bevestiging
        │
Protocollaag                 CoAP-berichten coderen en decoderen, versleuteling, één UDP-socket
```

De protocol- en sessielaag vormen samen een losstaand pakket dat niets uit Home Assistant importeert. Dat maakt het los testbaar tegen een nagebootst apparaat en later publiceerbaar als eigen library.

**De sessielaag is de enige eigenaar van bereikbaarheid.** De coordinator krijgt geen eigen interval; hij geeft binnenkomende status door en leidt de beschikbaarheid van entiteiten af uit de toestand van de sessie. Een bewaking in het interval van de coordinator zou bij de eerste misser alles onbeschikbaar maken, en stopt wanneer een gebruiker "polling uitschakelen" kiest.

**Eigen CoAP-code in plaats van de library aiocoap.** Redenen:

- aiocoap heeft geen time-out voor verzoeken zonder ontvangstbevestiging. **[code]**
- aiocoap kan een abonnement niet met hetzelfde kenmerk vernieuwen en meldt het apparaat niet af.
- Drie Philips-integraties moesten aiocoap programmabreed aanpassen, en Home Assistant levert het alleen indirect mee.
- Een mogelijke valkuil, op geen enkel apparaat waargenomen: aiocoap verwerpt tot 128 seconden lang statusberichten waarvan het volgnummer niet oploopt.

Het benodigde deel van CoAP is klein: berichtkop, kenmerk, de opties Uri-Path, Observe en Max-Age, GET en POST, en het bevestigen van binnenkomende berichten. Voor AES is het pakket `cryptography` genoeg, dat Home Assistant zelf als vereiste heeft. De integratie heeft dan geen externe afhankelijkheden.

### 6.3 Sessie: toestanden en regels

| Toestand | Entiteiten in Home Assistant | Wat er loopt |
|---|---|---|
| OFFLINE | Onbeschikbaar | Pogingen met oplopende wachttijd |
| BEREIKBAAR | Beschikbaar met de laatst bekende waarden; onbekend als er nooit een status is ontvangen | Abonnement, bereikbaarheidscontrole |
| ACTUEEL | Beschikbaar; laatste waarden blijven staan, hoe oud ook | Abonnement, bereikbaarheidscontrole |
| TWIJFEL | Ongewijzigd | Herhaalde controles |

**Overgangen**

| Gebeurtenis | Gevolg |
|---|---|
| Geldig statusbericht, in welke toestand ook | Naar ACTUEEL |
| Elk geldig datagram van het apparaatadres (statusbericht, sync-antwoord, antwoord op een commando, ook een bericht dat de inhoudscontrole niet doorstaat) | Telt als contact; teller van gemiste controles terug naar nul |
| 60 seconden zonder contact | Bereikbaarheidscontrole sturen, deadline 3 seconden |
| Controle gemist | Naar TWIJFEL; elke 10 seconden opnieuw |
| Minstens 3 missers op rij, én minstens 180 seconden sinds het laatste contact, én een tweede, andersoortige controle faalt ook | Naar OFFLINE |
| Contact vanuit OFFLINE of TWIJFEL | Naar BEREIKBAAR of ACTUEEL met behoud van de bewaarde waarden; direct opnieuw abonneren en de identiteit controleren |

De drempel van 180 seconden volgt uit het bewijs dat sync op een gezond apparaat een enkele keer minuten onbeantwoord blijft. Onterecht OFFLINE gaan is duur: Home Assistant slaat acties op onbeschikbare entiteiten stilzwijgend over.

**Abonnement**

| Regel | Reden |
|---|---|
| De abonnementsaanvraag gaat bij het verbinden altijd uit, ook als sync niet antwoordt | Status lezen heeft geen sync nodig |
| Vernieuwen is verplicht en nooit uit: elke 65 tot 75 seconden, zonder antwoord te eisen | Het is het enige herstel na een korte herstart van het apparaat, verdringing door een andere client, of een verlopen abonnement |
| Extra vernieuwen na: de eerste geslaagde controle na een misser, een commando dat geaccepteerd maar niet teruggemeld wordt, een beschadigd bericht, een lagere looptijd dan voorheen | Aanwijzingen dat het abonnement weg is of een wijziging is gemist |
| Oplopende aanpak als vernieuwen niet helpt: zelfde kenmerk, dan een nieuw kenmerk (het oude blijft geldig tot het nieuwe levert), dan sync plus een nieuw abonnement | Welke vorm op de AC3220 werkt, is onbekend; de werkende trede komt in de diagnostiek |
| Bij afsluiten het abonnement afmelden; op berichten met een onbekend kenmerk antwoorden met een reset | Voorkomt dat het apparaat oude abonnees blijft bedienen |

**Overige regels**

| Onderdeel | Regel |
|---|---|
| Verzoeken | Zonder ontvangstbevestiging, met een eigen deadline per verzoek; binnenkomende bevestigbare berichten wel bevestigen |
| Bereikbaarheidscontrole | Startwaarde: sync. De meting in hoofdstuk 7 vergelijkt sync, de info-aanvraag en een lege CoAP-ping tijdens stilte; antwoordt de info-aanvraag betrouwbaar, dan krijgt die de voorkeur omdat ze de teller niet raakt. |
| Sync-antwoord | Moet precies 8 hextekens zijn. Een misvormd antwoord telt als contact, maar als mislukte poging voor een commando. |
| Beschadigd statusbericht | Overslaan, tellen en als gemiste wijziging behandelen: opnieuw abonneren |
| Volgorde | Nooit op berichtnummer filteren. Een bericht met een iets lagere looptijd dan het vorige is oud en vervalt; een looptijd die terugvalt naar een kleine waarde is een herstart. |
| Identiteit | `DeviceId` in elk statusbericht vergelijken met het ingestelde apparaat; bij een afwijking het bericht negeren en een reparatiemelding tonen |
| Socket | Eén per apparaat. Alleen vervangen bij een fout van het besturingssysteem of bij het ingaan van OFFLINE. |
| Wachttijd bij OFFLINE | 10, 10, 10, 30, 60 seconden, daarna elke 60 seconden; na 5 minuten ook zoeken naar het apparaat-id op een ander adres |
| Logboek | Eén regel bij verlies, één bij herstel |

De kern: **stilte is nooit een fout, en er wordt niets afgebroken omdat het stil is.** De getallen zijn keuzes binnen de bandbreedte van bestaande implementaties, geen gemeten optimum.

**Na een herstart van Home Assistant.** De sessielaag bewaart per apparaat de waargenomen sleutelset, de firmwareversies en het laatste volledige statusbericht met het tijdstip van ontvangst. Bij het opstarten worden de entiteiten daaruit aangemaakt en gevuld, en het eerste echte bericht vervangt die waarden. Zonder deze stap zouden er na een herstart geen entiteiten bestaan tot het apparaat iets meldt, en dat kan in stand-by uren duren. Het verschil met kongo09 is dat hier de laatst ontvangen status wordt bewaard en niet die van het moment van toevoegen, en dat een aparte entiteit "Laatste statusbericht" de ouderdom zichtbaar maakt.

**Restrisico's die het ontwerp niet wegneemt**

| Risico | Gevolg | Beperking |
|---|---|---|
| Het laatste bericht vóór een stille periode gaat verloren | Home Assistant toont een verouderde toestand tot de volgende wijziging | Verplichte vernieuwing; de entiteit "Laatste statusbericht". Als de meting uitwijst dat een vernieuwing direct wordt beantwoord, werkt die als periodieke opvraging. |
| Het netwerk laat kleine pakketten door maar geen fragmenten | Bereikbaar, maar nooit een status | Reparatiemelding na drie geaccepteerde commando's zonder enig statusbericht; optionele stap bij het instellen |

### 6.4 Commando's

1. **Uitwisseling onder één slot:** sync, daarna de schrijfopdracht met teller plus één. Per poging 1,5 seconde voor sync en 2 seconden voor het antwoord; hooguit drie pogingen, elk met een nieuwe sync en opnieuw versleuteld. Dit is de werkwijze van openHAB en voorkomt verouderde tellers.
2. **Harde limiet van 10 seconden** per actie, inclusief wachten op het slot. Het slot komt vrij zodra het antwoord binnen is.
3. **Bevestiging per sleutel, met deadline.** Gold de gevraagde waarde al, dan is de actie direct geslaagd, want het apparaat stuurt dan geen bericht. Anders: berichten met een afwijkende waarde 2 seconden negeren (ze kunnen van vóór de wijziging zijn), en het eerste bericht met een geaccepteerde waarde telt als bevestiging.
4. **Geen bevestiging binnen 5 seconden:** opnieuw abonneren, 3 seconden wachten, één keer opnieuw sturen, en daarna een foutmelding "geaccepteerd maar niet bevestigd" in Home Assistant.
5. **Geaccepteerde teruggelezen waarden per sleutel.** Het apparaat normaliseert sommige waarden: de pieptoon leest als 100 terug na het schrijven van 1, snelheid 5 meldt toerental 18, en de stand leest -16 als het apparaat uit staat.
6. **Samenvoegen.** Samengestelde acties, zoals aanzetten met een stand, gaan in één bericht. Commando's die vrijwel tegelijk binnenkomen worden samengevoegd; per sleutel wint de laatste waarde.
7. Commando's zijn toegestaan in TWIJFEL en in BEREIKBAAR. Een geslaagde uitwisseling telt als contact.

### 6.5 Ontdekking en instellen

- **Herkenning** via het onversleutelde `GET /sys/dev/info`. De `device_id` daaruit is de unieke sleutel van het apparaat in Home Assistant. Alleen een antwoord met `device_id`, `product_id` en een ondersteund model wordt geaccepteerd; MXCHIP-voorvoegsels worden ook door andere merken gebruikt.
- **Terugval** als de AC3220 de info-aanvraag niet beantwoordt: het apparaat-id uit het eerste statusbericht nemen. Het instellen vraagt dan om een druk op een knop van de luchtreiniger om een bericht uit te lokken.
- **Drie routes naar dezelfde instelstroom:** DHCP-herkenning op alle acht MXCHIP-voorvoegsels, een actieve zoektocht, en handmatige invoer van het IP-adres. De actieve zoektocht stuurt de info-aanvraag per netwerkadapter naar het broadcast-adres en naar 224.0.1.187, drie tot vijf keer met een seconde ertussen. Dat werkt niet als Home Assistant in een afgeschermd containernetwerk draait; handmatige invoer blijft altijd mogelijk.
- **Nooit een tweede sessie** openen naar een apparaat dat al is ingesteld. De info-aanvraag raakt abonnement en teller niet en is dus veilig.
- **Instellen slaagt** zodra het apparaat is herkend. Optioneel volgt een stap "druk op een knop op de luchtreiniger" die tot 60 seconden op een eerste statusbericht wacht; lukt dat niet, dan start de integratie met een vaste sleuteltabel voor de 3200-serie.
- **Opstarten van Home Assistant** wacht nooit op het apparaat: de integratie laadt, en de sessielaag blijft zelf proberen.
- **Adreswijziging:** bij een DHCP-melding alleen het adres bijwerken. Het MAC-adres wordt na een geslaagde uitwisseling uit de netwerktabel geleerd, zodat dit ook werkt voor handmatig toegevoegde apparaten. De identiteit wordt opnieuw gecontroleerd bij het opstarten en na elke terugkeer uit OFFLINE.
- **Herconfiguratie** voor het wijzigen van het IP-adres, met controle dat het hetzelfde apparaat is.

### 6.6 Entiteiten voor de AC3220

Entiteiten worden aangemaakt uit de bewaarde sleutelset van het apparaat (zie 6.3), omdat de sleutels per firmware verschillen. Verschijnt er later een nieuwe sleutel, dan komt de bijbehorende entiteit erbij. De volledige datapunttabel staat in bijlage A.

**Ventilator (hoofdentiteit)**

| Eigenschap | Voorstel |
|---|---|
| Aan/uit | `D03102` |
| Stand en snelheid | `D0310C`: 0 auto, 17 slaap, 19 medium, 18 turbo, 1 tot 5 handmatig |
| Percentage teruglezen | Bij een vaste snelheid uit de stand. In auto en slaap geen percentage: Home Assistant behandelt percentage en voorkeuzestand als elkaar uitsluitend, en een scène die in auto is opgeslagen zou het apparaat anders uit auto halen (aangetoond bij de controle van 23 november 2026). Het werkelijke toerental staat in een eigen sensor. |

Twee varianten voor de indeling, te kiezen na de meting:

| | Variant A | Variant B |
|---|---|---|
| Voorkeuzestanden | `auto`, `sleep`, `medium`, `turbo` | `auto`, `sleep` |
| Snelheid | Vijf stappen | Vijf stappen; Medium wordt getoond als 60% en Turbo als 100% |
| Voor | Komt overeen met de knoppen op het apparaat | Volgt de richtlijn van Home Assistant: vaste snelheden zijn geen voorkeuzestanden. Geen dubbelingen. |
| Tegen | Op de AC4220/12 is snelheid 5 hetzelfde toerental als Turbo en snelheid 3 hetzelfde als Medium, dus twee namen voor één toestand | "Turbo" bestaat niet meer als naam |

Mijn voorkeur is variant B als de meting bevestigt dat de snelheden 1 tot 5 werken en samenvallen met Medium en Turbo. Handmatige snelheden zijn bevestigd op de AC4220/12, AC4221 en AC3221/13 en staan in de specificatie van de AC3220 ("5 niveaus"), maar zijn niet op een AC3220 waargenomen. Werken ze niet, dan blijft variant A zonder snelheidsregeling over. De tabel met standen wordt gegevensgestuurd, zodat wisselen geen herbouw vraagt.

**Sensoren**

| Entiteit | Sleutel | Standaard |
|---|---|---|
| Fijnstof PM2.5 (µg/m³) | `D03221` | Aan |
| Allergenenindex (1 tot 12) | `D03120` | Aan |
| Temperatuur | `D03224` gedeeld door 10 | Aan |
| Luchtvochtigheid | `D03125` | Aan |
| Filter resterend (%) | `D0540E` gedeeld door `D05408`; nooit 0% zolang er uren over zijn | Aan, diagnostisch |
| Filter reinigen over (uren) | `D0520D` | Aan, diagnostisch |
| Einde van de timer (tijdstip) | Uit `D03211` | Aan |
| Laatste statusbericht (tijdstip, hooguit eens per minuut bijgewerkt) | Sessielaag | Aan, diagnostisch |
| Wifi-signaal, foutcode, laatste herstart, toerental | `rssi`, `D03240`, `Runtime`, `D0310D` | Uit, diagnostisch |

Eenheden komen uit `UnitOfDensity` en `UnitOfRatio`; de oudere constanten die beide bestaande integraties gebruiken, verdwijnen in Home Assistant 2027.8. De sensor "laatste herstart" wordt één keer per herstart van het apparaat berekend en niet bij elk bericht.

**Binaire sensoren:** filter vervangen (`D0540E` is 0), filter reinigen (`D0520D` is 0), storing (`D03240` is niet 0).

**Schakelaars:** kinderslot (`D03103`), pieptoon (`D03130`, 100 of 0), Auto+ (`D03180`), Allergie-slaap (`D03115`), sensoren in stand-by (`D03134`).

**Keuzelijsten:** lamp (`D03135`: uit 0, luchtkwaliteit 1, sfeerlicht 2), weergegeven index (`D0312A`: allergenen 0, PM2.5 1), timer (`D03110`: uit 0, 1 tot 12 uur als 2 tot 13).

**Pas na een geslaagde test op het apparaat:**

| Entiteit | Waarom wachten |
|---|---|
| Displayhelderheid (`D03105`: uit 0, automatisch 101, laag 115, fel 123) | Op een AC4220/12 alleen-lezen: schrijfopdrachten worden bevestigd en genegeerd. Op een AC4221 werkte alleen uitzetten. Tot de test een alleen-lezen sensor. |
| Lichtscène (`D03137`: 1 tot 4) | Niet schrijfbaar op een AC4220/12 en een AC4221; een Homey-gebruiker meldt dat de kleur van de lichtring op een AC3221/13 wel te wijzigen is. De app wijzigt mogelijk meerdere sleutels tegelijk. |
| Displayschakelaar (`D03112`, omgekeerd) | Alleen op nieuwere firmware; nergens op hardware bevestigd |
| Knoppen voor het terugzetten van de filtertellers | Geen lokale methode bekend voor deze generatie |

**Niet opslaan of tonen:** `Runtime` als ruwe waarde, `free_memory`, `StatusType`, `ConnectType` en de onbekende sleutels. `Runtime` verandert in elk bericht en zou de database vullen.

**Apparaatgegevens:** model uit `D01S05`, firmware uit `D01S12`, geen serienummer (`D01S0D` is een productcode per model).

### 6.7 Home Assistant: richtlijnen, tests en distributie

Home Assistant is in 2026 op een aantal punten veranderd die het plan raken. Alle vijftien beweringen hierover zijn op 22 november 2026 tegen de officiële bronnen gecontroleerd; geen enkele is weerlegd.

| Wijziging | Sinds | Gevolg voor dit project |
|---|---|---|
| Ontwikkelaarsdocumentatie staat op contributors.home-assistant.io | 16 oktober 2026 | Oude links verwijzen door |
| HACS is opgegaan in de ingebouwde "Marketplace", met dezelfde catalogus en hetzelfde `hacs.json` | 2026.11 | Installeren via een link vereist dat de gebruiker GitHub koppelt; opname in de catalogus duurt maanden |
| Testpakket `pytest-homeassistant` vervangt `pytest-homeassistant-custom-component`, dat zichzelf "kapot" noemt | 2026.11 | Er bestaat geen versie voor ouder dan 2026.11, dus **de minimale Home Assistant-versie wordt 2026.11.0** |
| Merkafbeeldingen staan in een map `brand/` in de integratie zelf | 2026.3 | `brand/icon.png` meeleveren |
| Eigen integraties leveren volledige `translations/<taal>.json`; `strings.json` en verwijzingen werken alleen in de kern | | `en.json` volledig, plus `nl.json` |
| Een apparaat hoort bij precies één integratie | 2026.8 | De nieuwe integratie kan naast een oude in de apparatenlijst staan. Ze tegelijk laten draaien blijft op protocolniveau onverstandig. |
| Uitzondering `UpdateFailedUnreachable` | 2026.12 | Niet nodig: de sessielaag schrijft zelf de twee logregels |
| `DeviceInfo` is een dataclass | 2026.11 | De nieuwe schrijfwijze gebruiken |

Verdere keuzes:

| Onderwerp | Voorstel |
|---|---|
| Gegevensstroom | `DataUpdateCoordinator` zonder interval; status komt binnen via `async_set_updated_data`; beschikbaarheid komt uit de sessielaag |
| Opslag tijdens draaien | Getypeerde `entry.runtime_data` |
| Fouten bij commando's | Vertaalde `HomeAssistantError` |
| Entiteiten | `has_entity_name`, vertaalsleutels, `icons.json`, beschrijvingen met een functie die bepaalt of de sleutel bestaat |
| Diagnostiek | Download met afgeschermde identificatie, plus tellers: tijd sinds laatste bericht, controles, time-outs, overgeslagen berichten, werkende vernieuwingsvorm, herverbindingen |
| Tests | Een nagebootste luchtreiniger op 127.0.0.1 die elk bekend firmwaretrekje kan vertonen; elk trekje wordt een regressietest |
| Controle bij elke wijziging | hassfest, de HACS-validatie, ruff, mypy, en tests tegen de minimale, de huidige en de bètaversie van Home Assistant |
| Distributie | Een GitHub-release per versie en een installatielink in de README; na de eerste stabiele versie aanmelden voor de catalogus |
| Domeinnaam | `philips_pureprotect` (besloten; vrij in de kern en in de catalogus op 22 november 2026) |

### 6.8 Wat we bewust niet doen

| Niet doen | Reden |
|---|---|
| Cloud als onderdeel van de werking | Dezelfde gegevens, en een geheim uit de app nodig. De statuslaag wordt wel zo opgezet dat een cloudroute later kan worden toegevoegd, bijvoorbeeld om op verzoek een verse status op te halen. |
| De alternatieve handshake (RSA met AES-GCM) uit kongo09 pull request #384 | De code kan in die pull request nooit worden uitgevoerd en is nergens op een apparaat aangetoond. De gewone handshake werkt op verwante modellen met `@86`. |
| Een statusbericht afdwingen met een schrijfopdracht, als standaard | Onbewezen op deze familie; een opdracht met de huidige waarde gaf op de AMF870 geen bericht, en een gewijzigde waarde kan een pieptoon of zichtbaar effect geven |
| ICMP-ping of een losse statusaanvraag als bereikbaarheidscontrole | Ping zegt niets over de CoAP-toepassing: één AC2220 negeert het, een AC2210 en een AC0850 blijven het beantwoorden terwijl de statusstroom dood is. Een statusaanvraag wordt tijdens stilte niet beantwoord. |

---

## 7. Eerst meten op jouw apparaat

De meting bestaat uit twee delen. Het eerste kan vandaag met bestaande hulpmiddelen. Het tweede vraagt een eigen meetprogramma, omdat de bestaande hulpmiddelen geen losse sync, geen vernieuwing van een abonnement en geen tweede kenmerk kunnen sturen.

### 7.1 Snelle controle met bestaande hulpmiddelen (ongeveer een halfuur)

**Vooraf**

- Schakel de bestaande integratie voor dit apparaat uit in Home Assistant.
- Sluit de Air+ app geforceerd af op alle telefoons. De app is zelf een lokale client en lokt berichten uit.
- Gebruik nooit de opdracht `status` terwijl `status-observe` loopt: op sommige firmware neemt de nieuwste aanvraag de stroom over.

Op een computer in hetzelfde netwerk, met Python 3.12 of nieuwer en het programma `coap-client` uit het pakket libcoap:

```bash
python3 -m venv venv && . venv/bin/activate
pip install aioairctrl==0.3.1
```

Start in een tweede venster een netwerkopname. Fragmenten en ARP-verkeer komen zo mee:

```bash
sudo tcpdump -n -i <interface> -w ac3220.pcap 'host <ip-luchtreiniger> or arp host <ip-luchtreiniger>'
```

**Stappen**

| # | Vraag | Hoe |
|---|---|---|
| 1 | Welk MAC-voorvoegsel en welke DHCP-hostnaam? | Apparatenlijst van de router |
| 2 | Antwoordt de info-aanvraag, en met welk apparaat-id? | `coap-client -m get coap://<ip>/sys/dev/info`, één keer terwijl het apparaat draait en één keer in stand-by. Noteer `device_id`, `modelid`, `type` en `option`. Alternatief: `philips-airctrl device-info-raw -H <ip>`; de installatie daarvan vraagt een C-compiler. |
| 3 | Firmware, sleutelset, en hoe snel het eerste bericht komt | Eén lange sessie met de logopdracht hieronder, gestart terwijl het apparaat draait. Vergelijk `DeviceId` met het `device_id` uit stap 2. |
| 4 | Blijft het abonnement leven? | Laat de sessie van stap 3 lopen en druk na 3, 5, 10 en 15 minuten op de standknop van het apparaat. Verschijnt na elke druk een bericht? |
| 5 | Welke schrijfopdrachten werken? | In een ander venster, terwijl de sessie loopt, met `-I` voor gehele getallen: `aioairctrl -H <ip> set -I D0310C=3`. Zie de lijst hieronder. Noteer per opdracht het antwoord, of de stroom de nieuwe waarde meldt, en na hoeveel seconden. |
| 6 | Geeft een opdracht met de huidige waarde een bericht? | Schrijf de waarde die al geldt, bijvoorbeeld `set -I D03103=0` bij een uitgeschakeld kinderslot |
| 7 | Wat doet de app? | Als laatste: open de Air+ app. Komt er op dat moment een bericht in de stroom, en loopt de stroom daarna door? |

De logopdracht, met een tijdstempel per regel:

```bash
aioairctrl -H <ip> -D status-observe -J 2>&1 | while IFS= read -r regel; do
  printf '%s %s\n' "$(date +%T)" "$regel"
done | tee observe.log
```

Schrijfopdrachten voor stap 5, in deze volgorde:

| Onderdeel | Opdrachten | Let op |
|---|---|---|
| Aan/uit | `D03102=0`, `D03102=1` | |
| Standen | `D0310C=0`, `17`, `19`, `18` | Noteer telkens `D0310D` |
| Snelheden | `D0310C=1` tot `5` | Meldt `D0310D` 1, 2, 3, 4 en 18? |
| Lamp | `D03135=0`, `1`, `2` | Belangrijkste lichttest |
| Schakelaars | `D03103`, `D03130` (0 en 100), `D03180`, `D03115`, `D03134` | |
| Instellingen | `D0312A=0` en `1`, `D03110=2` en `0` | |
| Display en scène | `D03105=0`, `101`, `115`, `123`; `D03137=1` tot `4` | Verwachting: genegeerd |

Valkuilen bij het lezen van de uitkomst: een opdracht die blijft hangen kan een verloren sync zijn (afbreken en herhalen), en een sessie die met een foutmelding stopt kan een beschadigd bericht zijn en geen verlopen abonnement.

### 7.2 Meetprogramma

Het meetprogramma staat in [`tools/probe/`](../tools/probe/README.md). Het gebruikt een kale UDP-socket, legt elk datagram met tijdstempel vast en vervangt ook de snelle controle uit 7.1: de opdracht `quick` doet die stappen in twee minuten. Het is getest tegen een nagebootst apparaat en tegen bestaande implementaties, maar nog niet tegen een echte luchtreiniger.

Het programma voert deze reeks uit:

| Meting | Beslist |
|---|---|
| Sync, info-aanvraag en lege CoAP-ping elke 30 seconden, twee uur in stand-by, met en zonder "sensoren in stand-by" | Welke bereikbaarheidscontrole |
| Eén abonnement zonder vernieuwing; knopdruk na 3, 5, 10 en 20 minuten | Of het abonnement verloopt |
| Vernieuwen met hetzelfde kenmerk, daarna met een nieuw kenmerk; wordt een vernieuwing direct beantwoord? | De vorm van vernieuwen, en of vernieuwen als opvraging kan dienen |
| Tweede client vanaf dezelfde computer en vanaf een andere | Eén abonnee per IP of niet |
| Stroom eraf en erop | Tijd tot de eerste geldige status; gedrag van teller en abonnement |
| Elke schrijfopdracht met de tijd tot de terugmelding | De deadlines in 6.4 |
| Afmelden van een abonnement | Of het apparaat dat respecteert |
| Elke 10 seconden een sync terwijl je het apparaat via de app bedient | Of onze controles de app storen |
| Info-aanvraag naar broadcast en naar 224.0.1.187, elk 20 keer | Of automatisch zoeken werkt |
| Uit de opname: bevestigbare of niet-bevestigbare meldingen, Max-Age, volgnummers, fragmenten | Details van de protocollaag |

### 7.3 Wat de uitkomsten beslissen

| Uitkomst | Gevolg voor het ontwerp |
|---|---|
| Info-aanvraag antwoordt niet | Apparaat-id uit het eerste statusbericht; instellen vraagt een knopdruk |
| Eerste bericht komt direct, ook in stand-by | Opstarten en vernieuwen leveren meteen een verse status |
| Eerste bericht komt pas bij een verandering | De bewaarde status en de entiteit "Laatste statusbericht" zijn onmisbaar |
| Abonnement verloopt | De vernieuwing voorkomt het; de meting bepaalt met welk kenmerk |
| Abonnement verloopt niet | Vernieuwen blijft aan als herstelmiddel, met dezelfde frequentie |
| Opdracht met de huidige waarde geeft een bericht | Bruikbaar om na een herstart de status te verversen, samen met de bewaarde status |
| Lamp-, display- of scène-opdrachten worden genegeerd | Die entiteiten alleen-lezen maken of weglaten |
| Snelheden 1 tot 5 werken en vallen samen met Medium en Turbo | Variant B voor de ventilator |
| De app lokt een bericht uit of verstoort de stroom | Vastleggen in de documentatie; bij verstoring is de oplopende vernieuwing het herstel |
| MAC-voorvoegsel buiten de bekende acht | Herkenning uitbreiden |

---

## 8. Voorgesteld stappenplan

| Stap | Inhoud | Resultaat | Stand op 23 november 2026 |
|---|---|---|---|
| 0 | Snelle controle uit 7.1 | Firmware, sleutelset en werkende schrijfopdrachten van jouw apparaat | Gedaan met het meetprogramma |
| 1 | Meetprogramma bouwen en de reeks uit 7.2 draaien | Ontwerpkeuzes vastgelegd; de kern van de protocollaag bestaat | Programma klaar. Elf metingen gedaan, zie [metingen.md](metingen.md); daar staat ook wat nog open is |
| 2 | Protocol- en sessiepakket met nagebootst apparaat en tests | Betrouwbare verbinding, los van Home Assistant te testen | Klaar en door drie controleurs nagelopen; 154 tests. Nog niet tegen het echte apparaat gedraaid |
| 3 | Minimale integratie: instellen met IP-adres, coordinator, ventilator en sensoren | Werkend in je eigen Home Assistant | Geschreven, samen met stap 4. Door vier controleurs nagelopen, de bewezen fouten opgelost en dat onafhankelijk nagecontroleerd; 116 tests in Home Assistant 2026.11. Nog niet in je eigen Home Assistant gedraaid |
| 4 | Overige entiteiten, diagnostiek, DHCP-herkenning, herconfiguratie, vertalingen | Volledige functionaliteit | Entiteiten, diagnostiek, herconfiguratie en vertalingen zijn er. Nog niet: DHCP-herkenning, zoeken in het netwerk, knoppen voor de filtertellers |
| 5 | Duurtest van één tot twee weken op je eigen apparaat, met de diagnostiektellers | Aantoonbaar stabiel | Nog niet begonnen |
| 6 | Eerste release met installatielink; kleine verbeteringen aanbieden bij de bestaande projecten | Publiek beschikbaar | Nog niet begonnen |

---

## 9. Open vragen en beslissingen

**Alleen op het apparaat te beantwoorden** (hoofdstuk 7):

- Firmwareversies en sleutelset van jouw exemplaar.
- Of de info-aanvraag en de sync tijdens stilte antwoorden.
- Direct antwoord op een abonnement of pas bij verandering.
- Verloop van het abonnement en de juiste manier van vernieuwen.
- Welke schrijfopdrachten lokaal werken, in het bijzonder lamp, display en filterteller.
- MAC-voorvoegsel en hostnaam.
- Of de app en Home Assistant elkaar storen.

**Niet gevonden:**

- Welke servers het apparaat benadert, en dus welke je zou moeten blokkeren om updates tegen te houden. Alleen het volledig blokkeren van internet voor het apparaat is betrouwbaar, en ervaringen daarmee op deze generatie zijn schaars.
- Nederlandse gebruikerservaringen op Tweakers; die site was voor geen enkel hulpmiddel leesbaar.
- De betekenis van de sleutels `D03106`, `D0311F`, `D03136`, `D0313B`, `D03182`, `D03R81`, `D05102` en de `D011xx`-reeks.

**Genomen beslissingen:**

| Beslissing | Keuze | Datum |
|---|---|---|
| Domeinnaam | `philips_pureprotect`, met weergavenaam "Philips PureProtect". Het domein is definitief; de weergavenaam kan later nog wijzigen. | 22 november 2026 |
| Indeling van de ventilator | Voorlopig variant B uit 6.6: de standen auto en slaap, en vijf snelheden; medium en turbo zijn 60% en 100%. De meting bevestigde dat snelheid 3 en medium, en snelheid 5 en turbo, hetzelfde toerental geven. De tabel is gegevensgestuurd, dus wisselen naar variant A blijft een kleine wijziging. | 23 november 2026, door mij gekozen; jij kunt het nog omdraaien |
| Licht | Voorlopig drie keuzelijsten (licht, helderheid, scène), geschreven zoals de app dat doet. Definitief na de meting `write-matrix`. | 23 november 2026, voorlopig |
| Minimale Home Assistant-versie | 2026.11.0. Jouw installatie draait 2026.11.2, dezelfde versie waartegen de tests draaien. | 23 november 2026 |
| Aan of uit na een herstart | Een apparaat dat aan staat beantwoordt een nieuw abonnement binnen twee seconden en meldt daarna elke paar seconden iets; in stand-by zwijgt het. Antwoordt het apparaat wel op controles maar komt er tien seconden na een nieuw abonnement geen statusbericht, dan gaat de integratie ervan uit dat het uit staat. Het eerste statusbericht daarna geeft de werkelijke toestand. Zonder deze regel zou Home Assistant na een herstart "aan" blijven tonen voor een apparaat dat uit staat. | 23 november 2026, door mij gekozen |
| Meetwaarden terwijl het apparaat uit staat | Fijnstof, allergenenindex, temperatuur en luchtvochtigheid zijn "onbekend" zolang het apparaat uit staat en "sensoren in stand-by" uit is, omdat het dan niet meet. Dit wijkt af van "laatste waarden blijven staan" in 6.3: een temperatuur van gisteren als actueel tonen is misleidend. | 23 november 2026, door mij gekozen; jij kunt het nog omdraaien |
| Licht uitzetten | Voorlopig alleen de lampfunctie op uit, zonder de helderheid te wijzigen. Verwante modellen negeren een nieuwe helderheid, en dan zou uitzetten als mislukt worden gemeld. Definitief na de meting `write-matrix`. | 23 november 2026, voorlopig |

**Beslissingen voor jou:**

| Beslissing | Opties | Mijn voorkeur |
|---|---|---|
| Reikwijdte | Alleen de 3200-serie, of ook de verwante 2200- en 4200-serie | Beginnen met de 3200-serie; de modeltabel zo opzetten dat de andere erbij kunnen |

---

## Bijlage A. Datapunten van de AC3220

Bronnen: de statusdump van een AC3220/10 (november 2024, firmware `0.1.9`), een dump van een AC3210/12 (2026, firmware `0.2.3`), de openHAB-binding, en waarnemingen op de AC4220/12 en AC4221/11. Geen van de schrijfopdrachten is op een AC3220 bevestigd.

### Identiteit en beheer

| Sleutel | Betekenis | Voorbeeld |
|---|---|---|
| `D01S03` | Naam uit de app | "Salon" |
| `D01S04` | Platformnaam | "Unicorn" |
| `D01S05` | Model | "AC3220/10" |
| `D01S12` | Apparaatfirmware | "0.1.9", "0.2.3" |
| `D01S0D` | Productcode per model, geen serienummer | "688001001384" |
| `DeviceId` | Uniek per apparaat; ook de naam van het apparaat in de cloud | 32 hextekens |
| `ProductId` | Per model | 32 hextekens |
| `WifiVersion` | Wifi-firmware | "AWS_Philips_AIR_Combo@86" |
| `Runtime` | Looptijd van de wifi-module in milliseconden; begint opnieuw bij een herstart | |
| `rssi` | Wifi-signaal in dBm | -49 |
| `StatusType` | "status", of kort "control" na een commando | |
| `ConnectType` | "Online": de verbinding van het apparaat met de cloud | |

### Toestand, instellingen en sensoren

| Sleutel | Betekenis | Waarden | Lokaal schrijven op verwante modellen |
|---|---|---|---|
| `D03102` | Aan/uit | 1 aan, 0 uit | Werkt (AC4221/11; AC3221/13 via Homey) |
| `D03103` | Kinderslot | 1, 0 | Werkt (AC4221/11) |
| `D03105` | Displayhelderheid | 0 uit, 101 automatisch, 115 laag, 123 fel | Tegenstrijdig: alleen-lezen op AC4220/12; op AC4221/11 werkte alleen 0 |
| `D0310C` | Stand | 0 auto, 1 tot 5 handmatig, 17 slaap, 18 turbo, 19 medium; -16 als het apparaat uit staat | Werkt (AC4221/11; snelheid op AC3221/13 via Homey) |
| `D0310D` | Werkelijk toerental | 0, 1 tot 4, 18 is het hoogste | Alleen-lezen |
| `D03110` | Timer | 0 uit, 2 tot 13 is 1 tot 12 uur | Niet bevestigd |
| `D03211` | Resterende timertijd in minuten | 0 tot 720 | Alleen-lezen |
| `D03112` | Display aan/uit, omgekeerd; alleen op nieuwere firmware | 0 aan, 1 uit | Niet bevestigd |
| `D03115` | Allergie-slaap | 1, 0 | Niet bevestigd |
| `D03120` | Allergenenindex | 1 tot 12 | Alleen-lezen |
| `D03221` | Fijnstof PM2.5 in µg/m³ | | Alleen-lezen |
| `D03224` | Temperatuur maal 10 | 212 is 21,2 °C | Alleen-lezen |
| `D03125` | Luchtvochtigheid in % | | Alleen-lezen |
| `D0312A` | Weergegeven index | 0 allergenen, 1 PM2.5 | Niet bevestigd |
| `D0312C` | Drempel voor meldingen in de app | 1, 4, 7, 10 | Niet bevestigd |
| `D03130` | Pieptoon | 100 aan, 0 uit | Werkt (AC4220/12; 1 leest terug als 100) |
| `D03134` | Sensoren actief in stand-by | 1, 0 | Niet bevestigd |
| `D03135` | Lampfunctie | 0 uit, 1 luchtkwaliteit, 2 sfeerlicht | Werkt op AC4220/12 (0, 1, 2); op AC4221/11 werkte alleen 0 |
| `D03137` | Lichtscène; alleen op nieuwere firmware | 1 tot 4 | Niet schrijfbaar op AC4220/12 en AC4221/11 |
| `D03180` | Auto+ | 1, 0 | Niet bevestigd |
| `D03240` | Foutcode | 0 is geen fout | Alleen-lezen |

De melding over de AC4221/11 gebruikte mogelijk tekstwaarden in plaats van getallen. Dat verklaart het patroon "uit werkt, aan niet" en maakt die uitkomsten onzeker.

### Filters

| Sleutel | Betekenis | Voorbeeld |
|---|---|---|
| `D05408` | Levensduur filter, totaal in uren | 9600 |
| `D0540E` | Levensduur filter, resterend in uren | 9501 |
| `D05207` | Reinigingsinterval, totaal in uren | 720 |
| `D0520D` | Uren tot de volgende reiniging | 621 |

Opbouw van de sleutelnamen: `D`, twee cijfers voor de groep (`01` apparaat, `03` bediening en sensoren, `05` filters), een teken voor het type (`1`, `2` of `4` bytes, `S` tekst, `R` ruwe gegevens) en twee hextekens voor het nummer.

---

## Bijlage B. Controle van de bevindingen

**Zelf nagekeken in de broncode, alle bevestigd:** het ontbreken van time-outs in aioairctrl; het hergebruik van het oude versleutelde bericht in philips-airctrl; de altijd-beschikbare entiteiten, de opgeslagen status en de bewaking van 180 seconden in kongo09; de vernieuwing met deadline van 10 seconden en het ontbreken van de afdwingtruc voor de AC3220 in tinkerologie; de verkeerde sleutel `D03-42` in beide; de vier op hardware geverifieerde feiten over de AC4220/12 in het Homebridge-project van ruaan-deysel.

**Veertien beweringen uit issue-trackers** ([notitie 11](research/11-verify-firmware-claims.md)): tien bevestigd, vier deels, geen weerlegd. De belangrijkste correcties:

- Het gedrag "alleen bij verandering" is voor de verwante 2200- en 4200-serie afgeleid uit time-outstatistieken; de beslissende proef staat in geen van die issues. De directe meting komt van de ESP32-logger op een AC2220/10.
- Het verlopen van een abonnement na 150 seconden rust op twee sessies op één AC4220/12.
- In geen enkele gelezen bron staat een AC3210, AC3220 of AC3221 op `@86` met gemeten gedrag.

**Elf beweringen uit fora** ([notitie 12](research/12-verify-forum-claims.md)): zes bevestigd, vijf deels, geen weerlegd. De belangrijkste correcties:

- De melding dat een Nederlandse AC3220/10 "prima werkt" (januari 2026) is van iemand die het apparaat net had gekocht, zonder versienummers.
- Een Australische AC3220/10 op `0.2.3` met `@86` gaf niets terug aan aioairctrl (april 2026); de oorzaak is nooit opgehelderd. Op stille firmware is dat het verwachte gedrag van die opdracht bij een apparaat in rust.
- De wachttijden van 30, 60 en 120 seconden zijn alleen van ioBroker; openHAB heeft geen oplopende wachttijd.

**Controle van dit rapport zelf** (notities [13a](research/13a-review-factcheck.md), [13b](research/13b-review-design.md) en [13c](research/13c-review-ha-claims.md)):

| Controleur | Uitkomst | Verwerkt |
|---|---|---|
| Feiten | Geen verzonnen cijfers en geen ernstige fouten; vijf middelzware en acht kleine onnauwkeurigheden | Alle, onder meer de schrijfbaarheid van licht en display, de te smalle bandbreedtes in 3.2 en de te stellige samenvatting |
| Ontwerp | Vijf ernstige zwakke plekken: bevestiging van commando's zonder deadline, optionele vernieuwing als enig herstelmiddel, te snel OFFLINE, geen entiteiten vóór het eerste bericht, en een meetplan dat niet alles kon beslissen | Alle; hoofdstuk 6 en 7 zijn daarop herschreven |
| Home Assistant | Vijftien beweringen over 2026: twaalf bevestigd, drie in smallere vorm, geen weerlegd. Wel vier gebreken in het rapport: twee eigenaren van de bereikbaarheidsbewaking, onduidelijk aanmaken van entiteiten, ontbrekend testpakket en verouderd distributieadvies | Alle, in 6.2, 6.3, 6.6 en 6.7 |

Het ontwerp in hoofdstuk 6 is een doorgerekend voorstel op papier. Het is op geen enkel apparaat uitgevoerd.

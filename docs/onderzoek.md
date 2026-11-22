# Onderzoek: Philips PureProtect 3200 (AC3220/10) en Home Assistant

Datum: 22 november 2026.

Dit rapport beantwoordt twee vragen: hoe communiceert de AC3220/10, en hoe bouwen we er een betrouwbare Home Assistant-integratie voor. Het is gebaseerd op de broncode van zeventien bestaande projecten, issue-trackers, fora, de officiële handleiding en productgegevens van Philips.

**Er is niets op een echte AC3220 getest.** Alles over het gedrag van jouw apparaat op de huidige firmware is afgeleid van verwante modellen. Hoofdstuk 7 beschrijft een korte meetsessie die dat gat dicht; die hoort vóór het bouwen te komen.

Bewijsniveaus in dit rapport:

| Label | Betekenis |
|---|---|
| **[code]** | Zelf nagekeken in de broncode van het genoemde project. |
| **[gemeten: model]** | Door een derde gemeten op het genoemde model, teruggelezen in de bron. |
| **[aanname]** | Afgeleid van verwante modellen of documentatie; niet aangetoond op een AC3220. |

De onderliggende onderzoeksnotities (Engels, met bronverwijzingen per bewering) staan in [`docs/research/`](research/README.md).

---

## 1. Samenvatting

**Hoe het apparaat communiceert.** De AC3220 is een CoAP-server op UDP-poort 5683 in je eigen netwerk. Er is geen koppeling en geen wachtwoord. De inhoud is versleuteld met een vaste, publiek bekende sleutelafleiding; dat is verhulling en geen beveiliging. Het apparaat praat daarnaast met de Philips-cloud, en ook de Air+ app gebruikt op het thuisnetwerk dit lokale protocol.

**Waarom de bestaande integraties haperen.** De recente wifi-firmware (`AWS_Philips_AIR_Combo@86`) meldt de status alleen wanneer er een waarde verandert. In stand-by is het apparaat stil, en een statusaanvraag wordt pas bij de volgende verandering beantwoord. Beide HACS-integraties zien die stilte als een verbroken verbinding:

- `kongo09/philips-airpurifier-coap` breekt na 180 seconden stilte de hele verbinding af en bouwt haar opnieuw op. Verzoeken hebben geen time-out, dus één verloren pakketje kan een commando of herverbinding laten hangen. Na een herstart toont de integratie een oude, opgeslagen status als actueel.
- `tinkerologie/ha-philips-airpurifier` vernieuwt het statusabonnement elke 60 seconden en gooit het werkende abonnement weg als het apparaat niet binnen 10 seconden antwoordt. Op verwante modellen leverde dat 118 storingen per dag op, tegen 14 zonder die vernieuwing.

Daarnaast bevatten beide integraties voor de AC3220 een verkeerde sleutel (de keuzelijst "voorkeursindex" werkt nooit) en missen ze meerdere functies.

**Advies.** Bouw een nieuwe, kleine integratie die alleen deze generatie luchtreinigers bedient, met een eigen protocollaag:

1. Bereikbaarheid bepalen met een aparte, lichte controle (de sync-handshake) en nooit uit stilte op de statusstroom.
2. Eén socket en één abonnement per apparaat, voor de hele levensduur van de integratie. Niets afbreken op een timer.
3. Elk verzoek een time-out en een beperkt aantal herhalingen geven.
4. Commando's pas als geslaagd tonen wanneer het apparaat de nieuwe waarde terugmeldt.
5. Geen cloud in het kritieke pad.

**Eerst meten.** Drie eigenschappen van jouw apparaat bepalen het ontwerp en zijn nu onbekend: of het direct antwoordt op een statusabonnement, of een abonnement na ongeveer 150 seconden verloopt, en welke schrijfopdrachten het lokaal accepteert. Een meetsessie van ongeveer een uur beantwoordt dat (hoofdstuk 7).

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
| Verlichting | Display, lichtring | Lampfunctie en lichtscènes |
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

**Schrijfopdrachten.** De inhoud is `{"state":{"desired":{"CommandType":"app","DeviceId":"","EnduserId":"", <sleutel>: <waarde>}}}`. Waarden moeten als geheel getal worden gestuurd. Als tekst gestuurde waarden worden genegeerd, terwijl het apparaat soms toch "success" antwoordt. **[gemeten: CX3120; patroon ook bij AC4221/11]**

### 3.2 Gedrag van de firmware

Dit is het deel dat de betrouwbaarheid bepaalt. De tabel geeft per eigenschap het sterkste bewijs en wat dat voor de AC3220 betekent.

| Eigenschap | Sterkste bewijs | Voor de AC3220 |
|---|---|---|
| Status alleen bij verandering, geen hartslag | **[gemeten: AMF870/15]** met netwerkopname over vier dagen: stiltes van 12 minuten tot 2 uur, ongeveer 18 keer per dag. **[gemeten: AC2220/10, firmware 0.2.3 met @86]**: stil tot 14 minuten op een lopend abonnement. | **[aanname]**, waarschijnlijk |
| Een abonnementsaanvraag wordt pas bij de volgende verandering beantwoord | **[gemeten: AC2220/10]**: 6,5 seconden tot 14 minuten. **[gemeten: AC2210]**: 47% van 414 vernieuwingen onbeantwoord binnen 10 seconden. | **[aanname]**, waarschijnlijk |
| Sync blijft antwoorden tijdens stilte | **[gemeten: AC2220/10]** ongeveer 100 ms; **[gemeten: CX7550/01]** 26 van 26 controles in 4,6 uur met één statusbericht. Op de AMF870 bleef sync een enkele keer een paar minuten onbeantwoord. | **[aanname]** |
| Schrijven werkt tijdens stilte | **[gemeten: AMF870/15]** 4 van 4 binnen 109 tot 211 ms | **[aanname]** |
| Abonnement verloopt na ongeveer 150 seconden zonder vernieuwing | **[gemeten: AC4220/12]**, twee sessies op één apparaat; de oorzaak is volgens het issue zelf "niet bevestigd" | Onbekend |
| Eén abonnee per bron-IP, de nieuwste wint | **[gemeten: AMF870/15]**. Op een AC2220 werkten twee clients naast elkaar. | Onbekend |
| Beschadigde berichten uit het apparaat zelf | **[gemeten: AMF870/15 en AC0850]**: één op de 1.800 tot 5.300 statusberichten bevat nul-bytes bij een geldig controlegetal. Ook sync-antwoorden zijn soms misvormd. | **[aanname]** |
| Apparaat negeert een deel van de broadcast-ARP-verzoeken | **[gemeten: AMF870/15 op één UniFi-netwerk]**: 61% beantwoord | Onbekend |
| Berichtnummers van het apparaat zijn onbetrouwbaar | Meerdere modellen sturen steeds hetzelfde nummer | **[aanname]** |

Er is geen aanwijzing gevonden dat een firmware-update lokale toegang heeft verwijderd op de 2200-, 3200- of 4200-serie. De modellen zonder lokaal protocol (AC0650, AC0651, nieuwere AC1715) zijn een ander hardwareplatform met een ESP32-module. Voor de AC1715 is de oorzaak niet opgehelderd, en bij Philips-airfryers is een overgang naar alleen-cloud via een update wel gedocumenteerd. Uitsluiten kan dus niemand het.

### 3.3 Ontdekken in het netwerk

- Een verwant model op `@86` (AC0950/10) beantwoordt een onversleuteld `GET /sys/dev/info` binnen ongeveer 200 ms, ook als het naar het broadcast-adres of naar multicast-adres 224.0.1.187 wordt gestuurd. **[gemeten: AC0950/10]**
- Het antwoord bevat `device_id`, en dat is dezelfde waarde als `DeviceId` in de versleutelde status. Een apparaat is dus te vinden en eenduidig te herkennen zonder sync en zonder abonnement.
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

De cloud levert geen extra gegevens, meldt ook alleen bij verandering, en vereist een geheim dat uit de app moet worden gehaald. De cloud hoort daarom niet in het kritieke pad. De app zelf gebruikt op het thuisnetwerk het lokale protocol: op een AC4221/11 met `@86` is verkeer van telefoon naar luchtreiniger op poort 5683 vastgelegd, en de app bleef werken met het internet van het apparaat geblokkeerd. **[gemeten: AC4221/11]**

Officieel ondersteunt Philips alleen Alexa en Google voor spraakbediening. Er is geen Matter, HomeKit, SmartThings of openbare API gevonden.

---

## 4. Waarom de bestaande integraties onbetrouwbaar zijn

### 4.1 kongo09/philips-airpurifier-coap

Laatste wijziging op 26 juli 2026; de verbeteringen voor betrouwbaarheid staan als niet-samengevoegde pull requests open of zijn gesloten. Alle punten hieronder: **[code]**.

| Probleem | Gevolg |
|---|---|
| Geen time-out op enig verzoek; verzoeken worden één keer en zonder ontvangstbevestiging verstuurd | Eén verloren pakketje laat een commando of herverbinding onbeperkt hangen |
| Entiteiten zijn altijd "beschikbaar" en starten met de status die bij het toevoegen is opgeslagen | Na een herstart zie je mogelijk maanden oude waarden als actueel |
| Enige herstel: na 180 seconden stilte de hele client afbreken en opnieuw opbouwen | Op stille firmware gebeurt dat de hele dag door; elke herverbinding kan hangen |
| De ontvangstlus heeft geen foutafhandeling | Eén beschadigd bericht stopt alle updates tot de volgende herstart van de verbinding |
| Het resultaat van commando's wordt niet gecontroleerd | De gevraagde waarde wordt getoond, ook als het apparaat haar negeerde |
| De DHCP-ontdekking opent een tweede sessie naar een al ingesteld apparaat | Kan de lopende sessie haar meldingen afnemen |

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
| AC2210 | tinkerologie 2026.10.3 (met vernieuwing) tegen 2026.10.2 (zonder), elk 24 uur | 118 tegen 14 storingen; 10 uur 22 minuten tegen 3 uur 21 minuten onbeschikbaar |
| AC2220/10 | tinkerologie 2026.11.1 gedurende 30 uur tegen kongo09 v0.37 gedurende 8,5 dag | 56 tegen 5 periodes onbeschikbaar |

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
- Op verwante modellen gaf kongo09 v0.37 de minste zichtbare storingen, met als prijs dat waarden verouderd kunnen zijn. Bij tinkerologie is versie 2026.10.2 de laatste zonder de vernieuwing.
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
| Homey-app | Geen | Beëindigt elk abonnement na 600 seconden | Eén beschadigd bericht beëindigt de sessie. AC3220-eigenaren melden instabiliteit. |

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
| **Nieuw en gericht** | Eén generatie, naar schatting 600 tot 900 regels integratie plus de protocollaag; het juiste bereikbaarheidsmodel vanaf het begin | Eigen protocollaag schrijven en testen |

De kleine, goedkope verbeteringen (de sleutel `D0312A`, de acties voor deze generatie, opnieuw versleutelen bij een herhaling) zijn het waard om daarnaast bij de bestaande projecten aan te bieden.

### 6.2 Opbouw in lagen

```
Home Assistant-platforms     fan, sensor, binary_sensor, switch, select, button, diagnostics
        │
Coordinator                  houdt de laatste status vast, bepaalt beschikbaarheid, voert commando's uit
        │
Sessielaag                   toestandsmachine: sync, abonnement, bereikbaarheidscontrole, herstel
        │
Protocollaag                 CoAP-berichten coderen en decoderen, versleuteling, één UDP-socket
```

De protocol- en sessielaag vormen samen een losstaand pakket dat niets uit Home Assistant importeert. Dat maakt het los testbaar tegen een nagebootst apparaat en later publiceerbaar als eigen library.

**Eigen CoAP-code in plaats van de library aiocoap.** Redenen:

- aiocoap heeft geen time-out voor verzoeken zonder ontvangstbevestiging. **[code]**
- aiocoap kan een abonnement niet met hetzelfde kenmerk vernieuwen en meldt het apparaat niet af.
- aiocoap verwerpt statusberichten waarvan het volgnummer niet oploopt, tot 128 seconden lang.
- Drie Philips-integraties moesten aiocoap programmabreed aanpassen, en Home Assistant levert het alleen indirect mee.

Het benodigde deel van CoAP is klein: berichtkop, kenmerk, de opties Uri-Path, Observe en Max-Age, GET en POST, en het bevestigen van binnenkomende berichten. Voor AES is het pakket `cryptography` genoeg, dat Home Assistant al meelevert. De integratie heeft dan geen externe afhankelijkheden.

### 6.3 Sessie: toestanden en tijden

```
              sync gelukt                    eerste statusbericht
 OFFLINE ───────────────▶ BEREIKBAAR, ─────────────────────────▶ ACTUEEL
    ▲      wachttijd        NOG GEEN STATUS                          │
    │                            │                                   │
    │  3 controles gemist        ▼                                   ▼
    └──────────────────────── TWIJFEL ◀──── 60 s zonder enig contact ┘
```

| Toestand | Entiteiten in Home Assistant | Wat er loopt |
|---|---|---|
| OFFLINE | Onbeschikbaar | Sync-pogingen met oplopende wachttijd |
| BEREIKBAAR, NOG GEEN STATUS | Beschikbaar, waarden onbekend | Abonnement, bereikbaarheidscontrole |
| ACTUEEL | Beschikbaar; laatste waarden blijven staan, hoe oud ook | Abonnement, bereikbaarheidscontrole |
| TWIJFEL | Ongewijzigd | Herhaalde controles |

| Onderdeel | Voorstel | Herkomst |
|---|---|---|
| Verzoeken | Zonder ontvangstbevestiging, met een eigen deadline per verzoek | Twee eigen CoAP-implementaties die op `@86` werken |
| Verbinden | Sync (3 pogingen, 5 seconden per poging), daarna de abonnementsaanvraag zonder op antwoord te wachten | AC2220: aanvraag wordt niet direct beantwoord |
| Bereikbaarheidscontrole | Na 60 seconden zonder enig contact een sync | openHAB, ioBroker, ESP32-logger |
| Gemiste controle | Elke 10 seconden opnieuw; na 3 missers OFFLINE | Ontwerpkeuze tussen de bestaande waarden in |
| Wachttijd bij OFFLINE | 10, 10, 10, 30, 60 seconden, daarna elke 60 seconden | Ontwerpkeuze |
| Abonnement vernieuwen | Instelbaar: zelfde kenmerk, nieuw kenmerk, of niet. Startwaarde: zelfde kenmerk elke 60 seconden, zonder antwoord te eisen | Niet beslist voor de AC3220; zie hoofdstuk 7 |
| Beschadigd bericht | Overslaan en tellen; na meer dan 3 op rij opnieuw sync en abonnement | ioBroker, openHAB |
| Dubbele berichten | Nooit op berichtnummer filteren | Apparaten hergebruiken berichtnummers |
| Herstart van het apparaat | Looptijd lager dan voorheen: opnieuw abonneren | Veld `Runtime` |
| Logboek | Eén regel bij verlies, één bij herstel | Home Assistant-richtlijn |

De kern: **stilte is nooit een fout, en er wordt niets afgebroken op een timer.** De getallen voor 3 missers en de wachttijden zijn keuzes binnen de bandbreedte van bestaande implementaties, geen gemeten optimum.

**Opstarten zonder status.** Op stille firmware kan het na een herstart van Home Assistant even duren voor het eerste bericht komt. Een draaiend apparaat meldt om de paar seconden; een apparaat in stand-by met de sensoren uit kan lang zwijgen. Tot dan zijn de entiteiten beschikbaar met onbekende waarden. Een schrijfopdracht om een statusbericht af te dwingen staat standaard uit: op een AC4220/12 werden schrijfopdrachten naar de displaysleutel genegeerd, en buiten Home Assistant doet geen enkel project dit voor luchtreinigers.

### 6.4 Commando's

1. Slot nemen, zodat commando's en controles elkaar niet kruisen.
2. Sync, daarna de schrijfopdracht met teller plus één. Dit is de werkwijze van openHAB en voorkomt verouderde tellers.
3. `{"status":"success"}` verwachten binnen 3 seconden; hooguit twee herhalingen, elk met een nieuwe sync en opnieuw versleuteld; totaal maximaal 10 seconden.
4. Wachten op het eerstvolgende statusbericht dat de sleutel bevat. Wijkt de waarde af, dan één keer opnieuw sturen en daarna een foutmelding in Home Assistant tonen.
5. Samengestelde acties, zoals aanzetten met een stand, in één bericht sturen.

### 6.5 Ontdekking en instellen

- **Herkenning** altijd via het onversleutelde `GET /sys/dev/info`. De `device_id` daaruit is de unieke sleutel van het apparaat in Home Assistant.
- **Drie routes naar dezelfde instelstroom:** DHCP-herkenning op alle acht MXCHIP-voorvoegsels, een actieve zoektocht via broadcast en multicast, en handmatige invoer van het IP-adres.
- **Nooit een tweede sessie** openen naar een apparaat dat al is ingesteld. Bij een DHCP-melding eerst het MAC-adres vergelijken zonder netwerkverkeer, en bij een nieuw IP-adres alleen het adres bijwerken.
- **Instellen slaagt** zodra de info-aanvraag en een sync lukken. Een statusbericht is geen voorwaarde.
- **Herconfiguratie** voor het wijzigen van het IP-adres, met controle dat het hetzelfde apparaat is.

### 6.6 Entiteiten voor de AC3220

Entiteiten worden alleen aangemaakt voor sleutels die het apparaat werkelijk meldt, omdat de sleutelset per firmware verschilt. De volledige datapunttabel staat in bijlage A.

**Ventilator (hoofdentiteit)**

| Eigenschap | Voorstel |
|---|---|
| Aan/uit | `D03102` |
| Voorkeuzestanden | `auto`, `sleep`, `medium`, `turbo`, gelezen uit `D0310C` (0, 17, 19, 18) |
| Snelheid | Vijf stappen; schrijven als `D0310C` = 1 tot 5 |
| Percentage teruglezen | Uit het werkelijke toerental `D0310D`, in elke stand |

Handmatige snelheden 1 tot 5 zijn bevestigd op de AC4221 en staan in de specificatie van de AC3220 ("5 niveaus"), maar zijn niet op een AC3220 waargenomen. Blijken ze niet te werken, dan vervalt de snelheidsregeling en blijven de voorkeuzestanden.

**Sensoren**

| Entiteit | Sleutel | Standaard |
|---|---|---|
| Fijnstof PM2.5 (µg/m³) | `D03221` | Aan |
| Allergenenindex (1 tot 12) | `D03120` | Aan |
| Temperatuur | `D03224` gedeeld door 10 | Aan |
| Luchtvochtigheid | `D03125` | Aan |
| Filter resterend (%) | `D0540E` gedeeld door `D05408` | Aan, diagnostisch |
| Filter reinigen over (uren) | `D0520D` | Aan, diagnostisch |
| Einde van de timer (tijdstip) | Uit `D03211` | Aan |
| Wifi-signaal, foutcode, laatste herstart, toerental | `rssi`, `D03240`, `Runtime`, `D0310D` | Uit, diagnostisch |

**Binaire sensoren:** filter vervangen (`D0540E` is 0), filter reinigen (`D0520D` is 0), storing (`D03240` is niet 0).

**Schakelaars:** kinderslot (`D03103`), pieptoon (`D03130`, 100 of 0), Auto+ (`D03180`), Allergie-slaap (`D03115`), sensoren in stand-by (`D03134`).

**Keuzelijsten:** displayhelderheid (`D03105`: uit 0, automatisch 101, laag 115, fel 123), lamp (`D03135`: uit 0, luchtkwaliteit 1, sfeerlicht 2), lichtscène (`D03137`: 1 tot 4), weergegeven index (`D0312A`: allergenen 0, PM2.5 1), timer (`D03110`: uit 0, 1 tot 12 uur als 2 tot 13).

**Pas na een geslaagde test op het apparaat:** knoppen voor het terugzetten van de filtertellers, de displayschakelaar (`D03112`, omgekeerd), en een lamp-entiteit voor de lichtring. Op een AC4221 met `@86` werd de lamp lokaal wel uitgezet maar niet aangezet; die melding gebruikte mogelijk tekstwaarden in plaats van getallen, dus het kan een meetfout zijn.

**Niet opslaan of tonen:** `Runtime`, `free_memory`, `StatusType`, `ConnectType` en de onbekende sleutels. `Runtime` verandert in elk bericht en zou de database vullen.

**Apparaatgegevens:** model uit `D01S05`, firmware uit `D01S12`, geen serienummer (`D01S0D` is een productcode per model), MAC-adres alleen uit DHCP-gegevens.

### 6.7 Home Assistant-kwaliteit, tests en distributie

De onderzoeksagent voor dit onderdeel meldt een aantal wijzigingen in Home Assistant uit 2026 die het plan raken. Ze zijn volgens die agent in de officiële bronnen gelezen; een tweede, onafhankelijke controle staat in bijlage B.

| Onderwerp | Voorstel |
|---|---|
| Gegevensstroom | `DataUpdateCoordinator` in push-modus; het interval dient alleen als bewaking na stilte |
| Opstarten | Niet wachten op een statusbericht; de richtlijn `test-before-setup` staat dat toe voor apparaten die vaak stil zijn |
| Opslag tijdens draaien | Getypeerde `entry.runtime_data` |
| Fouten bij commando's | Vertaalde `HomeAssistantError` |
| Entiteiten | `has_entity_name`, vertaalsleutels, `icons.json`, beschrijvingen met een functie die bepaalt of de sleutel bestaat |
| Diagnostiek | Download met afgeschermde identificatie, plus tellers: tijd sinds laatste bericht, controles, time-outs, overgeslagen berichten, herverbindingen |
| Vertalingen | Nederlands en Engels |
| Tests | Een nagebootste luchtreiniger op 127.0.0.1 die elk bekend firmwaretrekje kan vertonen; elk trekje wordt een regressietest |
| Controle bij elke wijziging | hassfest, HACS-validatie, ruff, mypy, tests tegen de minimale, de huidige en de bètaversie van Home Assistant |
| Distributie | Eerst als eigen repository via HACS; na de eerste stabiele versie aanmelden voor de standaardcatalogus |
| Domeinnaam | Vrij zijn onder meer `philips_pureprotect` en `philips_air_local`. De keuze is definitief. |

### 6.8 Wat we bewust niet doen

| Niet doen | Reden |
|---|---|
| Cloud als onderdeel van de werking | Geen extra gegevens, dezelfde stilte, en een geheim uit de app nodig. De statuslaag wordt wel zo opgezet dat een cloudroute later kan worden toegevoegd. |
| De alternatieve handshake (RSA met AES-GCM) uit kongo09 pull request #384 | De code kan in die pull request nooit worden uitgevoerd en is nergens op een apparaat aangetoond. De gewone handshake werkt op verwante modellen met `@86`. |
| Een statusbericht afdwingen met een schrijfopdracht, als standaard | Onbewezen op deze familie; kan een pieptoon of zichtbaar effect geven |
| ICMP-ping of een statusaanvraag als bereikbaarheidscontrole | De AC2220 negeert ping; een statusaanvraag wordt tijdens stilte niet beantwoord |

---

## 7. Eerst meten op jouw apparaat

Deze sessie duurt ongeveer een uur en beslist de open ontwerpkeuzes. Schakel eerst de bestaande integratie voor dit apparaat uit in Home Assistant, zodat er maar één client is.

### 7.1 Voorbereiding

Op een computer in hetzelfde netwerk, met Python 3.12 of nieuwer:

```bash
python3 -m venv venv && . venv/bin/activate
pip install aioairctrl==0.3.1
```

Start in een tweede venster een netwerkopname. De tweede voorwaarde vangt ook IP-fragmenten:

```bash
sudo tcpdump -n -i <interface> -w ac3220.pcap \
  'host <ip-luchtreiniger> and (udp port 5683 or (ip[6:2] & 0x3fff != 0))'
```

### 7.2 Metingen

| # | Vraag | Hoe |
|---|---|---|
| 1 | Welk MAC-voorvoegsel en welke DHCP-hostnaam heeft het apparaat? | Apparatenlijst van de router |
| 2 | Welke firmware en welke sleutels? | `aioairctrl -H <ip> status -J`. Blijft het hangen, verander dan iets op het apparaat; dat is zelf al een antwoord op vraag 3. |
| 3 | Antwoordt het direct op een abonnement, of pas bij een verandering? | `aioairctrl -H <ip> -D status-observe -J` starten terwijl het apparaat draait, en nog eens in stand-by. Noteer de tijd tot het eerste bericht. |
| 4 | Verloopt een abonnement na ongeveer 150 seconden? | Dezelfde opdracht 15 minuten laten lopen terwijl het apparaat draait. Stoppen de berichten terwijl de fijnstofwaarde op het display nog verandert? |
| 5 | Hoe lang is het stil in stand-by? | 30 minuten in stand-by, één keer met en één keer zonder "sensoren in stand-by" |
| 6 | Welke schrijfopdrachten werken lokaal? | Met `-I` voor gehele getallen, bijvoorbeeld `aioairctrl -H <ip> set -I D0310C=3`. Probeer: aan/uit, de vier standen, snelheden 1 tot 5, `D03105`, `D03135`, `D03137`, `D03115`, `D03134`, `D0312A`, `D03110`. Noteer per opdracht of de status de nieuwe waarde terugmeldt. |
| 7 | Stoort de Air+ app? | Open de app tijdens meting 4 en bedien het apparaat. Loopt de stroom door? |
| 8 | Antwoordt de info-aanvraag altijd? | Staat in de opname zodra de nieuwe protocollaag er is; met de huidige tools niet te testen |

Met tijdstempels per regel:

```bash
aioairctrl -H <ip> -D status-observe -J | while IFS= read -r regel; do
  printf '%s %s\n' "$(date +%T)" "$regel"
done | tee observe.log
```

### 7.3 Wat de uitkomsten beslissen

| Uitkomst | Gevolg voor het ontwerp |
|---|---|
| Abonnement verloopt niet | Vernieuwen kan uit of zeer spaarzaam |
| Abonnement verloopt wel | Vernieuwen met hetzelfde kenmerk testen; anders met een nieuw kenmerk |
| Schrijfopdracht met de huidige waarde geeft een volledig statusbericht | Dat is een bijwerkingsvrije manier om bij het opstarten de status op te halen |
| Lamp- en displayopdrachten worden genegeerd | Die entiteiten alleen-lezen maken of weglaten |
| Snelheden 1 tot 5 werken niet | Alleen voorkeuzestanden aanbieden |
| MAC-voorvoegsel buiten de bekende acht | Herkenning uitbreiden |

De eerste bouwstap kan ook een eigen meetprogramma zijn dat deze sessie automatiseert. Dat programma is dan meteen de basis van de protocollaag.

---

## 8. Voorgesteld stappenplan

| Stap | Inhoud | Resultaat |
|---|---|---|
| 0 | Meetsessie uit hoofdstuk 7 | Ontwerpkeuzes vastgelegd op basis van jouw apparaat |
| 1 | Protocol- en sessiepakket met nagebootst apparaat en tests | Betrouwbare verbinding, los van Home Assistant te testen |
| 2 | Minimale integratie: instellen met IP-adres, coordinator, ventilator en sensoren | Werkend in je eigen Home Assistant |
| 3 | Overige entiteiten, diagnostiek, DHCP-herkenning, herconfiguratie, vertalingen | Volledige functionaliteit |
| 4 | Duurtest van één tot twee weken op je eigen apparaat, met de diagnostiektellers | Aantoonbaar stabiel |
| 5 | Eerste release via HACS; kleine verbeteringen aanbieden bij de bestaande projecten | Publiek beschikbaar |

---

## 9. Open vragen en beslissingen

**Alleen op het apparaat te beantwoorden** (hoofdstuk 7):

- Firmwareversies en sleutelset van jouw exemplaar.
- Direct antwoord op een abonnement of pas bij verandering.
- Verloop van het abonnement en de juiste manier van vernieuwen.
- Welke schrijfopdrachten lokaal werken, in het bijzonder lamp, display en filterteller.
- MAC-voorvoegsel en hostnaam.
- Of de app en Home Assistant elkaar storen.

**Niet gevonden:**

- Welke servers het apparaat benadert, en dus welke je zou moeten blokkeren om updates tegen te houden. Alleen het volledig blokkeren van internet voor het apparaat is betrouwbaar, en ervaringen daarmee op deze generatie zijn schaars.
- Nederlandse gebruikerservaringen op Tweakers; die site was voor geen enkel hulpmiddel leesbaar.
- De betekenis van de sleutels `D03106`, `D0311F`, `D03136`, `D0313B`, `D03182`, `D03R81`, `D05102` en de `D011xx`-reeks.

**Beslissingen voor jou:**

| Beslissing | Opties | Mijn voorkeur |
|---|---|---|
| Domeinnaam | `philips_pureprotect`, `philips_air_local`, andere | `philips_pureprotect` |
| Reikwijdte | Alleen de 3200-serie, of ook de verwante 2200- en 4200-serie | Beginnen met de 3200-serie; de modeltabel zo opzetten dat de andere erbij kunnen |
| Minimale Home Assistant-versie | De versie die je nu draait of nieuwer | Afhankelijk van jouw installatie |

---

## Bijlage A. Datapunten van de AC3220

Bronnen: de statusdump van een AC3220/10 (november 2024, firmware `0.1.9`), een dump van een AC3210/12 (2026, firmware `0.2.3`), de openHAB-binding en waarnemingen op de AC4221/11. Kolom "Schrijven": **ja** is over lokaal CoAP bevestigd op een verwant model; **?** wordt door andere projecten geschreven maar is op deze familie niet bevestigd.

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

| Sleutel | Betekenis | Waarden | Schrijven |
|---|---|---|---|
| `D03102` | Aan/uit | 1 aan, 0 uit | ja |
| `D03103` | Kinderslot | 1, 0 | ja |
| `D03105` | Displayhelderheid | 0 uit, 101 automatisch, 115 laag, 123 fel | deels: 0 bevestigd |
| `D0310C` | Stand | 0 auto, 1 tot 5 handmatig, 17 slaap, 18 turbo, 19 medium; -16 als het apparaat uit staat | ja |
| `D0310D` | Werkelijk toerental | 0, 1 tot 4, 18 is het hoogste | nee |
| `D03110` | Timer | 0 uit, 2 tot 13 is 1 tot 12 uur | ? |
| `D03211` | Resterende timertijd in minuten | 0 tot 720 | nee |
| `D03112` | Display aan/uit, omgekeerd; alleen op nieuwere firmware | 0 aan, 1 uit | ? |
| `D03115` | Allergie-slaap | 1, 0 | ? |
| `D03120` | Allergenenindex | 1 tot 12 | nee |
| `D03221` | Fijnstof PM2.5 in µg/m³ | | nee |
| `D03224` | Temperatuur maal 10 | 212 is 21,2 °C | nee |
| `D03125` | Luchtvochtigheid in % | | nee |
| `D0312A` | Weergegeven index | 0 allergenen, 1 PM2.5 | ? |
| `D0312C` | Drempel voor meldingen in de app | 1, 4, 7, 10 | ? |
| `D03130` | Pieptoon | 100 aan, 0 uit | ? |
| `D03134` | Sensoren actief in stand-by | 1, 0 | ? |
| `D03135` | Lampfunctie | 0 uit, 1 luchtkwaliteit, 2 sfeerlicht | deels: 0 bevestigd |
| `D03137` | Lichtscène; alleen op nieuwere firmware | 1 tot 4 | ? |
| `D03180` | Auto+ | 1, 0 | ? |
| `D03240` | Foutcode | 0 is geen fout | nee |

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

Na het onderzoek zijn de dragende beweringen opnieuw tegen de bronnen gelegd.

**Zelf nagekeken in de broncode, alle bevestigd:** het ontbreken van time-outs in aioairctrl; het hergebruik van het oude versleutelde bericht in philips-airctrl; de altijd-beschikbare entiteiten, de opgeslagen status en de bewaking van 180 seconden in kongo09; de vernieuwing met deadline van 10 seconden en het ontbreken van de afdwingtruc voor de AC3220 in tinkerologie; de verkeerde sleutel `D03-42` in beide.

**Veertien beweringen uit issue-trackers:** tien bevestigd, vier deels, geen weerlegd. De belangrijkste correcties:

- Het gedrag "alleen bij verandering" is voor de verwante 2200- en 4200-serie afgeleid uit time-outstatistieken; de beslissende proef (abonneren, een waarde wijzigen, een bericht zien) staat in geen van die issues. De directe meting komt van de ESP32-logger op een AC2220/10.
- Het verlopen van een abonnement na 150 seconden rust op twee sessies op één AC4220/12.
- "Tekstwaarden worden genegeerd" is te breed: de tekst "0" voor uitzetten werkte wel. De regel om altijd gehele getallen te sturen blijft staan.
- In geen enkele gelezen bron staat een AC3210, AC3220 of AC3221 op `@86` met gemeten gedrag.

**Elf beweringen uit fora:** zes bevestigd, vijf deels, geen weerlegd. De belangrijkste correcties:

- De melding dat een Nederlandse AC3220/10 "prima werkt" (januari 2026) is van iemand die het apparaat net had gekocht, zonder versienummers.
- Een Australische AC3220/10 op `0.2.3` met `@86` gaf niets terug aan aioairctrl (april 2026); de oorzaak is nooit opgehelderd. Op stille firmware is dat het verwachte gedrag van die opdracht bij een apparaat in rust.
- De wachttijden van 30, 60 en 120 seconden zijn alleen van ioBroker; openHAB heeft geen oplopende wachttijd.

**Bevindingen over Home Assistant in 2026**, zoals gemeld door de onderzoeksagent en door een tweede agent gecontroleerd: zie de uitkomst in [`docs/research/13-review.md`](research/13-review.md).

# Meetprogramma

Dit programma meet hoe jouw luchtreiniger zich op het lokale netwerk gedraagt. De uitkomsten beslissen de open ontwerpkeuzes uit [het onderzoeksrapport](../../docs/onderzoek.md), hoofdstuk 7.

Het programma is gedraaid tegen een echte AC3220/10 met firmware 0.2.3; de uitkomsten staan in [het meetlogboek](../../docs/metingen.md). Wat daarnaast geautomatiseerd wordt getest, staat onder [Wat is getest](#wat-is-getest).

## Wat het doet

- Het praat rechtstreeks met de luchtreiniger over UDP-poort 5683, zonder cloud en zonder account.
- Het stuurt elk verzoek precies één keer en herhaalt niets. Een verloren pakketje is dan zichtbaar als een ontbrekend antwoord.
- Het legt elk verzonden en ontvangen datagram vast met een tijdstempel.
- De meeste opdrachten lezen alleen. De opdrachten `set`, `write-matrix` en de stimulus `schrijf` veranderen instellingen van het apparaat.

## Installeren

Je hebt Python 3.11 of nieuwer nodig, op een computer in hetzelfde netwerk als de luchtreiniger.

```bash
cd tools/probe
python3 -m venv venv
. venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Vooraf

1. Schakel in Home Assistant de bestaande integratie voor dit apparaat uit. Twee clients vanaf hetzelfde adres kunnen elkaars berichten afnemen.
2. Sluit de Air+ app geforceerd af op alle telefoons. De app praat zelf ook lokaal met het apparaat.
3. Zoek het IP-adres van de luchtreiniger op in je router en geef het daar een vaste reservering.
4. Staat er een firewall op je computer, sta dan inkomend UDP-verkeer voor Python toe als daarom wordt gevraagd.

## Eerste meting

```bash
python -m pureprotect_probe quick --host <ip-adres>
```

Dit duurt ongeveer twee minuten. Komt er na tien seconden geen statusbericht, dan vraagt het programma je op de standknop van de luchtreiniger te drukken.

Aan het eind staat er een samenvatting op het scherm. Dezelfde tekst staat in `metingen/<datum>-quick/samenvatting.txt`. **Stuur mij die samenvatting**; daarmee weet ik de firmware, de sleutels en of het apparaat direct of pas bij een verandering antwoordt.

## Overige metingen

Doe ze in deze volgorde. Elke meting schrijft een eigen map onder `metingen/`.

| # | Opdracht | Duur | Wat het beslist |
|---|---|---|---|
| 1 | `quick` | 2 min | Firmware, sleutels, welke controles antwoorden, hoe het eerste statusbericht komt |
| 2 | `write-matrix` | 8 min | Welke schrijfopdrachten werken, ook gecombineerd, en hoe snel ze worden teruggemeld |
| 3 | `lapse` | 20 min | Of een abonnement zonder vernieuwing blijft leveren |
| 4 | `refresh` | 5 min | Of opnieuw abonneren wordt beantwoord: met hetzelfde kenmerk, en met een nieuw kenmerk vanaf dezelfde poort |
| 5 | `liveness` | 2 uur | Welke bereikbaarheidscontrole blijft antwoorden terwijl het apparaat stil is |
| 6 | `second-client` | 2 min | Of het apparaat één of meer abonnees per adres bedient, en of de teller gedeeld is |
| 7 | `deregister` | 2 min | Of het apparaat afmelden en een reset respecteert |
| 8 | `power-cycle` | 5 min | Hoe lang opstarten duurt en of een abonnement een stroomonderbreking overleeft |
| 9 | `app` | 4 min | Of de Air+ app en deze client elkaar storen |
| 10 | `discover` | 10 s | Of het apparaat via broadcast of multicast te vinden is |

Aanwijzingen per meting:

- **`write-matrix`** verandert stand, snelheid, licht en instellingen en zet ze daarna terug. Het apparaat kan bij elke opdracht piepen, het gaat een paar keer uit en aan, de ventilator draait kort op de hoogste stand en er wordt kort een timer gezet. Doe dit dus niet 's nachts. Het programma vraagt eerst om bevestiging. Met `--groepen lamp,snelheden` beperk je de meting tot die groepen. Aan het eind schrijft het programma elke aangeraakte instelling terug, ook als je met Ctrl-C afbreekt, en meldt het wat het niet kon bevestigen.
  - De groep `licht` schrijft meerdere sleutels in één opdracht, zoals de Air+ app dat doet.
  - De groep `combinatie` zet het apparaat aan samen met een stand, en stuurt een instelling direct achter het aanzetten aan.
  - De groep `filter` zet de twee filtertellers één uur lager en weer terug. Neemt het apparaat het terugzetten niet aan, dan loopt een teller één uur achter of staat hij weer op vol.
- **`refresh`** draai je met het apparaat aan. Elke ronde heeft drie even lange vensters: één zonder aanvraag, één na een aanvraag met hetzelfde kenmerk en één na een aanvraag met een nieuw kenmerk. Een apparaat dat aan staat stuurt ook uit zichzelf berichten; het venster zonder aanvraag laat zien hoe vaak. Een antwoord op een aanvraag herken je doordat het de al bekende status herhaalt.
- **`lapse`** draai je twee keer: één keer terwijl het apparaat draait, en één keer in stand-by. Draai het daarna eventueel met `--sync-interval 30` om te zien of een sync het abonnement in leven houdt.
- **`liveness`** draai je met het apparaat in stand-by, bij voorkeur één keer met en één keer zonder "sensoren in stand-by". Met `--duur 1800` kort je de meting in tot een halfuur.
- **`second-client`** test twee clients vanaf dezelfde computer. Voor twee verschillende computers start je op elk `observe --duur 300` en druk je een paar keer op de standknop.
- **`power-cycle`** en **`app`** vragen je onderweg iets te doen en wachten op Enter.

Alle opties van een opdracht zie je met `python -m pureprotect_probe <opdracht> --help`.

### Uitkomsten van een schrijfopdracht

| Uitkomst | Betekenis |
|---|---|
| teruggemeld | Een later statusbericht toont de nieuwe waarde: de opdracht werkt |
| GENEGEERD | Het apparaat antwoordde "success", maar een later statusbericht toont nog de oude waarde |
| onbekend | Het apparaat antwoordde "success", maar er kwam geen statusbericht. Kijk op het apparaat zelf of er iets veranderde, en noteer dat erbij. |
| de waarde gold al | Er is niets veranderd; het programma meldt of er toch een statusbericht kwam |
| DEELS uitgevoerd | Een opdracht met meerdere sleutels: een latere status toont een deel van de waarden wel en een deel niet |
| geweigerd | Het apparaat antwoordde "failed" |

### Als het programma vraagt of je hebt gedrukt

Komt er na een verzoek om op de standknop te drukken geen statusbericht, dan vraagt het programma of je echt hebt gedrukt. Antwoord eerlijk: bij "nee" probeert het programma het nog één keer, en alleen bij "ja" telt "geen bericht" als uitkomst.

## Rondgang door de app

Hiermee koppel je elke instelling in de Air+ app aan een sleutel, ook de instellingen waarvan de sleutel nog onbekend is.

```bash
python -m pureprotect_probe watch --host <ip>
```

Zet het apparaat aan, open de Air+ app en wijzig telkens één instelling, met een paar seconden ertussen. Elke wijziging verschijnt direct op je scherm, bijvoorbeeld `D03135: 1 -> 2`. Stop met Ctrl-C; de samenvatting bevat alle gewijzigde sleutels en een tijdlijn. Noteer erbij in welke volgorde je de instellingen hebt gewijzigd.

De meetwaarden die uit zichzelf veranderen (fijnstof, allergenenindex, temperatuur, vochtigheid) worden weggelaten; met `--alles` zie je ze wel.

## Een verandering uitlokken

Het apparaat stuurt mogelijk alleen een statusbericht als er iets verandert. Veel metingen hebben daarom op vaste momenten een verandering nodig. Er zijn twee manieren:

| Optie | Wat er gebeurt | Wanneer |
|---|---|---|
| `--stimulus knop` (standaard) | Het programma vraagt je op de standknop te drukken | Zuiverste meting: er gaat geen extra verkeer naar het apparaat |
| `--stimulus schrijf` | Het programma zet het kinderslot aan en weer uit | Als je er niet bij wilt blijven. De schrijfopdracht is zelf verkeer en kan de uitkomst van `lapse` beïnvloeden. |

Met `--stimulus schrijf:D03130=0,100` kies je een andere sleutel en twee waarden.

## Losse opdrachten

```bash
python -m pureprotect_probe status --host <ip>             # één volledige status tonen en bewaren
python -m pureprotect_probe observe --host <ip> --duur 900 # meeluisteren
python -m pureprotect_probe info --host <ip> --aantal 20   # de info-aanvraag herhalen; ook: sync, ping
python -m pureprotect_probe set --host <ip> D0310C=3       # één schrijfopdracht, alleen gehele getallen
```

## Resultaten

| Bestand | Inhoud |
|---|---|
| `samenvatting.txt` | De conclusies in gewone taal |
| `events.jsonl` | Elk datagram en elke waarneming, één JSON-regel per gebeurtenis |
| `status.json` | De laatst ontvangen volledige status |

Apparaat-id, product-id en de naam van het apparaat worden vervangen door een korte code. Gelijke waarden krijgen dezelfde code, zodat vergelijken mogelijk blijft. Met `--toon-ids` staan ze er onverkort in. IP-adressen uit je thuisnetwerk staan wel in de bestanden.

Wil je naast het programma een netwerkopname maken, dan vangt deze opdracht ook fragmenten en ARP-verkeer:

```bash
sudo tcpdump -n -i <interface> -w ac3220.pcap 'host <ip> or arp host <ip>'
```

## Wat is getest

- De versleuteling ontcijfert een statusbericht dat van een echte AC0850/11 is vastgelegd (`tests/vectors/`).
- De CoAP-codering is getest tegen met de hand uitgewerkte bytereeksen, en komt in 800 vergelijkingen byte voor byte overeen met de library aiocoap.
- De versleuteling komt in beide richtingen overeen met die van aioairctrl, de bestaande client voor deze apparaten.
- De bestaande client aioairctrl kan de nagebootste luchtreiniger uitlezen, volgen en besturen. De nabootsing spreekt het protocol dus zoals een bewezen client het verwacht.
- Dit programma is ook gedraaid tegen een server die met aiocoap is gebouwd, een onafhankelijke CoAP-implementatie.
- Elke meting is getest tegen een nagebootste luchtreiniger (`tests/fake_purifier.py`) die de bekende firmwaretrekjes kan vertonen: alleen melden bij verandering, verlopende abonnementen, één abonnee per adres, beschadigde berichten, misvormde sync-antwoorden en alleen-lezen sleutels.

Tests draaien:

```bash
pip install -r requirements-dev.txt
python -m pytest tests
```

Zonder aiocoap en aioairctrl worden de twee vergelijkende tests overgeslagen; `pip install pytest` is dan genoeg.

Wat deze tests niet kunnen aantonen: hoe een echte luchtreiniger zich gedraagt. Dat staat in [het meetlogboek](../../docs/metingen.md).

## Opbouw

| Bestand | Rol |
|---|---|
| `pureprotect_probe/coap.py` | CoAP-berichten coderen en decoderen |
| `pureprotect_probe/crypto.py` | De versleutelde envelop |
| `pureprotect_probe/endpoint.py` | Eén UDP-socket; koppelt antwoorden aan verzoeken; legt alles vast |
| `pureprotect_probe/device.py` | De vier adressen van het apparaat: info, sync, status, control |
| `pureprotect_probe/scenarios.py` | De metingen |
| `pureprotect_probe/__main__.py` | De opdrachtregel |

De eerste vier bestanden zijn de kern van de latere protocollaag van de integratie.

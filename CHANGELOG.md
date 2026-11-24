# Wijzigingen

Elke versie hieronder wordt een release op GitHub zodra ze in `main` staat, en HACS biedt haar aan als update.

## Niet uitgebracht

- Voorbeeldadressen en onderzoeksnotities zonder echte netwerk- of apparaatgegevens, en GitHub Actions vastgezet op een vaste versie.

## 0.2.0

- **Automatisch vinden.** Bij het toevoegen kan Home Assistant de luchtreiniger in je netwerk zoeken. Een nieuwe luchtreiniger wordt via DHCP herkend en aangeboden. Krijgt je luchtreiniger een ander adres, dan volgt de integratie dat: via DHCP, of door hem zelf te zoeken als hij een minuut of vijf niet antwoordt op het oude adres, of als daar een ander apparaat antwoordt. Gezocht en aangeboden wordt alleen de AC3220; een ander model kun je nog met zijn adres toevoegen, maar dat is niet getest.
- **Stand:** een keuzelijst met alle standen van het apparaat, op de apparaatpagina.
- **Knoppen** "Filter gereinigd" en "Nieuw filter geplaatst".
- **Licht** werkt zoals in de Air+ app; helderheid heeft een keuze "uit".
- **Aanzetten in een stand** gaat in één opdracht.
- **Luchtkwaliteit:** een sensor met de vier niveaus van de gekleurde ring (goed, redelijk, slecht, zeer slecht), volgens de grenzen in de handleiding.
- **Blauwdrukken** voor wat de Air+ app alleen via de cloud doet: een weekschema, een melding bij slechte lucht en een filterherinnering.
- **Sensoren** "Cloudverbinding" en "Laatst opgestart", om te zien of de luchtreiniger zonder cloud goed blijft werken.
- **Tests op GitHub:** elke pull request draait alle tests, in Home Assistant 2026.11 en zonder.
- **Uiterlijk:** een eigen pictogram, pictogrammen die met de toestand meewisselen, en een kant-en-klare dashboardkaart in `docs/dashboard.yaml`.

## 0.1.0

- Eerste versie: lokaal bedienen via het IP-adres, alle sensoren, schakelaars en keuzelijsten, en diagnostiek.

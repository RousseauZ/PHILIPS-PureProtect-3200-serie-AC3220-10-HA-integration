# Wijzigingen

Elke versie hieronder wordt een release op GitHub zodra ze in `main` staat, en HACS biedt haar aan als update.

## 0.2.0

- **Automatisch vinden.** Bij het toevoegen kan Home Assistant de luchtreiniger in je netwerk zoeken. Een nieuwe luchtreiniger wordt via DHCP herkend en aangeboden. Krijgt je luchtreiniger een ander adres, dan volgt de integratie dat: via DHCP, of door hem zelf te zoeken als hij een minuut of vijf niet antwoordt op het oude adres, of als daar een ander apparaat antwoordt.
- **Stand:** een keuzelijst met alle standen van het apparaat, op de apparaatpagina.
- **Knoppen** "Filter gereinigd" en "Nieuw filter geplaatst".
- **Licht** werkt zoals in de Air+ app; helderheid heeft een keuze "uit".
- **Aanzetten in een stand** gaat in één opdracht.
- **Sensoren** "Cloudverbinding" en "Laatst opgestart", om te zien of de luchtreiniger zonder cloud goed blijft werken.
- **Uiterlijk:** een eigen pictogram, pictogrammen die met de toestand meewisselen, en een kant-en-klare dashboardkaart in `docs/dashboard.yaml`.

## 0.1.0

- Eerste versie: lokaal bedienen via het IP-adres, alle sensoren, schakelaars en keuzelijsten, en diagnostiek.

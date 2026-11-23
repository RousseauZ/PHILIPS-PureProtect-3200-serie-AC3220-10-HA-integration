# Onderzoeksnotities

Dit zijn de ruwe notities (Engels) waarop [`../onderzoek.md`](../onderzoek.md) is gebaseerd. Elke notitie is door een aparte onderzoeksagent geschreven op 22 november 2026 en bevat bronverwijzingen per bewering.

Lees ze als naslag, niet als eindconclusie:

- Niets is op een echte AC3220 getest.
- Notities 11, 12 en 13a tot 13c zijn controles achteraf. Waar ze de eerdere notities tegenspreken, gelden de controles.
- Notities 13a tot 13c beoordelen de eerste versie van het rapport. De correcties zijn daarna verwerkt, dus de aangehaalde zinnen staan er niet meer letterlijk in.
- GitHub-issues konden alleen via een samenvattend hulpmiddel worden gelezen. Citaten daaruit zijn "woordelijk zoals doorgegeven", niet zelf van de pagina gekopieerd.
- Verwijzingen als `scratchpad/src/...` wijzen naar tijdelijke kopieën van openbare repositories die niet in deze repository staan. De naam van de map is `<eigenaar>_<repository>` op GitHub.

| Notitie | Onderwerp |
|---|---|
| [01](01-coap-protocol.md) | Het lokale protocol: adressen, handshake, versleuteling, abonnement, time-outs per library |
| [02](02-kongo09-integration.md) | Codereview van `kongo09/philips-airpurifier-coap`, met de entiteiten voor de AC3220 |
| [03](03-tinkerologie-integration.md) | Codereview van `tinkerologie/ha-philips-airpurifier` en de library `philips-airctrl` |
| [04](04-github-issues.md) | Storingsmeldingen en oorzaken uit de issue-trackers |
| [05](05-forums.md) | Ervaringen op fora (Home Assistant, Homey, openHAB, ioBroker) |
| [06](06-cloud-path.md) | De cloudroute via de Air+ app: twee backends, aanmelden, MQTT |
| [07](07-hardware-discovery.md) | Hardware, firmware, MAC-voorvoegsels, ontdekking in het netwerk |
| [08](08-other-ecosystems.md) | Hoe openHAB, ioBroker, Homey en anderen betrouwbaarheid aanpakken; voorgesteld sessie-algoritme |
| [09](09-ac3220-capabilities.md) | Mogelijkheden en volledige datapunttabel van de AC3220; voorgesteld entiteitenmodel |
| [10](10-ha-best-practices.md) | Richtlijnen voor een Home Assistant-integratie eind 2026; opzet, tests, distributie |
| [11](11-verify-firmware-claims.md) | Controle van veertien beweringen over firmwaregedrag |
| [12](12-verify-forum-claims.md) | Controle van elf beweringen uit fora en over de cloud |
| [13a](13a-review-factcheck.md) | Controle van het rapport op feiten, tegen de notities en de broncode |
| [13b](13b-review-design.md) | Aanval op het voorgestelde ontwerp en het meetplan, met een tabel per storingsscenario |
| [13c](13c-review-ha-claims.md) | Controle van vijftien beweringen over Home Assistant in 2026 tegen de officiële bronnen |

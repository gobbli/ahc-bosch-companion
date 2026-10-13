# AHC Bosch Companion — Architektur und Sicherheitsregeln

**Entwicklungsversion 0.1.0-dev1. Kein produktiver Heizungsregler.**

## Motivation

Die Integration soll den originalen [Advanced Heating Control](https://github.com/panhans/HomeAssistant)
Blueprint (zum Projektstart AHC 5.5.9) nicht verändern. Bosch Room Thermostat II
(BTH-RM) ist die lokale Bedieneinheit und Bosch Radiator Thermostat II (BTH-RA)
bilden die Stellglieder. Beide werden über Zigbee2MQTT eingebunden.

## Etappe 1 – implementiert: ausschließlich lesende Diagnose

- UI-Setup wählt bereits vorhandene Home-Assistant-Entitäten:
  `climate` für das Raumthermostat und `select` für `operating_mode`.
- Zwei neue Sensoren spiegeln den aktuellen Bosch-Modus
  (`schedule`, `manual`, `pause`) und den Sollwert des Raum-`climate`.
- Echtzeit-Aktualisierung über Home Assistants State-Change-Events.
- Keine MQTT-Veröffentlichungen, keine `climate.set_*`-Befehle.
- Original-AHC und die vorhandene Heizungsautomation werden nicht verändert.

Dies ist **keine** voll funktionsfähige HACS-Beta. HACS-Struktur ist vorbereitet,
die Home-Assistant-Laufzeitprüfung und HACS-Validierung stehen noch aus.

## Geplanter Regelpfad (noch nicht implementiert)

```
Zigbee2MQTT -> Bosch-Zustandsautomat -> AHC/Companion-Vermittlung
                                    -> genau eine Befehlsinstanz -> beide TRVs
```

Entscheidend: Eine virtuelle Climate-Entität allein genügt nicht als
Nachweis sicherer Interoperabilität mit AHC. AHC nutzt Scheduler, Custom Actions,
Szenen, Frostschutz, Fensterkontakt und andere Eingriffe, die man einzeln prüfen
muss. Die Vermittlung darf nicht versuchen, eine vermeintliche AHC-Absicht aus
einer einzelnen Solltemperaturänderung zu erraten.

### Gewünschte Zustandsregeln

1. Bosch `schedule`: AHC steuert nach Zeitplan.
2. Physische Änderung in `schedule` mit `setpoint_change_source=manual`:
   temporäre Übersteuerung bis zum **nächsten tatsächlich relevanten AHC-Scheduler-Ereignis**.
   `setpoint_change_source` bleibt möglicherweise `manual`; nur eine
   echte Änderung der Solltemperatur ist ein neuer Eingriff.
3. Bosch `manual`: explizite manuelle Solltemperatur, bis Moduswechsel.
4. Bosch `pause`: TRVs pausieren; Wiedereintritt in AHC muss deterministisch
   sein und weitere AHC-Befehle dürfen Pause nicht versehentlich aufheben.
5. AHC-Sollwert zum Bosch-Raumdisplay zurücksynchronisieren, ohne Feedback-Loop.
6. Remote-Temperatur an beide TRVs mindestens alle 10 Minuten liefern;
   innerhalb des späteren Systems genau einen zuständigen Sender verwenden.
7. Persistenz/Restart, Geräteverfügbarkeit und Fenster-/Frostschutzvorrang
   müssen mit realen Bosch-Geräten validiert sein, bevor Stellbefehle aktiviert
   werden.

## Veröffentlichung

Der Companion enthält ausschließlich neu geschriebenen eigenen Code und
übernimmt keine AHC-Blueprint-Quelldatei. HACS erwartet die Custom-Integration
unter `custom_components/ahc_bosch_companion/`, ein Manifest und Repo-Metadaten.
Bis zur fertigen Freigabe bleiben die Änderungen auf einem Entwicklungsbranch.

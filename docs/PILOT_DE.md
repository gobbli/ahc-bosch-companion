# AHC Bosch Companion – beaufsichtigter erster Test (0.1.0b1)

**Wichtig:** Noch keine unbeaufsichtigte Heizungssteuerung! Das Plugin hat bislang keine echten Hardwaretests bestanden. **Der Ausgangsschalter ist bei jedem HA-Neustart AUS.** Ein AUS schaltet die realen Heizkörper NICHT ab, sondern verhindert neue Companion-Befehle.

## A. Vorbereitung

1. **Vollständiges HA-Backup** erstellen.
2. Beide Bosch BTH-RA und den Bosch BTH-RM in Zigbee2MQTT prüfen.
3. Original-AHC **5.5.9** und dessen Uptime-Integration behalten.
4. Die funktionierende Automation für **remote_temperature alle 10 Minuten** auf beiden BTH-RAs **aktiv lassen**; AHC-Kalibrierung deaktivieren.
5. Die direkte MQTT-Sollwert-Synchronisation Raumthermostat → Heizkörper für den aktiven Test deaktivieren. Zwei konkurrierende AHC-/Setpoint-Automationen dürfen nie dieselben Heizkörper steuern.
6. In diesem Piloten nur **einen** HA-`schedule`-Helper für AHC verwenden, z. B. `schedule.ahc_hobbyraum`.

## B. HACS und Einrichtungsdialog

Nach der Veröffentlichung im Standardbranch in HACS → Benutzerdefinierte Repositories:
URL `https://github.com/gobbli/ahc-bosch-companion`, Typ **Integration**.
Herunterladen, HA neu starten, anschließend unter Einstellungen → Geräte und Dienste → Integration hinzufügen den **AHC Bosch Companion** auswählen.

Konfiguration (Entity-IDs bitte in Entwicklerwerkzeuge → Zustände bestätigen):

| Feld | Voraussichtlicher Wert |
|---|---|
| Bosch Raumthermostat (Climate) | `climate.raumthermostat_hobbyraum` |
| Raum-Betriebsart (Select) | `select.raumthermostat_hobbyraum_operating_mode` |
| Raumtemperatur | `sensor.raumthermostat_hobbyraum_local_temperature` |
| Raum-MQTT-Topic | `zigbee2mqtt/Raumthermostat Hobbyraum` |
| Zeitplan | `schedule.ahc_hobbyraum` |
| Heizkörper (Climates) | `climate.thermostat_hobbyraum_1`, `climate.thermostat_hobbyraum_2` |
| Heizkörper-Betriebsarten (Selects) | Jeweils die `select.*operating_mode`-Entität derselben BTH-RA-Hardware **in der gleichen Reihenfolge** |
| AHC-Automation | Optional bei Ersteinrichtung; später unter **Konfigurieren** zuordnen |

Der Companion überprüft, dass jeder Heizkörper-Climate-Entity ein Select desselben HA-Geräts mit Optionen `manual` und `pause` zugeordnet ist. Stimmen die Paare nicht, wird die Einrichtung abgelehnt.

## C. Original-AHC unverändert konfigurieren

1. Companion erstellt eine **virtuelle Climate-Entität** (genaue ID in HA ablesen).
2. Erstelle deine AHC-Automation aus dem Original-Blueprint **AHC 5.5.9**.
3. Unter **Thermostats / Climates** in AHC **NUR** die neue virtuelle Climate eintragen. Die beiden realen BTH-RA dürfen hier NICHT ausgewählt sein.
4. Als AHC-Raumtemperatur den Bosch-Raumsensor wählen, **Calibration OFF**.
5. Den in Companion konfigurierten **einen** Zeitplan verwenden. Komfort-/Eco-HVAC-Modus jeweils `heat` einstellen. Keine AHC-Physical-/UI-Setpoint-Synchronisation.
6. In den Einstellungen des Companion auf **Konfigurieren** klicken und die soeben angelegte AHC-Automation auswählen. Der Companion lädt erneut; der Ausgangsschalter bleibt AUS.

## D. Zuerst Trockenlauf – keine Heizkörperbefehle

Der Schalter **Radiator output enabled** bleibt **AUS**.

- Der AHC-Sollwert muss an der virtuellen Climate erscheinen.
- Bei Bosch `manual` und einer veränderten Wunschtemperatur muss `bosch_override_mode` auf `manual` stehen.
- Bei Bosch `schedule` und physischer Sollwertänderung muss `bosch_override_mode` auf `temporary` stehen; nach einem HA-Schedule-Wechsel on/off wieder `schedule`.
- Bei `pause` muss `bosch_desired_mode` den Wert `pause` anzeigen.
- `ahc_event_received` muss `true` sein; `ahc_protection` bei Fenster-/Frostschutz beachten.
- Wenn das nicht passt, **nicht freischalten**. Fehler/Attribute dokumentieren.

## E. Kurzer beaufsichtigter Hardwaretest

**Nur bei erfolgreichem D** und ausgeschalteten konkurrierenden Sollwert-Automationen:

1. HA/Zigbee2MQTT-Verbindung und beide BTH-RA prüfen.
2. Companion-Schalter **Radiator output enabled** manuell auf **EIN** setzen.
3. Bosch `schedule`: Beide BTH-RA müssen auf `manual` stehen und den AHC-Sollwert erhalten.
4. Bosch `manual`: Am Raumthermostat andere Temperatur einstellen, beide TRVs prüfen.
5. Bosch `pause`: Beide TRVs müssen den Bosch-Modus `pause` annehmen.
6. Wieder `schedule`: Beide TRVs müssen AHC-Solltemperatur im Modus `manual` annehmen.
7. Im `schedule` einmal am Raumthermostat verstellen und den nächsten HA-Schedule-Schaltpunkt testen.

**Jedes Mal reale Zigbee2MQTT-/HA-Gerätezustände nachprüfen.** Service-Aufrufe bedeuten nicht, dass Zigbee-Befehle tatsächlich angekommen sind.

## F. Sofortiger Rückweg bei jedem unerwarteten Verhalten

1. Companion-Schalter AUS (sendet selbst **keinen** Stopp-Befehl!).
2. Neue AHC-Proxy-Automation deaktivieren.
3. Beide Heizkörper über Zigbee2MQTT/HA manuell auf `manual` und einen sicheren Sollwert (z. B. 18–20 °C) stellen. Zustand verifizieren.
4. Wenn vorhanden: bewährte bisherige Heizungsregelung für reale TRVs **anstelle** der Proxy-Automation wieder aktivieren. Externe Isttemperaturversorgung bleibt bestehen.
5. Vor unbeaufsichtigtem Einsatz zuerst Ergebnisse dieses Pilots auswerten und offene Zuverlässigkeitsprobleme beheben.

## Grenzen der ersten Version

Kein Display-Sollwert-Sync; keine mehreren Zeitpläne oder nahtlosen Zeitblöcke; kein automatischer Neustart der Aktorsteuerung nach HA-Reboot; noch keine reale Gerätequittierungslogik; Zigbee-/MQTT-Unterbrechung kann verzögerte Aktorreaktionen verursachen. **Nicht für Nächte/Urlaub unbeaufsichtigt verwenden.**

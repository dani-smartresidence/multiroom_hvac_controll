# Room Climate Portal

Fiecare cameră primește un cod QR. Scanat, el deschide o pagină pe telefon (în română, cu engleză la o
atingere, luminoasă sau întunecată după telefon) unde ocupantul vede temperatura live, schimbă ținta în
limitele permise și vede evenimentele următoare ale camerei, cu ora la care începe preîncălzirea pentru
fiecare. Totul vine din Home Assistant; add-on-ul nu ține un program propriu.

Pagina de administrare se deschide din bara laterală HA, la **Încălzire camere**, și are trei tab-uri:
**Camere** (coduri QR, PIN-uri, termostate), **Instalație** (centrale, circuite, estimări, comanda
încălzirii) și **Jurnal încălzire** (rulări măsurate, estimat față de realitate).

## 1. Pregătește Home Assistant (o dată pentru fiecare cameră)

| Ce | Cum |
| --- | --- |
| Zonă (Area) | O zonă pentru fiecare cameră (Setări → Zone). Pune pe ea eticheta **`qr_room`**. |
| Termostat | Entitatea `climate` a camerei, asociată acelei zone (direct sau prin dispozitivul ei). |
| Calendar | Un calendar pentru fiecare cameră în zonă, de exemplu un Local Calendar `calendar.camera_204`. |
| Preîncălzire | Se setează din administrare: **Preîncălzire: toate camerele** (120 min implicit) și, pe cameră, câmpul „Pornește cu … min înainte de evenimente” din coloana **Calendar și preîncălzire**. Helper-ele de preîncălzire din HA nu mai sunt citite. |
| Umiditate (opțional) | Orice senzor de umiditate din zonă apare automat. |

Descrierea unui eveniment poate avea o linie opțională:

```
target: 22          # temperatura țintă a evenimentului (altfel opțiunea „Ținta implicită a evenimentelor”)
```

Calendarul nu stabilește preîncălzirea: o linie `precondition: 60` într-un eveniment e ignorată. Schimb-o
din pagina de administrare.

## 2. Configurează add-on-ul

- **public_url**: adresa HA fără cale, de exemplu `https://ha.voxdomini.ro`.
- **base_path**: `/camera` (implicit). Codurile QR duc la `https://ha.voxdomini.ro/camera/<cod>`.
- **trust_proxy_headers**: pornește-l când în față e un reverse proxy (vezi secțiunea 3), ca limitările
  de modificări și blocările de PIN să vadă adresa reală a fiecărui telefon.
- **min_temp / max_temp / temp_step**: limitele pentru oaspeți (se pot schimba pe cameră în `rooms.yaml`).
- **default_language**: `ro` sau `en`.
- **pin_remember_hours / pin_max_attempts / pin_lockout_minutes**: comportamentul PIN-ului (PIN-urile se setează din administrare).
- **publish_precondition_sensors**: creează `sensor.<area_id>_next_precondition` (timestamp) cu
  atributele `target_temperature`, `event_summary`, `event_start`, `climate_entity`.

**Text la printare**: linia de sub fiecare cod QR pe foaia printată. Se setează pentru toate camerele cu
**Text la printare: toate camerele** (implicit „Scanează- Termostat”) sau pe cameră cu **Modifică**, lângă
„Text la printare” în coloana Cod QR.

Setări pe cameră: copiază `rooms.example.yaml` în `/addon_configs/<id>_room_climate_portal/rooms.yaml`.

## 3. Publică paginile sub domeniul HA (același port 443)

Add-on-ul servește tot ce e sub `/camera` pe portul lui 8080. Ce răspunde pe 443 pentru
`ha.voxdomini.ro` trimite `/camera/` acolo și restul la HA, ca până acum.
Ca destinație folosește **Hostname**-ul add-on-ului din pagina lui Info (de exemplu
`a0d7b954-room-climate-portal`); merge și IP-ul din rețea al HA Green, cu portul 8080.

### Cu add-on-ul oficial „NGINX Home Assistant SSL proxy” (merge pe HA Green)

1. Creează `/share/nginx_proxy_default_camera.conf` (add-on-ul Samba sau File editor):

   ```nginx
   location /camera/ {
       proxy_pass http://<add-on hostname>:8080;
       proxy_http_version 1.1;
       proxy_set_header Host $host;
       proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
       proxy_set_header X-Forwarded-Proto $scheme;
       proxy_buffering off;          # actualizări live (Server-Sent Events)
       proxy_read_timeout 1h;
   }
   ```
2. În configurația add-on-ului NGINX setează `customize: active: true` (modelul implicit
   `nginx_proxy_default*.conf` preia fișierul) și repornește add-on-ul NGINX.
3. În acest add-on setează `trust_proxy_headers: true`.

Dacă HA face acum singur HTTPS (`ssl_certificate` sub `http:` în configuration.yaml, cu routerul
trimițând 443 → 8123), trecerea la add-on-ul NGINX înseamnă: îl instalezi cu domeniul tău și fișierele
de certificat din `/ssl`, ștergi liniile `ssl_*` din `http:`, adaugi `use_x_forwarded_for: true` și
`trusted_proxies: [172.30.33.0/24]` sub `http:`, repornești HA și trimiți portul 443 al routerului la
portul 443 al HA Green.

### Cu add-on-ul Cloudflared (Cloudflare Tunnel)

Nu e nevoie de NGINX. Setează `trust_proxy_headers: true` în acest add-on.

- **Tunel administrat din dashboard-ul Cloudflare** (add-on-ul Cloudflared are `tunnel_token`):
  Zero Trust → Networks → Tunnels → tunelul tău → Public Hostname → **Add a public hostname**:
  subdomeniu `ha`, domeniu `voxdomini.ro`, cale `camera/*`, serviciu **HTTP** `172.30.32.1:8080`.
  Intrarea trebuie să fie **deasupra** intrării existente `ha.voxdomini.ro` (regulile se potrivesc de sus în jos).
- **Tunel administrat chiar de add-on** (fără `tunnel_token`): add-on-ul nu poate adăuga o regulă pe cale
  pentru hostname-ul HA. Folosește un subdomeniu, în opțiunile add-on-ului Cloudflared:
  `additional_hosts: [{hostname: camera.voxdomini.ro, service: "http://172.30.32.1:8080"}]`,
  și setează `public_url` al acestui add-on la `https://camera.voxdomini.ro`.

`172.30.32.1` e mașina HA văzută din add-on-uri, unde e publicat portul 8080 al acestui add-on.
Dacă `cloudflared` rulează pe alt calculator (nu ca add-on HA), folosește IP-ul din rețea al mașinii HA,
de exemplu `http://192.168.1.50:8080`.

### Cu accesul de la distanță Nabu Casa

Nu se poate: adresa Nabu Casa ajunge doar la HA. Folosește una dintre variantele de mai sus.

## 4. PIN (opțional)

În tab-ul **Camere**, fiecare cameră are **Setează PIN / Schimbă PIN-ul / Șterge PIN-ul**, iar **PIN
pentru toate camerele** pune (sau șterge, dacă îl lași gol) același PIN peste tot. Cu PIN, telefonul îl
cere o dată și îl ține minte `pin_remember_hours`; schimbarea PIN-ului deconectează toate telefoanele din
acea cameră. După `pin_max_attempts` încercări greșite, telefonul e blocat `pin_lockout_minutes`, iar o
cameră acceptă cel mult 50 de încercări greșite pe oră, în total.

## 5. Pornește preîncălzirea la ora afișată

Importă blueprint-ul `blueprints/automation/room_precondition.yaml` din acest repository și creează câte o
automatizare pentru fiecare cameră (senzorul de preîncălzire + termostatul). Ea pornește exact la ora
afișată pe pagină, așa că pagina și încălzirea nu se contrazic.

## 6. Încălzire manuală și perioade planificate

Camerele fără eveniment în calendar se pot încălzi și din pagina camerei:

- **Pornește încălzirea** pentru 1 h, 2 h sau 4 h, sau **până la** o oră aleasă. Schimbarea temperaturii
  cu − / + pornește și ea încălzirea manuală (și repornește un termostat oprit).
- Implicit, încălzirea manuală **se oprește singură după 2 ore** (`hold_default_minutes`). Cât timp
  merge, oaspetele poate adăuga +30 min / +1 h, poate alege altă oră de final sau o poate opri. O perioadă
  durează cel mult `hold_max_hours` (12 h).
- **Planifică o perioadă**: de la–până la, în următoarele 24 h, cu temperatura ei (cel mult 4 pe cameră).
  Pornește și se oprește singură și apare pe pagina Program.
- La final, termostatul revine la **setările camerei din administrare** (vezi mai jos). Dacă în acel
  moment camera are un eveniment în preîncălzire sau în desfășurare, nu se schimbă nimic, ca evenimentul
  să-și păstreze încălzirea.

### Setările camerei (administrare)

Temperatura și modul setate pentru o cameră în administrare sunt ținute minte ca setările camerei. Când
se termină o perioadă manuală, o perioadă planificată sau un eveniment din calendar (sau un eveniment e
șters în timp ce rulează), termostatul revine la ele, de exemplu *Oprit* sau *Încălzire 18 °C*. Camerele
pe care nu le-ai setat sunt oprite (`hold_end_action: off`) sau puse la `setback_temp`
(`hold_end_action: setback`). Oprește `restore_after_events` dacă automatizările tale se ocupă deja de
sfârșitul evenimentelor.

Perioadele sunt salvate în `/data/holds.json` și rămân după reporniri și actualizări.

## 7. Coduri personalizate

Implicit, linkul fiecărei camere se formează din etaj și nume, de exemplu zona *D01 - Sala sport* de pe
etajul *Demisol* → `https://camera.voxdomini.ro/room/demisol-d01-sala-sport` (fără diacritice, cu litere
mici; se adaugă un număr dacă două camere ar primi același link). Codul se fixează când camera e văzută
prima dată, așa că redenumirea zonei nu strică codul QR printat; **Cod ușor de citit** îl reface din
numele actual. Linkurile ușor de citit sunt ușor de ghicit, așa că pune PIN acestor camere sau setează
`readable_codes: false` ca să folosești un cod aleator de 22 de caractere. **Cod personalizat** îți
permite să-l alegi, de exemplu `sala-102` → `https://camera.voxdomini.ro/camera/sala-102`. Codurile
trebuie să fie unice și să aibă 4–64 de litere, cifre, `-` sau `_`. Un cod scurt sau ușor de ghicit (cum
e numărul camerei) poate fi încercat de oricine, așa că pune PIN acestor camere. **Cod aleator nou**
înlocuiește un cod personalizat cu unul aleator. Orice schimbare oprește codul printat vechi.

## 8. Printează codurile QR

Deschide **Încălzire camere** din bara laterală HA. Tab-ul **Camere** listează toate camerele, cu ce s-a
găsit (și ce lipsește), temperaturile live, următorul eveniment și codul QR. **Printează toate codurile
QR** dă o foaie A4; **Cod aleator nou** înlocuiește codul unei camere (eticheta veche nu mai funcționează
imediat, paginile deschise se închid).

## 9. Instalația și jurnalul de încălzire

Tab-ul **Instalație** arată fiecare centrală cu circuitul pe care îl folosește (pornit sau oprit, preset,
cerere de căldură) și un tabel care leagă fiecare cameră de circuitul care o încălzește, de robinetul ei
(un switch pe distribuitor, dacă are) și de senzorul ei de temperatură. Valorile marcate *ghicit* vin din
zona camerei: un switch `*_relay` devine robinetul, senzorul de temperatură al zonei devine senzorul.
Alege o valoare ca s-o păstrezi, alege „–” ca să revii la ce a fost ghicit. **Încălzire** stabilește dacă
o cameră urmează evenimentele din calendar, are nevoie doar de antiîngheț sau nu se încălzește deloc.

Centralele se creează la prima pornire și se salvează în `/data/topology.json`. Se folosește doar primul
circuit al fiecărei centrale: `climate.sala_plen1`, `climate.parter1`, `climate.etaj1` și
`climate.demisol1`. Add-on-ul arată fiecare circuit cu numele lui din HA (un nume setat în registrul de
entități are prioritate). Un circuit e considerat pornit cât timp presetul lui e `Winter` sau
`heat_request` e peste 0.

Add-on-ul înregistrează temperaturile camerelor, temperatura de afară (`outdoor_sensor`), fiecare circuit
și fiecare robinet în `/data/heating.db` (SQLite): un rând la fiecare schimbare, cel puțin unul la 10
minute. Rândurile mai vechi de 120 de zile devin medii pe 15 minute. Tab-ul **Jurnal încălzire** listează
rulările măsurate din ele:

| Rulare | Ce se măsoară pentru fiecare cameră |
| --- | --- |
| Încălzire (de la pornirea circuitului până la oprire, cel mult 8 h) | temperatura de pornire, timpul mort până la +0,2 °C, viteza de încălzire în °C/h, timpul până la temperatura de confort, temperatura de afară, câte circuite ale centralei erau pornite |
| Răcire (circuit oprit cel puțin 2 h) | constanta de timp τ în ore: cât de repede pierde camera căldura spre exterior |

Adaugă o notă unei rulări ca să marchezi un test, de exemplu „Test A, un circuit”.

## 10. Ora estimată de pornire

Secțiunea **Ora estimată de pornire** din tab-ul Instalație are câte un rând pentru fiecare circuit cu o
cameră legată care are un eveniment cu oră în viitor. Rândul arată camera care are nevoie prima de
căldură, când trebuie pornit circuitul pentru ea și cum e calculată ora:

```
preîncălzire = timp mort + (țintă − temperatura camerei la pornire) ÷ viteza de încălzire + 15 min rezervă
```

- **Timpul mort și viteza de încălzire** vin din rulările de încălzire ale camerei din Jurnal încălzire.
  Dacă nu are, se folosesc rulările altor camere de pe același circuit. Fără nicio rulare, valorile
  implicite sunt 40 min și 1,5 °C/h. Eticheta arată câte rulări s-au folosit.
- **Centrală împărțită**: când alte circuite ale aceleiași centrale încălzesc în același timp, puterea
  centralei se împarte (2 circuite: 67 % fiecare, 3 circuite: 50 %), deci pornirea se mută mai devreme.
- **Temperatura de afară**: cu cel puțin 5 rulări răspândite pe cel puțin 4 °C de temperatură exterioară,
  viteza urmează și temperatura de afară.
- **Răcirea până la pornire**: după ce camera are un τ dintr-o rulare de răcire, estimarea prezice cât
  se răcește camera până pornește circuitul.
- **Ținta**: linia `target:` a evenimentului, altfel temperatura de confort a camerei din tab-ul
  Instalație, altfel `default_target_temp`.
- **Preîncălzirea folosită acum**: timpul fix folosit efectiv de preîncălzire, pentru comparație.

Pe telefon, cardul arată doar următorul eveniment și ora estimată; **Detalii** deschide restul.

Tab-ul **Jurnal încălzire** se încheie cu **Estimat față de realitate**: ultima estimare făcută înainte de
ora estimată de pornire a fiecărui eveniment, apoi, după eveniment, când a pornit de fapt circuitul,
temperatura camerei la începutul evenimentului și când a ajuns camera la țintă.

## 11. Comanda încălzirii (comutarea circuitelor)

Secțiunea **Comanda încălzirii** din tab-ul Instalație are câte un card pentru fiecare centrală, în unul
din două moduri:

- **Simulare** (implicit): add-on-ul decide în fiecare minut ce ar face cu circuitul și arată decizia
  („Ar porni: preîncălzire pentru Sala Mare”). Nu se trimite nimic la HA.
- **Activ**: add-on-ul comută circuitul (presetul `Winter` ca să pornească, `Summer` ca să oprească) și
  robinetele (switch-urile) camerelor de pe el.

Un circuit pornește pentru:

| Motiv | Când |
| --- | --- |
| Preîncălzire | De la ora estimată (secțiunea 10) până la eveniment, până ajunge camera la țintă |
| Eveniment | Cât timp rulează un eveniment într-o cameră de pe circuit: sub țintă − `hysteresis` pornește, peste țintă + `hysteresis` se oprește. O cameră fără senzor se încălzește tot evenimentul. |
| Antiîngheț | Orice cameră încălzită sub `frost_temp` (implicit 10 °C), până se încălzește cu 1 °C |

Altfel se oprește, și comută cel mult o dată la `min_switch_minutes` (implicit 10; antiîngheț-ul nu
așteaptă). Robinetul unei camere e deschis doar cât timp camera lui are nevoie de căldură.

### Înainte să pui o centrală pe Activ

1. **Automatizări preluate.** La *Alege automatizările*, bifează fiecare automatizare HA care comută acest
   circuit. Pentru Sala Plen azi: *Sala Mare - termostat Zone1*, *Sala Mare - termostat oprit, Zone1 pe
   Summer*, *HVAC sala plen - smart start/resume*. *Climate - Winter at night, Summer in the morning*
   comută toate cele patru centrale: dacă o preiei, se oprește încălzirea ei de noapte și pentru
   centralele rămase pe Simulare. Activ oprește aceste automatizări; Simulare le repornește.
2. **Watchdog.** Creează o automatizare din blueprint-ul `blueprints/automation/heating_watchdog.yaml`
   (importă-l din repository). Add-on-ul publică `sensor.heating_controller_heartbeat` în fiecare minut;
   dacă e mai vechi de 15 minute, watchdog-ul repornește automatizările preluate și afișează o notificare.
   Când add-on-ul pornește din nou și vede pornită una din automatizările lui preluate, trece centrala
   înapoi pe Simulare: pune-o din nou pe Activ din tab-ul Instalație după ce totul e în regulă.
3. **Robinetele de la Parter.** Releele `switch.p0X_…_relay` sunt comandate și de termostatele generice
   `climate.p0X_…_thermostat`. Oprește acele termostate înainte să pui Parterul pe Activ, altfel se bat.

Fiecare comutare făcută de add-on apare în Modificări recente („Controler: … → Winter (preîncălzire, …)”).

## 12. Economie, avertismente, teste și grafice

**Oprire anticipată.** După ce camera are un τ dintr-o rulare de răcire, încălzirea se oprește înainte
de finalul evenimentului, cât timp camera pierde cel mult `coast_drop` °C (implicit 0,5) până la final,
dar nu mai devreme de `max_coast_minutes` (45). O cameră care e deja cu 1 °C sub țintă se încălzește în
continuare.

**Temperatura minimă de așteptare (setback dinamic).** Înaintea unui eveniment din următoarele
`setback_horizon_hours` (8 h), fiecare cameră e ținută peste un minim: cea mai mică temperatură din
care preîncălzirea încă încape în `max_preheat_hours` (6 h), după timpul mort și viteza învățate (și
prognoză). Minimul nu urcă niciodată cu mai mult de 1 °C peste `setback_temp`: dacă modelul cere mai mult,
evenimentul nu încape oricum în `max_preheat_hours`, iar ținerea camerei aproape de confort ore în șir
doar arde gaz. Mai departe de un eveniment se aplică doar antiîngheț-ul, deci camera se poate răci cât vrea.

Viteza de încălzire se învață doar din rulările de preîncălzire, eveniment și test: o rulare în care
circuitul a ținut camera la minim sau la antiîngheț nu e o rampă și nu intră în model. Nici rulările sub
0,25 °C/h (cele vechi, de dinainte ca motivul deschiderii să fie salvat).
Cardul din Comanda încălzirii arată minimul fiecărei camere.

**La timp sau întârziat.** În timpul preîncălzirii, add-on-ul calculează când ajunge camera la țintă din
ce face ea de fapt. Dacă asta e cu mai mult de `late_margin_minutes` (10) după începutul evenimentului,
cardul scrie „întârzie” și primești o notificare pe eveniment.

**Prognoză.** Setează `weather_entity` (de exemplu `weather.forecast_vox_domini`). Estimările și minimul
de așteptare folosesc atunci temperatura prognozată pentru fiecare interval de preîncălzire, nu
temperatura de acum.

**Ora estimată pe paginile camerelor.** Deasupra estimărilor, alege *Ora estimată* ca paginile
camerelor, `sensor.<cameră>_next_precondition` și intervalul „eveniment în desfășurare” să folosească
preîncălzirea estimată a fiecărei camere pentru următorul ei eveniment, în loc de timpul fix. *Timpul
fix* revine la valoarea fixă.

**Senzori în HA**, actualizați în fiecare minut: `sensor.heating_<circuit>_next_start` (timestamp;
cameră, eveniment, preîncălzire, încredere) și `sensor.heating_<circuit>_decision` (open/closed; motiv,
mod, întârziere), de exemplu `sensor.heating_sala_plen1_next_start`.

**Notificările** merg la `notify_service` (de exemplu `notify.iphone`), altfel în panoul de notificări
din HA: preîncălzire întârziată, un circuit care nu a comutat în 5 minute după comandă, un test oprit de
un eveniment și, o dată pe zi, senzorii camerelor legate care sunt offline.

**Teste.** Pe o centrală Activă, *Pornește un test (A, apoi B)* programează, de exemplu diseară la 22:00,
testul A (pornit până camera crește cu 3 °C sau trec 4 h), apoi testul B (oprit 8 h). Rulările făcute în
timpul unui test primesc nota „Test A” sau „Test B” în Jurnal încălzire. Un test e refuzat dacă un
eveniment (cu preîncălzirea lui) cade în timpul lui și se oprește dacă e nevoie de circuit.

**Grafice.** *Ultimele 24 h* pe fiecare circuit și *Grafic* pe fiecare rulare din Jurnal încălzire:
temperatura camerei, temperatura de afară și perioadele în care circuitul a fost pornit.

**Watchdog după repornire.** În automatizarea watchdog, alege la *Automatizări de rezervă* aceleași
automatizări: dacă semnalul de funcționare nu revine în 15 minute de la pornirea Home Assistant, ele sunt
repornite.

## Securitate

- Fiecare cod e un token de 128 de biți care arată aleator (HMAC al unui secret din `/data`); numerele camerelor nu apar niciodată în URL.
- PIN opțional pe cameră, salvat ca hash PBKDF2 cu salt; cookie-ul de deblocare e HttpOnly, SameSite=Strict, limitat la `/camera/`.
- Un cod ajunge doar la termostatul camerei lui și doar la `set_temperature` (plus modul termostatului, dacă e permis).
- Țintele sunt limitate pe server; o modificare pe cameră la 3 s și 60 pe oră pe telefon.
- Fiecare modificare e înregistrată (cameră, vechi → nou, ora, id pseudonim al telefonului) și apare în administrare.
- Paginile pentru oaspeți trimit CSP strict, `no-referrer` și niciun cod de la terți.

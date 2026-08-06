# NFF Ticket Monitor

Varsler på Telegram når det dukker opp billetter til herrelandslagets kamper —
både ved nysalg på [billett.fotball.no](https://billett.fotball.no) og ved
videresalg på [resale.fotball.no](https://resale.fotball.no).

**Dette er en varsler.** Den kjøper ingenting, omgår ingen kø og løser ingen
CAPTCHA. Den ser på offentlig tilgjengelige endepunkter og sender deg en
melding.

---

## ⚠️ robots.txt

`www.fotball.no` har `User-agent: * → Disallow: /`. Kunngjøringsvakten poller
den siden likevel, én gang i timen, fordi det er et bevisst valg gjort ved
oppsett. Hver eneste slike request logges:

```
WARNING nffmon.httpclient: ROBOTS-DISALLOWED https://www.fotball.no/... -
  robots.txt for this host disallows our user-agent; fetching anyway per configuration
```

Vil du ikke det, sett `announce.enabled: false` i `chart/values.yaml`. Da
slutter monitoren å røre `www.fotball.no` helt — men du mister automatisk
oppdaging av nye kamper og salgsdatoer, og hot-vinduet i tilgjengelighetsvakten
får ingen salgstidspunkter å skjerpe seg rundt.

De to billettdomenene er uproblematiske: alle endepunktene som brukes ligger
utenfor deres disallow-liste. Sjekk selv når som helst:

```bash
./run-local.sh robots
```

---

## Hvordan det virker

Begge billettsystemene er samme SecuTix-installasjon og har rene
JSON/AJAX-endepunkter. **Ingen headless nettleser, ingen innlogging** —
videresalgslistene er lesbare anonymt (innlogging kreves kun for å kjøpe), så
appen holder ingen credentials og ingen sesjon.

| Endepunkt | Gir |
|---|---|
| `billett.fotball.no/ajax/event/date/performances?productId=…` | alle kamper under ett produkt, med `available`/`sold_out` |
| `resale.fotball.no/selection/resale/resaleItems.json?performanceId=…` | antall videresalgsbilletter for én kamp |
| `billett.fotball.no/list/resale/resaleProductCatalog.json` | produktkatalogen, for å finne `productId` |

Et **produkt** er en kampkategori («Nations League - A-herrer»), ikke én kamp.
Enkeltkampene ligger under som *performances*, med `performanceId` som stabil
nøkkel. Derfor abonnerer du på produktet: nye kamper plukkes opp automatisk
uten at du redigerer noe.

### To CronJobs

**A — kunngjøringsvakt** (`7 * * * *`)
Poller kunngjøringssiden, differ mot forrige kjøring, varsler ved ny kamp, ny
salgsdato, endret salgsdato eller endret status. Skriver `sale_schedule.json`.

Med `announce.homeMatchesOnly: true` (default) varsles bare kamper spilt i
Norge — «NORGE – X». Bortekamper selges av motstanderforbundet, så
salgsdatoene deres kan uansett ikke styre hot-vinduet. Sett den til `false`
hvis du også vil ha bortekamper; da varsles de tre du filtrerte bort som
«nye» ved neste kjøring.

**B — tilgjengelighetsvakt** (`*/5 * * * *`)
CronJobs har fast schedule, så adaptiviteten ligger i prosessen:

- **utenfor salgsvindu** — de to kildene har hver sin takt, og en kjøring der
  ingen av dem er forfalt avslutter på under et sekund:

  | Kilde | Takt | Hvorfor |
  |---|---|---|
  | billett.fotball.no | 30 min | salgstidspunktene er kjent på forhånd, så mellomtiden er bare forsikring |
  | resale.fotball.no | 5 min | supportere legger ut billetter når som helst, og de kjøpes ofte i løpet av minutter |

  `resaleIntervalSeconds` er satt til **240**, ikke 300, med vilje: gaten måler
  mot forrige kjørings starttidspunkt, og to cron-kjøringer ligger 300 s fra
  hverandre pluss/minus scheduling-jitter. På nøyaktig 300 ville en kjøring som
  starter et øyeblikk for tidlig falle gjennom gaten og utsette til neste — og
  takten ble i praksis 10 minutter annenhver gang.

  Resale-pollen leser `performanceId` rett fra `availability.json` og trenger
  derfor ikke hente kamplista fra billett.fotball.no først. Det er det som gjør
  den høyere frekvensen billig: én request per kamp, ikke en katalogvandring.
- **i salgsvindu** (10 min før → 60 min etter et kjent salgstidspunkt) —
  løkker internt hvert 60. sekund til vinduet lukkes eller kjøringsbudsjettet
  er brukt opp, hvorpå neste cron-kjøring tar over sømløst

Pre-vinduet er 10 min og ikke 5 med vilje: med 5-minutters cron ville et
5-minutters pre-vindu i verste fall gitt første poll akkurat ved salgsstart.

Varsel sendes **kun ved tilstandsendring** — utsolgt → tilgjengelig, eller
flere billetter på resale. Aldri hver kjøring. Per kamp+kilde er det maks ett
varsel per 10 min; hendelser innenfor cooldown parkeres og slås sammen, så en
selger som legger ut sju billetter én om gangen gir én melding, ikke sju.

### State

Tre filer på delt PVC. De to jobbene skriver aldri samme fil, så det trengs
ingen låsing. Alle skriv går via temp-fil + `rename`.

| Fil | Skriver | Leser |
|---|---|---|
| `announcements.json` | A | A |
| `sale_schedule.json` | A | A + **B** |
| `availability.json` | B | B |

---

## Legge til en ny kamp

Som regel trenger du ikke gjøre noe: en ny landskamp dukker opp som en ny
*performance* under et produkt du allerede overvåker, og fanges automatisk.

Skal du følge en **ny kategori** (f.eks. VM-kvalik), finn `productId`:

```bash
./run-local.sh list-products
```

```
10229739619905  qty=     0  Nations League - A-herrer  [Ullevaal Stadion]  first=[2026, 9, 24, 20, 45, 0]
```

Legg den til under `watch:` i `chart/values.yaml`:

```yaml
watch:
  - productId: 10229739619905
    label: "Nations League - A-herrer"
    include:
      - "Norge vs *"      # kun hjemmekamper; tom liste = alle
    exclude: []
    sources:
      - primary
      - resale
    performanceIds: []    # tom = alle kamper under produktet
```

`include`/`exclude` er fnmatch-mønstre mot `"Hjemmelag vs Bortelag"`. Vil du
pinne én enkelt kamp, sett `performanceIds: [10229739913106]` — id-en ser du i
`./run-local.sh check`.

Deploy på nytt:

```bash
./build-and-deploy.sh
```

---

## Teste lokalt

```bash
cp app/.env.local.example app/.env.local
$EDITOR app/.env.local          # fyll inn Telegram-token og chat-id
```

`run-local.sh` lager et virtualenv første gang og kjører mot de ekte sidene:

```bash
./run-local.sh robots           # robots.txt-dom per URL vi rører
./run-local.sh list-products    # productId-er for values.yaml
./run-local.sh check            # alle overvåkede kamper og tilstanden deres — sender INGENTING
./run-local.sh availability     # full kjøring — SENDER Telegram-varsel
./run-local.sh announce         # full kjøring — SENDER Telegram-varsel
```

`check` er den du vil bruke mest:

```
# Nations League - A-herrer (productId=10229739619905)
  10229739913106  sold_out   Norge vs Danmark    torsdag, 24 september 2026 - 20:45  Fra 240.00 NOK  resale_hint=True
  10229739913107  sold_out   Norge vs Portugal   søndag, 27 september 2026 - 20:45   Fra 240.00 NOK  resale_hint=True
```

Lokal state havner i `app/local-state/` (gitignorert). Slett den for å
nullstille — merk at neste kjøring da varsler om alt på nytt.

Vil du teste hot-vinduet uten å vente på et ekte salg, injiser et
salgstidspunkt akkurat nå:

```bash
python3 -c "
import json,datetime
p='app/local-state/sale_schedule.json'; d=json.load(open(p))
now=datetime.datetime.now().astimezone()
d['matches']=[{'key':'test','label':'TEST','kickoff_date':'2026-11-14',
  'phases':[{'name':'apent_salg','starts_at':now.isoformat(),'description':'test'}]}]
json.dump(d,open(p,'w'))"
./run-local.sh availability     # skal logge 'HOT: ...' og løkke
```

---

## Deploy

Forutsetter `podman`, `kubectl` og `helm`. Imaget side-lastes inn i k3s sin
egen containerd — derfor `imagePullPolicy: Never` og ingen registry.

```bash
kubectl create namespace nff-monitor

cp secrets-apply-manually/nff-monitor-secret.example.yaml \
   secrets-apply-manually/nff-monitor-secret.yaml
$EDITOR secrets-apply-manually/nff-monitor-secret.yaml
kubectl apply -f secrets-apply-manually/nff-monitor-secret.yaml

./build-and-deploy.sh
```

Secret-manifestet ligger med vilje utenfor chartet, og den utfylte
`nff-monitor-secret.yaml` er gitignorert.

Kjør en jobb nå i stedet for å vente på schedule:

```bash
kubectl create job -n nff-monitor manual-$(date +%s) \
  --from=cronjob/nff-ticket-monitor-availability
kubectl logs -n nff-monitor -l app.kubernetes.io/name=nff-ticket-monitor -f --tail=100
```

---

## Hente ut state-fila for debugging

PVC-en er `local-path`, så fila ligger rett på noden:

```bash
kubectl get pv -o jsonpath='{range .items[*]}{.spec.claimRef.name}{"\t"}{.spec.hostPath.path}{"\n"}{end}' \
  | grep nff-ticket-monitor-data
sudo cat /var/lib/rancher/k3s/storage/<pvc-katalog>/availability.json | jq .
```

Uten å røre noden — start en engangspod på samme PVC:

```bash
kubectl run -n nff-monitor state-debug --rm -it --restart=Never \
  --image=busybox --overrides='
{"spec":{"containers":[{"name":"state-debug","image":"busybox","stdin":true,"tty":true,
"command":["sh"],"volumeMounts":[{"name":"d","mountPath":"/data"}]}],
"volumes":[{"name":"d","persistentVolumeClaim":{"claimName":"nff-ticket-monitor-data"}}]}}'
# / # cat /data/availability.json
```

Kopiere ut lokalt:

```bash
kubectl cp -n nff-monitor state-debug:/data/availability.json ./availability.json
```

Nullstill én kilde for én kamp (tvinger nytt varsel neste gang den blir
tilgjengelig) ved å sette `state` til `"unknown"` og `last_notified_at` til
`null` under den aktuelle `performanceId`.

---

## Når parsing ryker

Alle selectors, URL-er og tekstmarkører ligger samlet i
[app/nffmon/endpoints.py](app/nffmon/endpoints.py). Endrer NFF markupen, er det
den ene fila som skal rettes.

Stille feil er verre enn støy, så en parser som slutter å finne det den
forventer sender Telegram-varsel — maks ett per 6. time, så en varig
markup-endring ikke gir melding hvert femte minutt.

Ett viktig skille er innebygd: et produkt uten kamper (normalt mellom sesonger)
gir tom liste og *ingen* alarm, mens en respons som ikke lenger inneholder
fragment-markøren gir alarm. Uten det skillet ville et utspilt produkt varslet
deg i månedsvis.

Tilstanden til hver kilde ligger i `availability.json` under `parse_health`.

### Kjent usikkerhet

Da dette ble bygget fantes det **null** videresalgsbilletter i hele
NFF-systemet, så bare den *tomme* responsen fra resale kunne observeres. Formen
på en respons med billetter i er utledet, ikke verifisert. Parseren er derfor
skrevet som «er dette gjenkjennelig den tomme tilstanden? ellers → varsle», som
feiler mot falsk alarm framfor mot stillhet. Prisintervallet i
videresalgsvarselet er best effort og kan mangle første gang det smeller.

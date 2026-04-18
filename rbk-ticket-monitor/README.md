# RBK Ticket Monitor

Overvåker [RBK billettsiden](https://billett.rbk.no/section/kampbilletter-76ym) og sender Telegram-varsel når nye kamper legges ut.

## Funksjoner

- Kontinuerlig overvåking av RBK billettsiden
- Telegram-notifikasjoner ved nye kamper
- State persistence for å unngå duplikat-varsler
- Kjører i Kubernetes med automatisk restart

## Forutsetninger

1. En Telegram bot token
2. Din Telegram chat ID
3. Kubernetes cluster
4. Podman for å bygge image

## Oppsett

### 1. Sett opp Telegram Bot

#### Lag en bot og få bot token:

1. Åpne Telegram og søk etter `@BotFather`
2. Send `/newbot` kommandoen
3. Følg instruksjonene for å gi boten et navn
4. Kopier bot token som ser slik ut: `123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ`

#### Finn din Chat ID:

1. Send en melding til boten din
2. Åpne denne URLen i nettleseren (bytt ut `YOUR_BOT_TOKEN`):
   ```
   https://api.telegram.org/botYOUR_BOT_TOKEN/getUpdates
   ```
3. Se etter `"chat":{"id":123456789` i responsen
4. Chat ID er nummeret (f.eks. `123456789`)

### 2. Bygg Container Image

```bash
cd rbk-ticket-monitor
podman build -t localhost/rbk-ticket-monitor:latest .
```

Hvis du bruker k3s eller lignende, kan du trenge å importere imaget:

```bash
# For k3s
podman save localhost/rbk-ticket-monitor:latest | sudo k3s ctr images import -

# For minikube
minikube image load localhost/rbk-ticket-monitor:latest
```

### 3. Deploy til Kubernetes

#### Opprett Telegram secret:

```bash
kubectl create secret generic rbk-monitor-secret \
  --namespace rbk-monitor \
  --from-literal=TELEGRAM_BOT_TOKEN=your_bot_token_here \
  --from-literal=TELEGRAM_CHAT_ID=your_chat_id_here
```

**Merk:** Namespace opprettes automatisk av manifestet, men hvis du får feilmelding om at namespace ikke eksisterer, kjør:

```bash
kubectl create namespace rbk-monitor
```

#### Deploy applikasjonen:

```bash
kubectl apply -f rbk-ticket-monitor.yaml
```

### 4. Verifiser at det fungerer

Sjekk at poden kjører:

```bash
kubectl get pods -n rbk-monitor
```

Se logger:

```bash
kubectl logs -n rbk-monitor -l app=rbk-ticket-monitor -f
```

Du skal se noe som:

```
2026-04-18 10:00:00 - INFO - Starting RBK Ticket Monitor
2026-04-18 10:00:00 - INFO - Checking every 300 seconds
2026-04-18 10:00:00 - INFO - Fetching https://billett.rbk.no/section/kampbilletter-76ym
2026-04-18 10:00:01 - INFO - Found 5 potential matches
```

## Konfigurasjon

Du kan justere overvåkingsintervallet ved å endre `CHECK_INTERVAL` i `rbk-ticket-monitor.yaml`:

```yaml
- name: CHECK_INTERVAL
  value: "300"  # Sekunder mellom hver sjekk (300 = 5 minutter)
```

Anbefalt intervall er 5-10 minutter for å unngå å overbelaste nettsiden.

## Testing

For å teste uten å vente på nye kamper, kan du slette state-filen slik at alle eksisterende kamper blir detektert som "nye":

```bash
# Finn pod navn
POD=$(kubectl get pod -n rbk-monitor -l app=rbk-ticket-monitor -o jsonpath='{.items[0].metadata.name}')

# Slett state file
kubectl exec -n rbk-monitor $POD -- rm -f /data/state.json

# Restart poden for å kjøre ny sjekk
kubectl delete pod -n rbk-monitor $POD
```

## Vedlikehold

### Oppdater scriptet:

1. Gjør endringer i `monitor.py`
2. Bygg nytt image med `podman build -t localhost/rbk-ticket-monitor:latest .`
3. Importer til k3s: `podman save localhost/rbk-ticket-monitor:latest | sudo k3s ctr images import -`
4. Restart deployment:

```bash
kubectl rollout restart deployment/rbk-ticket-monitor -n rbk-monitor
```

### Se state:

```bash
POD=$(kubectl get pod -n rbk-monitor -l app=rbk-ticket-monitor -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n rbk-monitor $POD -- cat /data/state.json
```

## Feilsøking

### Ingen notifikasjoner:

1. Sjekk at boten har riktig token og chat ID
2. Verifiser at du har startet en samtale med boten (send `/start`)
3. Sjekk logger for feilmeldinger

### Duplikat-varsler:

Dette kan skje hvis state-filen blir slettet eller pod restartes med ny PVC. State-filen lagrer hvilke kamper som allerede er sett.

### Pod crasher:

```bash
kubectl describe pod -n rbk-monitor -l app=rbk-ticket-monitor
kubectl logs -n rbk-monitor -l app=rbk-ticket-monitor --previous
```

## Avinstallering

```bash
kubectl delete -f rbk-ticket-monitor.yaml
kubectl delete secret rbk-monitor-secret -n rbk-monitor
kubectl delete namespace rbk-monitor
```

## Lisens

Dette er et personlig prosjekt for overvåking av RBK billetter.

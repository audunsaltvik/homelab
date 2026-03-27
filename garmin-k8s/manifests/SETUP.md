# Garmin K8s Stack Setup Guide

This guide explains the security improvements made to the Garmin monitoring stack and how to deploy it.

## Security Improvements Applied

### 1. **Separated Secrets from Manifest**
**Problem**: Original manifest had hardcoded passwords in plaintext that would be committed to git.

**Solution**:
- Created `secrets.yaml.example` template
- Removed all secret definitions from main manifest
- Secrets must be created separately before deployment

**Why**: Prevents accidental exposure of credentials in version control.

### 2. **Secure Grafana Admin Credentials**
**Problem**: Grafana used hardcoded `admin/admin` credentials.

**Solution**:
- Grafana now reads admin credentials from `grafana-credentials` secret
- Passwords must be generated using secure methods

**Why**: Default credentials are a major security risk and often exploited.

### 3. **Secure Datasource Configuration**
**Problem**: InfluxDB password was stored in plaintext in ConfigMap.

**Solution**:
- Grafana datasource config uses environment variable substitution
- Variables `${INFLUXDB_DATABASE}`, `${INFLUXDB_USERNAME}`, `${INFLUXDB_PASSWORD}` are injected from secrets
- Grafana deployment has environment variables populated from secrets

**Why**: ConfigMaps are not encrypted; secrets provide better protection.

### 4. **Pinned Grafana Version**
**Problem**: Using `grafana/grafana:latest` can cause unexpected behavior when image updates.

**Solution**:
- Pinned to specific version: `grafana/grafana:11.4.0`

**Why**: Ensures predictable deployments and allows controlled upgrades.

### 5. **Comprehensive Network Policies**
**Problem**:
- Only ingress rules defined, no egress control
- Garmin fetcher couldn't access external APIs due to missing egress rules

**Solution**:
- Added egress rules to all NetworkPolicies
- All pods can resolve DNS (to kube-system)
- Grafana can connect to InfluxDB
- Garmin fetcher can access external HTTPS endpoints (Garmin Connect API)
- Garmin fetcher can connect to InfluxDB

**Why**: Defense-in-depth security; limits blast radius if a pod is compromised.

## Deployment Instructions

### Step 1: Create Secrets

```bash
# Copy the example file
cd manifests
cp secrets.yaml.example secrets.yaml

# Generate secure passwords
echo "InfluxDB password: $(openssl rand -base64 32)"
echo "Grafana password: $(openssl rand -base64 32)"

# Edit secrets.yaml and replace CHANGE_ME values with generated passwords
vim secrets.yaml  # or nano, or your preferred editor
```

### Step 2: Apply Secrets First

```bash
kubectl apply -f secrets.yaml
```

**Verify secrets were created:**
```bash
kubectl get secrets -n monitoring
```

You should see:
- `influxdb-credentials`
- `grafana-credentials`
- `garmin-credentials`

### Step 3: Deploy the Stack

```bash
kubectl apply -f garmin-stack.yaml
```

### Step 4: Verify Deployment

```bash
# Check all resources
kubectl get all -n monitoring

# Check pods are running
kubectl get pods -n monitoring

# Check logs if needed
kubectl logs -n monitoring -l app=influxdb
kubectl logs -n monitoring -l app=grafana
```

### Step 5: Access Grafana

```bash
# If using NodePort (default configuration)
# Grafana will be available at: http://<node-ip>:30300

# Get your admin password
kubectl get secret grafana-credentials -n monitoring -o jsonpath='{.data.admin-password}' | base64 -d
echo
```

### Step 6: Run Initial Garmin Setup

The initial setup job will authenticate with Garmin and save tokens:

```bash
# Check if job completed
kubectl get jobs -n monitoring

# View logs
kubectl logs -n monitoring job/garmin-initial-setup
```

If you need to provide Garmin credentials non-interactively, edit `secrets.yaml` and uncomment the `garmin-credentials` section.

## Network Policy Explanation

The NetworkPolicies implement a zero-trust network model:

1. **InfluxDB** - Only accepts connections from Grafana and Garmin fetcher pods
2. **Grafana** - Only accepts external connections on port 3000, can only connect to InfluxDB
3. **Garmin Fetcher** - Can access external internet (HTTPS) for Garmin API and InfluxDB internally
4. **All pods** - Can resolve DNS via kube-system namespace

## Troubleshooting

### Grafana can't connect to InfluxDB
Check if environment variables are properly set:
```bash
kubectl exec -n monitoring deployment/grafana -- env | grep INFLUXDB
```

### Garmin fetcher can't reach external API
Check NetworkPolicy is applied:
```bash
kubectl get networkpolicy -n monitoring
kubectl describe networkpolicy allow-garmin-external-access -n monitoring
```

### Secrets not found
Ensure you applied `secrets.yaml` before `garmin-stack.yaml`:
```bash
kubectl get secrets -n monitoring
```

## Security Best Practices

1. **Never commit `secrets.yaml`** - It's in `.gitignore` for a reason
2. **Rotate passwords regularly** - Update secrets and restart pods
3. **Use strong passwords** - Always use cryptographically secure random passwords
4. **Limit access** - Only grant cluster access to trusted users
5. **Monitor logs** - Watch for authentication failures or suspicious activity
6. **Backup persistent data** - Regularly backup PVC contents

## Architecture

```
External User
    |
    v
Grafana (NodePort 30300)
    |
    v
InfluxDB (ClusterIP)
    ^
    |
Garmin Fetcher (CronJob) --> Garmin Connect API (External)
```

All components communicate securely with credentials from Kubernetes secrets.

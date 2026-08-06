#!/bin/bash
# Build the image, side-load it into k3s, and apply the Helm chart.
# Same pattern as rbk-ticket-monitor: no registry, image lives in k3s' own
# containerd store, which is why imagePullPolicy is Never.
set -euo pipefail

cd "$(dirname "$0")"

IMAGE="localhost/nff-ticket-monitor:latest"
NAMESPACE="nff-monitor"
RELEASE="nff-ticket-monitor"

echo "==> Building ${IMAGE}"
podman build -t "${IMAGE}" ./app

echo "==> Importing image into k3s"
podman save "${IMAGE}" | sudo k3s ctr images import -

if ! kubectl get secret nff-monitor-secret -n "${NAMESPACE}" >/dev/null 2>&1; then
    echo
    echo "ERROR: secret 'nff-monitor-secret' is missing in namespace ${NAMESPACE}." >&2
    echo "Create it first:" >&2
    echo "  kubectl create namespace ${NAMESPACE}" >&2
    echo "  cp secrets-apply-manually/nff-monitor-secret.example.yaml \\" >&2
    echo "     secrets-apply-manually/nff-monitor-secret.yaml" >&2
    echo "  \$EDITOR secrets-apply-manually/nff-monitor-secret.yaml" >&2
    echo "  kubectl apply -f secrets-apply-manually/nff-monitor-secret.yaml" >&2
    exit 1
fi

echo "==> Deploying Helm release ${RELEASE}"
helm upgrade --install "${RELEASE}" ./chart \
    --namespace "${NAMESPACE}" \
    --create-namespace

echo
echo "Done. CronJobs:"
kubectl get cronjobs -n "${NAMESPACE}"
echo
echo "Trigger a run now:"
echo "  kubectl create job -n ${NAMESPACE} manual-\$(date +%s) --from=cronjob/${RELEASE}-availability"
echo "Follow logs:"
echo "  kubectl logs -n ${NAMESPACE} -l app.kubernetes.io/name=nff-ticket-monitor -f --tail=100"

#!/bin/bash
set -e

echo "Building container image..."
podman build -t localhost/rbk-ticket-monitor:latest .

echo "Importing image to k3s..."
podman save localhost/rbk-ticket-monitor:latest | sudo k3s ctr images import -

echo "Applying Kubernetes manifests..."
kubectl apply -f rbk-ticket-monitor.yaml

echo "Waiting for deployment..."
kubectl rollout status deployment/rbk-ticket-monitor -n rbk-monitor

echo "Done! Check logs with:"
echo "kubectl logs -n rbk-monitor -l app=rbk-ticket-monitor -f"

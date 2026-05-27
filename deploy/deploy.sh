#!/bin/bash
set -e

# DeepField deployment to infra01
# Usage: ./deploy.sh [--build] [--token TOKEN]

REGISTRY="image-registry.openshift-image-registry.svc:5000"
NAMESPACE="deepfield"
IMAGE="$REGISTRY/$NAMESPACE/deepfield-backend:latest"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

BUILD=false
OCP_TOKEN=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --build) BUILD=true; shift ;;
    --token) OCP_TOKEN="$2"; shift 2 ;;
    *) echo "Unknown: $1"; exit 1 ;;
  esac
done

echo "=== DeepField Deploy ==="
echo "Cluster: $(oc whoami --show-server)"
echo "User: $(oc whoami)"
echo ""

# Create namespace
echo "Creating namespace..."
oc apply -f "$SCRIPT_DIR/namespace.yaml"

# Secrets — generate postgres password, prompt for required values
POSTGRES_PW=$(openssl rand -base64 16)
if [ ! -f "$SCRIPT_DIR/.secrets.env" ]; then
  echo "Creating secrets config at $SCRIPT_DIR/.secrets.env"
  echo "Edit this file with your values, then re-run deploy.sh"
  cat > "$SCRIPT_DIR/.secrets.env" <<ENVEOF
LITELLM_API_BASE=
LITELLM_API_KEY=
CLUSTER_1_NAME=
CLUSTER_1_API_URL=
CLUSTER_1_TOKEN=
ENVEOF
  echo "IMPORTANT: Never commit .secrets.env to git"
  exit 1
fi
source "$SCRIPT_DIR/.secrets.env"
oc create secret generic deepfield-secrets \
  --namespace=$NAMESPACE \
  --from-literal=POSTGRES_USER=deepfield \
  --from-literal=POSTGRES_PASSWORD="$POSTGRES_PW" \
  --from-literal=DATABASE_URL="postgresql://deepfield:${POSTGRES_PW}@deepfield-postgres:5432/deepfield" \
  --from-literal=LITELLM_API_BASE="${LITELLM_API_BASE}" \
  --from-literal=LITELLM_API_KEY="${LITELLM_API_KEY}" \
  --from-literal=CLUSTER_1_NAME="${CLUSTER_1_NAME}" \
  --from-literal=CLUSTER_1_API_URL="${CLUSTER_1_API_URL}" \
  --from-literal=CLUSTER_1_TOKEN="${CLUSTER_1_TOKEN}" \
  --dry-run=client -o yaml | oc apply -f -

# Config
echo "Applying configmap..."
oc apply -f "$SCRIPT_DIR/configmap.yaml"

# Postgres
echo "Deploying PostgreSQL..."
oc apply -f "$SCRIPT_DIR/postgres-pvc.yaml"
oc apply -f "$SCRIPT_DIR/postgres-deployment.yaml"

# Build and push image
if [ "$BUILD" = true ]; then
  echo "Building container image..."
  cd "$ROOT_DIR/backend"
  oc new-build --strategy=docker --binary --name=deepfield-backend -n $NAMESPACE 2>/dev/null || true
  oc start-build deepfield-backend --from-dir=. --follow -n $NAMESPACE
  cd "$SCRIPT_DIR"
fi

# Backend
echo "Deploying backend..."
oc apply -f "$SCRIPT_DIR/backend-deployment.yaml"
oc apply -f "$SCRIPT_DIR/services.yaml"
oc apply -f "$SCRIPT_DIR/route.yaml"

# Wait for rollout
echo "Waiting for postgres..."
oc rollout status deployment/deepfield-postgres -n $NAMESPACE --timeout=120s

echo "Waiting for backend..."
oc rollout status deployment/deepfield-backend -n $NAMESPACE --timeout=120s

# Show route
ROUTE=$(oc get route deepfield -n $NAMESPACE -o jsonpath='{.spec.host}')
echo ""
echo "========================================="
echo "DeepField deployed!"
echo "URL: https://$ROUTE"
echo "Health: https://$ROUTE/health"
echo "API: https://$ROUTE/api/v1/"
echo "========================================="

#!/bin/bash
# ASPICE Analyzer - Kubernetes Deployment Commands
# Copy & paste these commands (after updating REGISTRY_URL)

# =============================================================================
# STEP 1: CONFIGURE
# =============================================================================
# Replace REGISTRY_URL with your actual private registry
# Examples: harbor.company.com, registry.internal:5000, docker.company.com
REGISTRY_URL="REPLACE_ME_WITH_YOUR_REGISTRY_URL"
REGISTRY_USERNAME="your_username"
REGISTRY_PASSWORD="your_password"

echo "Using registry: $REGISTRY_URL"
echo "Update REGISTRY_URL and credentials above, then run the commands below."

# =============================================================================
# STEP 2: BUILD & PUSH IMAGE
# =============================================================================

# Build the Docker image
docker build -t $REGISTRY_URL/aspice-api:latest .

# Login to your private registry (you'll be prompted for credentials)
docker login $REGISTRY_URL

# Push the image to your registry
docker push $REGISTRY_URL/aspice-api:latest

# =============================================================================
# STEP 3: CREATE REGISTRY SECRET IN KUBERNETES
# =============================================================================

# Create namespace first
kubectl create namespace aspice 2>/dev/null || echo "Namespace aspice already exists"

# Create docker-registry secret for Kubernetes to pull from your private registry
kubectl create secret docker-registry regcred \
  --docker-server=$REGISTRY_URL \
  --docker-username=$REGISTRY_USERNAME \
  --docker-password=$REGISTRY_PASSWORD \
  -n aspice

echo "✓ Registry secret created"

# =============================================================================
# STEP 4: UPDATE k8s-deployment.yaml WITH YOUR REGISTRY URL
# =============================================================================
# Before running kubectl apply, update k8s-deployment.yaml:
# Find line with: image: REGISTRY_URL/aspice-api:latest
# Replace REGISTRY_URL with your actual registry URL

# Mac/Linux:
sed -i "s|REGISTRY_URL|$REGISTRY_URL|g" k8s-deployment.yaml

# Windows (PowerShell):
# (Get-Content k8s-deployment.yaml) -replace 'REGISTRY_URL', $REGISTRY_URL | Set-Content k8s-deployment.yaml

# =============================================================================
# STEP 5: DEPLOY TO KUBERNETES
# =============================================================================

# Apply all Kubernetes resources (namespace, PVC, service, deployment)
kubectl apply -f k8s-deployment.yaml

echo "Waiting for deployment to be ready..."
# Wait for pods to be ready (timeout after 5 minutes)
kubectl wait --for=condition=ready pod -l app=aspice-api -n aspice --timeout=300s

# Check status
echo "Pod status:"
kubectl get pods -n aspice

echo "Persistent volume status:"
kubectl get pvc -n aspice

echo "Service status:"
kubectl get svc -n aspice

# =============================================================================
# STEP 6: VERIFY DEPLOYMENT (PORT FORWARD & TEST)
# =============================================================================

echo "
✓ Deployment successful!

To access the API locally:
  kubectl port-forward -n aspice svc/aspice-api 8000:8000

Then open: http://localhost:8000/docs

To watch logs:
  kubectl logs -n aspice -l app=aspice-api -f
"

# =============================================================================
# COMMON COMMANDS AFTER DEPLOYMENT
# =============================================================================

# View all pods in aspice namespace
# kubectl get pods -n aspice

# View logs from all API pods
# kubectl logs -n aspice -l app=aspice-api -f

# View logs from a specific pod
# kubectl logs -n aspice aspice-api-5f7c8d9b5f-abc12

# Shell into a pod for debugging
# kubectl exec -it -n aspice aspice-api-5f7c8d9b5f-abc12 -- /bin/bash

# Scale to different number of replicas
# kubectl scale deployment aspice-api -n aspice --replicas=5

# Deploy a new version
# docker build -t $REGISTRY_URL/aspice-api:v2 .
# docker push $REGISTRY_URL/aspice-api:v2
# kubectl set image deployment/aspice-api -n aspice aspice-api=$REGISTRY_URL/aspice-api:v2 --record

# Watch deployment rollout
# kubectl rollout status deployment/aspice-api -n aspice

# Rollback to previous version
# kubectl rollout undo deployment/aspice-api -n aspice

# Delete everything
# kubectl delete -f k8s-deployment.yaml

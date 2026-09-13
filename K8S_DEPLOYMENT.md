# Kubernetes Deployment Guide for ASPICE Analyzer

## Overview

This guide walks you through deploying the ASPICE API on your self-hosted Kubernetes cluster with:
- **3 replicas** of the service (HA + load balancing)
- **Zero-downtime deployments** (rolling updates)
- **Health checks** (auto-restart on crash)
- **Resource limits** (fair cluster sharing)

---

## Prerequisites

1. **kubectl access** to your Kubernetes cluster
   ```bash
   kubectl cluster-info  # Verify access
   ```

2. **Docker registry access** (to push the container image)
   - Docker installed locally
   - Access to your container registry (Docker Hub, Harbor, private registry, etc.)

3. **Current directory:** Repo root (contains `Dockerfile`, `k8s-deployment.yaml`)

---

## Step 1: Build the Docker Image

Build the container image locally:

```bash
# From repo root
docker build -t REGISTRY_URL/aspice-api:latest .
```

**Replace `REGISTRY_URL` with your private registry** (e.g., `registry.company.com`, `harbor.internal:5000`)

**Expected output:**
```
Step 1/8 : FROM python:3.12-slim
Step 2/8 : WORKDIR /app
...
Step 8/8 : CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
Successfully tagged REGISTRY_URL/aspice-api:latest
```

---

## Step 2: Push Image to Your Private Registry

### 2a. Authenticate with your private registry:

```bash
# Login to your private registry (you'll be prompted for credentials)
docker login REGISTRY_URL

# Example for Harbor:
docker login registry.company.com
```

**Save credentials safely** — Docker stores them in `~/.docker/config.json`

### 2b. Push the image:

```bash
docker push REGISTRY_URL/aspice-api:latest
```

### 2c. Create Kubernetes secret for registry auth:

Kubernetes needs credentials to pull from your private registry:

```bash
kubectl create secret docker-registry regcred \
  --docker-server=REGISTRY_URL \
  --docker-username=YOUR_USERNAME \
  --docker-password=YOUR_PASSWORD \
  --docker-email=your.email@company.com \
  -n aspice
```

### 2d. Update `k8s-deployment.yaml`:

In the Deployment spec, add:
```yaml
spec:
  imagePullSecrets:
    - name: regcred
  containers:
    - name: aspice-api
      image: REGISTRY_URL/aspice-api:latest  # Update this
```

---

## Step 3: Configure Storage (Optional)

Check if your cluster has a default StorageClass:

```bash
kubectl get storageclasses
```

If needed, update the `storageClassName` in `k8s-deployment.yaml`:

```yaml
spec:
  storageClassName: "your-storage-class"  # Or leave as "" for default
```

---

## Step 4: Deploy to Kubernetes

```bash
# Deploy all resources (namespace, PVC, service, deployment)
kubectl apply -f k8s-deployment.yaml

# Verify all pods are running and PVC is bound
kubectl get pods -n aspice
kubectl get pvc -n aspice
kubectl get svc -n aspice
```

**Expected output:**
```
NAME                          READY   STATUS    RESTARTS   AGE
aspice-api-5f7c8d9b5f-abc12   1/1     Running   0          20s
aspice-api-5f7c8d9b5f-def45   1/1     Running   0          15s
aspice-api-5f7c8d9b5f-ghi78   1/1     Running   0          10s

NAME                STATUS   VOLUME                                     CAPACITY   ACCESSMODES   STORAGECLASS   AGE
aspice-api-data     Bound    pvc-12345678-1234-1234-1234-123456789012   5Gi        RWO            standard       30s

NAME         TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)    AGE
aspice-api   ClusterIP   10.96.123.456   <none>        8000/TCP   30s
```

---

## Step 5: Access the API

### From within the cluster:
```bash
# Pod-to-service DNS
curl http://aspice-api.aspice.svc.cluster.local:8000/health

# Swagger UI
kubectl port-forward -n aspice svc/aspice-api 8000:8000
# Then open http://localhost:8000/docs
```

### From outside the cluster:
If you need external access, change the Service type to `LoadBalancer`:

```bash
kubectl patch svc aspice-api -n aspice -p '{"spec": {"type": "LoadBalancer"}}'
```

Then find the external IP:
```bash
kubectl get svc -n aspice aspice-api
```

---

## Step 6: Monitor & Troubleshoot

### Check pod status:
```bash
kubectl get pods -n aspice -o wide
kubectl describe pod <pod-name> -n aspice
```

### View logs:
```bash
# All pods
kubectl logs -n aspice -l app=aspice-api --all-containers=true

# Single pod
kubectl logs -n aspice aspice-api-5f7c8d9b5f-abc12

# Follow logs in real-time
kubectl logs -n aspice aspice-api-5f7c8d9b5f-abc12 -f
```

### Check events:
```bash
kubectl get events -n aspice
```

### Shell into a pod (debug):
```bash
kubectl exec -it -n aspice aspice-api-5f7c8d9b5f-abc12 -- /bin/bash
```

### Check persistent data:
```bash
# List files in the persistent volume
kubectl exec -it -n aspice aspice-api-5f7c8d9b5f-abc12 -- ls -la /app/api/db/data

# Verify JSON files are being written
kubectl exec -it -n aspice aspice-api-5f7c8d9b5f-abc12 -- find /app/api/db/data -type f
```

---

## Step 7: Deploy Updates (Zero-Downtime)

When you have a new version:

```bash
# 1. Build new image
docker build -t aspice-api:v2 .

# 2. Push to registry
docker push aspice-api:v2

# 3. Update deployment to use new image
kubectl set image deployment/aspice-api -n aspice \
  aspice-api=aspice-api:v2 --record

# 4. Watch the rolling update
kubectl rollout status deployment/aspice-api -n aspice

# 5. If something goes wrong, rollback instantly
kubectl rollout undo deployment/aspice-api -n aspice
kubectl rollout status deployment/aspice-api -n aspice
```

**What happens during update:**
1. K8s starts 1 new pod with v2 (maxSurge: 1)
2. Load balancer still sends traffic to v1 pods
3. Once v2 pod is healthy, K8s terminates 1 v1 pod
4. Repeats until all 3 pods are v2
5. **Result:** Zero downtime, no requests dropped

---

## Step 8: Scale Up/Down

```bash
# Scale to 5 replicas
kubectl scale deployment aspice-api -n aspice --replicas=5

# Scale back to 3
kubectl scale deployment aspice-api -n aspice --replicas=3

# Auto-scaling (requires metrics-server)
kubectl autoscale deployment aspice-api -n aspice --min=3 --max=10 --cpu-percent=80
```

---

## Step 9: Clean Up (If Needed)

```bash
# Delete all resources
kubectl delete -f k8s-deployment.yaml

# Or delete just the namespace (cascades)
kubectl delete namespace aspice
```

---

## Environment Variables Reference

Edit `k8s-deployment.yaml` ConfigMap to customize:

| Variable | Default | Purpose |
|---|---|---|
| `API_DB_BACKEND` | `json` | Use persistent JSON backend |
| `JOB_MAX_CONCURRENCY` | `2` | Max parallel analysis jobs |
| `SUBPROCESS_TIMEOUT` | `0` | Timeout for analysis (0 = no limit, adjust if needed) |
| `ANALYZER_REPO_ROOT` | auto-detect | Path to repo (usually already set) |
| `ANALYZER_WORKSPACES_DIR` | `./workspaces/` | Temp dir for analysis runs |

**To add more env vars:**
```yaml
data:
  API_DB_BACKEND: "json"
  MY_NEW_VAR: "value"  # Add here
```

Then redeploy:
```bash
kubectl apply -f k8s-deployment.yaml
kubectl rollout restart deployment/aspice-api -n aspice
```

---

## Health Checks Explained

The deployment includes **3 types of checks:**

1. **Liveness probe** (every 10 sec):
   - Checks `GET /health`
   - If fails 3 times → **kills and restarts pod**
   - Recovers from hung/crashed processes

2. **Readiness probe** (every 5 sec):
   - Checks `GET /health`
   - If fails 2 times → **removes from load balancer**
   - Pod restarts without losing traffic to other pods

3. **Docker HEALTHCHECK**:
   - Container-level health check
   - Used by Docker/K8s for quick status

---

## FAQ

### Q: Where does the API persist data?
A: Using the JSON backend with a PersistentVolume. JSON files are stored in `/app/api/db/data/` and survive pod restarts.

### Q: What happens when a pod is evicted or crashes?
A: Kubernetes automatically restarts it. The PersistentVolume keeps the JSON data, so nothing is lost.

### Q: Can I scale beyond 3 replicas?
A: Yes. Update `replicas: 3` in `k8s-deployment.yaml`, or use:
```bash
kubectl scale deployment aspice-api -n aspice --replicas=5
```

### Q: How do I back up the data?
A: Copy the persistent data from the pod:
```bash
kubectl cp aspice/aspice-api-xxx:/app/api/db/data ./data-backup
```

### Q: Can I upgrade to PostgreSQL later?
A: Yes. Implement a PostgreSQL adapter in `api/db/postgres.py`, migrate data, then update `API_DB_BACKEND=postgres`.

### Q: Can I use a different private registry?
A: Yes. Update the `image:` field and create a `regcred` secret with your registry credentials.

### Q: What if a pod runs out of memory?
A: K8s will evict it. Increase `limits.memory` in the Deployment if this happens frequently.

### Q: How do I see resource usage?
A: Requires metrics-server:
```bash
kubectl top nodes
kubectl top pods -n aspice
```

---

## Quick Cheat Sheet

```bash
# Deploy
kubectl apply -f k8s-deployment.yaml

# Check status
kubectl get pods -n aspice
kubectl logs -n aspice -l app=aspice-api -f

# Update image
kubectl set image deployment/aspice-api -n aspice aspice-api=aspice-api:v2 --record

# Rollback
kubectl rollout undo deployment/aspice-api -n aspice

# Scale
kubectl scale deployment aspice-api -n aspice --replicas=5

# Port forward (local access)
kubectl port-forward -n aspice svc/aspice-api 8000:8000

# Tail logs
kubectl logs -n aspice -f -l app=aspice-api

# Delete all
kubectl delete -f k8s-deployment.yaml
```

---

## Next Steps

1. **Test the deployment** with actual load from your projects
2. **Monitor resource usage** — adjust CPU/memory limits as needed
3. **Configure external access** — expose via Ingress or LoadBalancer if needed
4. **Set up monitoring** — Prometheus/Grafana for metrics
5. **Plan incident response** — document how to debug/rollback in production

---

**You now have:**
- ✅ 3-instance HA service (high availability)
- ✅ Zero-downtime deployments (rolling updates)
- ✅ Auto-recovery from crashes (health checks + restarts)
- ✅ Load balancing (K8s Service)
- ✅ Easy scaling (kubectl scale)

This solves your "high incidents + high deployment frequency + no downtime" problem.

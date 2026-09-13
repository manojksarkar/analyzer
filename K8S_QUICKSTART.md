# Kubernetes Deployment — Quick Start Checklist

## Before You Deploy

### 1. Private Registry Setup
- [ ] Get your registry URL (e.g., `registry.company.com`, `harbor.example.com:5000`)
- [ ] Get registry username & password
- [ ] **Replace `REGISTRY_URL`** in `Dockerfile` and `k8s-deployment.yaml` with your actual URL

### 2. Storage Setup (Optional)
- [ ] Check if your cluster has a default StorageClass:
  ```bash
  kubectl get storageclasses
  ```
- [ ] If needed, update `storageClassName` in `k8s-deployment.yaml`
  - Leave as `""` to use default
  - Or specify a named StorageClass (ask your cluster admin)

---

## Deployment Steps (In Order)

### Step 1: Build & Push Image
```bash
# Build
docker build -t REGISTRY_URL/aspice-api:latest .

# Login to registry (if needed)
docker login REGISTRY_URL

# Push
docker push REGISTRY_URL/aspice-api:latest
```

### Step 2: Create Registry Secret
```bash
kubectl create secret docker-registry regcred \
  --docker-server=REGISTRY_URL \
  --docker-username=YOUR_USERNAME \
  --docker-password=YOUR_PASSWORD \
  -n aspice
```

### Step 3: Deploy Everything
```bash
# Apply all resources (namespace, persistent storage, API, service)
kubectl apply -f k8s-deployment.yaml

# Check all pods are running (wait ~30 sec for PVC to bind)
kubectl get pods -n aspice
kubectl get pvc -n aspice
```

### Step 4: Test
```bash
# Port-forward to access API locally
kubectl port-forward -n aspice svc/aspice-api 8000:8000

# Open browser: http://localhost:8000/docs (Swagger UI)
# Or test health: curl http://localhost:8000/health
```

---

## What You Get

✅ **3 replicas** of the API service (HA + load balancing)
✅ **Persistent JSON backend** (data survives pod restarts)
✅ **Zero-downtime deployments** (rolling updates)
✅ **Auto-recovery** (health checks + auto-restart on crash)
✅ **Private registry support** (pulls from your company registry)

---

## Next Steps

1. **Monitor logs**
   ```bash
   kubectl logs -n aspice -l app=aspice-api -f
   kubectl logs -n aspice postgres-0 -f
   ```

3. **Deploy new versions**
   ```bash
   docker build -t REGISTRY_URL/aspice-api:v2 .
   docker push REGISTRY_URL/aspice-api:v2
   kubectl set image deployment/aspice-api -n aspice aspice-api=REGISTRY_URL/aspice-api:v2
   ```

4. **Backup JSON data** (optional)
   ```bash
   kubectl cp aspice/aspice-api-xxx:/app/api/db/data ./data-backup
   ```

---

## Troubleshooting

### Pods not starting?
```bash
kubectl describe pod aspice-api-xxx -n aspice
kubectl logs aspice-api-xxx -n aspice
```

### Can't pull image?
- Check registry credentials: `kubectl get secret regcred -n aspice`
- Check image URL in deployment: `kubectl get deployment aspice-api -n aspice -o yaml`

### PersistentVolume not binding?
```bash
# Check PVC status
kubectl describe pvc aspice-api-data -n aspice

# Check available storage classes
kubectl get storageclasses
```

---

**Full guide:** See `K8S_DEPLOYMENT.md` for detailed instructions.

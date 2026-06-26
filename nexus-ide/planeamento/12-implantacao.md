# NEXUS IDE — Deployment Detalhado

## 1. Visão Geral do Deployment

Deployment de NEXUS IDE envolve múltiplos ambientes (development, staging, production), estratégias de orquestração (Docker Compose, Kubernetes), e considerações de infraestrutura (hardware, rede, segurança). Este documento detalha como deployar NEXUS IDE em diferentes cenários.

### 1.1 Ambientes

```
┌─────────────────────────────────────────────────────────────┐
│                   Deployment Environments                   │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ Development │  │   Staging    │  │  Production  │      │
│  │              │  │              │  │              │      │
│  │ Local        │  │ Cloud (VPS)  │  │ Cloud (VPS)  │      │
│  │ Docker       │  │ Docker       │  │ Docker       │      │
│  │ Compose      │  │ Compose      │  │ Kubernetes   │      │
│  │ Hot reload   │  │ No reload    │  │ No reload    │      │
│  │ Mock data    │  │ Real data    │  │ Real data    │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 Estratégias de Deployment

| Estratégia | Quando Usar | Vantagens | Desvantagens |
|------------|-------------|-----------|--------------|
| Docker Compose | Development, pequeno scale | Simples, fácil de usar | Não escala horizontalmente |
| Kubernetes | Production, grande scale | Escalabilidade, alta disponibilidade | Complexo, overhead |
| Docker Swarm | Médio scale | Mais simples que K8s | Menos features que K8s |
| Serverless (AWS Lambda) | Baixo scale, intermitente | Pay-per-use, zero maintenance | Cold starts, limitações |

## 2. Deployment Local (Development)

### 2.1 Docker Compose

**docker-compose.yml:**

```yaml
version: '3.8'

services:
  # Backend
  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    environment:
      - OLLAMA_HOST=http://ollama:11434
      - REDIS_URL=redis://redis:6379
      - BRAVE_API_KEY=${BRAVE_API_KEY}
    volumes:
      - ./backend:/app
      - ./config:/app/config
    depends_on:
      - ollama
      - redis
    command: uvicorn orchestrator.main:app --host 0.0.0.0 --port 8000 --reload

  # Frontend
  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    ports:
      - "3000:3000"
    environment:
      - NEXT_PUBLIC_API_URL=http://localhost:8000
    volumes:
      - ./frontend:/app
      - /app/node_modules
      - /app/.next
    depends_on:
      - backend
    command: npm run dev

  # Ollama
  ollama:
    image: ollama/ollama:latest
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

  # Ollama Dashboard (separate instance)
  ollama-dashboard:
    image: ollama/ollama:latest
    ports:
      - "11435:11434"
    volumes:
      - ollama_dashboard_data:/root/.ollama
    command: ollama serve --port 11435
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

  # Redis
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes

  # Prometheus
  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"
    volumes:
      - ./config/prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus_data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'

  # Grafana
  grafana:
    image: grafana/grafana:latest
    ports:
      - "3001:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    volumes:
      - grafana_data:/var/lib/grafana
      - ./config/grafana/dashboards:/etc/grafana/provisioning/dashboards
    depends_on:
      - prometheus

  # Jaeger (tracing)
  jaeger:
    image: jaegertracing/all-in-one:latest
    ports:
      - "16686:16686"
      - "14268:14268"
    environment:
      - COLLECTOR_ZIPKIN_HOST_PORT=:9411

volumes:
  ollama_data:
  ollama_dashboard_data:
  redis_data:
  prometheus_data:
  grafana_data:
```

### 2.2 Comandos de Deployment

```bash
# Build e start
docker-compose up --build

# Start em background
docker-compose up -d

# Ver logs
docker-compose logs -f backend

# Stop
docker-compose down

# Stop e remove volumes
docker-compose down -v
```

### 2.3 Por que Docker Compose para Development?

- **Simples:** Fácil de usar, YAML simples
- **Reproducible:** Mesmo ambiente em todas as máquinas
- **Hot reload:** Suporta hot reload para desenvolvimento rápido
- **Multi-container:** Orquestra múltiplos containers facilmente
- **Volume mounting:** Permite editar código localmente

## 3. Deployment em Staging

### 3.1 VPS Configuration

**Hardware recomendado:**
- **CPU:** 4 cores (AMD Ryzen 5 5600X ou similar)
- **RAM:** 32GB DDR4
- **GPU:** RTX 3060 12GB ou RTX 4070 12GB
- **Storage:** 1TB NVMe SSD
- **OS:** Ubuntu 22.04 LTS

**Por que este hardware?**
- **CPU:** 4 cores suficientes para backend + frontend + Ollama
- **RAM:** 32GB permite rodar múltiplos modelos simultaneamente
- **GPU:** RTX 3060/4070 tem 12GB VRAM (suficiente para EXPERT 32b com quantização)
- **Storage:** 1TB NVMe é rápido e suficiente para código + modelos

### 3.2 Setup do Servidor

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Install NVIDIA drivers (se GPU)
sudo apt install nvidia-driver-535 -y

# Install NVIDIA Container Toolkit
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | sudo tee /etc/apt/sources.list.d/nvidia-docker.list
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

# Install UFW firewall
sudo apt install ufw -y
sudo ufw allow 22/tcp   # SSH
sudo ufw allow 80/tcp   # HTTP
sudo ufw allow 443/tcp  # HTTPS
sudo ufw allow 8000/tcp # Backend
sudo ufw allow 3000/tcp # Frontend
sudo ufw enable

# Clone repository
git clone https://github.com/yourusername/nexus-ide.git
cd nexus-ide

# Set environment variables
cp .env.example .env
nano .env  # Edit with your values

# Deploy
docker-compose up -d
```

### 3.3 Reverse Proxy (Nginx)

**nginx.conf:**

```nginx
server {
    listen 80;
    server_name staging.nexus-ide.com;

    # Frontend
    location / {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }

    # Backend API
    location /api/ {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }

    # SSE streaming
    location /api/chat/stream {
        proxy_pass http://localhost:8000/api/chat/stream;
        proxy_http_version 1.1;
        proxy_set_header Connection '';
        proxy_buffering off;
        proxy_cache off;
        chunked_transfer_encoding off;
    }

    # Dashboard (Grafana)
    location /grafana/ {
        proxy_pass http://localhost:3001/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
    }
}
```

**Por que Nginx?**
- **Performance:** Nginx é extremamente rápido
- **Reverse proxy:** Suporta WebSocket, SSE
- **SSL/TLS:** Fácil configurar HTTPS
- **Load balancing:** Pode fazer load balancing para múltiplas instâncias

### 3.4 SSL/TLS (Let's Encrypt)

```bash
# Install Certbot
sudo apt install certbot python3-certbot-nginx -y

# Obtain certificate
sudo certbot --nginx -d staging.nexus-ide.com

# Auto-renewal (automático)
sudo certbot renew --dry-run
```

## 4. Deployment em Production

### 4.1 Kubernetes Deployment

**Por que Kubernetes?**
- **Escalabilidade:** Horizontal scaling automático
- **Alta disponibilidade:** Self-healing, rolling updates
- **Resource management:** Limits e requests por pod
- **Multi-cluster:** Pode deploy em múltiplas regiões

### 4.2 Kubernetes Manifests

**backend-deployment.yaml:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nexus-backend
  labels:
    app: nexus-backend
spec:
  replicas: 3
  selector:
    matchLabels:
      app: nexus-backend
  template:
    metadata:
      labels:
        app: nexus-backend
    spec:
      containers:
      - name: backend
        image: nexuside/backend:latest
        ports:
        - containerPort: 8000
        env:
        - name: OLLAMA_HOST
          valueFrom:
            configMapKeyRef:
              name: nexus-config
              key: ollama-host
        - name: REDIS_URL
          valueFrom:
            configMapKeyRef:
              name: nexus-config
              key: redis-url
        resources:
          requests:
            cpu: "1"
            memory: "2Gi"
          limits:
            cpu: "2"
            memory: "4Gi"
        volumeMounts:
        - name: config
          mountPath: /app/config
      volumes:
      - name: config
        configMap:
          name: nexus-config
---
apiVersion: v1
kind: Service
metadata:
  name: nexus-backend-service
spec:
  selector:
    app: nexus-backend
  ports:
  - protocol: TCP
    port: 8000
    targetPort: 8000
  type: ClusterIP
```

**frontend-deployment.yaml:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nexus-frontend
  labels:
    app: nexus-frontend
spec:
  replicas: 2
  selector:
    matchLabels:
      app: nexus-frontend
  template:
    metadata:
      labels:
        app: nexus-frontend
    spec:
      containers:
      - name: frontend
        image: nexuside/frontend:latest
        ports:
        - containerPort: 3000
        env:
        - name: NEXT_PUBLIC_API_URL
          value: "http://nexus-backend-service:8000"
        resources:
          requests:
            cpu: "0.5"
            memory: "1Gi"
          limits:
            cpu: "1"
            memory: "2Gi"
---
apiVersion: v1
kind: Service
metadata:
  name: nexus-frontend-service
spec:
  selector:
    app: nexus-frontend
  ports:
  - protocol: TCP
    port: 3000
    targetPort: 3000
  type: LoadBalancer
```

**ollama-deployment.yaml:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ollama
  labels:
    app: ollama
spec:
  replicas: 1
  selector:
    matchLabels:
      app: ollama
  template:
    metadata:
      labels:
      - app: ollama
    spec:
      containers:
      - name: ollama
        image: ollama/ollama:latest
        ports:
        - containerPort: 11434
        resources:
          limits:
            nvidia.com/gpu: 1
        volumeMounts:
        - name: models
          mountPath: /root/.ollama
      volumes:
      - name: models
        persistentVolumeClaim:
          claimName: ollama-models-pvc
      nodeSelector:
        gpu: "true"
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ollama-models-pvc
spec:
  accessModes:
  - ReadWriteOnce
  resources:
    requests:
      storage: 100Gi
```

### 4.3 Horizontal Pod Autoscaler

**hpa.yaml:**

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: nexus-backend-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: nexus-backend
  minReplicas: 3
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
```

### 4.4 Ingress (NGINX Ingress Controller)

**ingress.yaml:**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: nexus-ingress
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - nexus-ide.com
    secretName: nexus-tls
  rules:
  - host: nexus-ide.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: nexus-frontend-service
            port:
              number: 3000
      - path: /api
        pathType: Prefix
        backend:
          service:
            name: nexus-backend-service
            port:
              number: 8000
```

## 5. Monitoring em Produção

### 5.1 Prometheus + Grafana

**Configuração Prometheus:**

```yaml
# prometheus.yml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'nexus-backend'
    kubernetes_sd_configs:
    - role: pod
      namespaces:
        names:
        - default
    relabel_configs:
    - source_labels: [__meta_kubernetes_pod_label_app]
      action: keep
      regex: nexus-backend
    - source_labels: [__meta_kubernetes_pod_ip]
      target_label: __address__
      replacement: $1:8000

  - job_name: 'nexus-frontend'
    kubernetes_sd_configs:
    - role: pod
      namespaces:
        names:
        - default
    relabel_configs:
    - source_labels: [__meta_kubernetes_pod_label_app]
      action: keep
      regex: nexus-frontend
    - source_labels: [__meta_kubernetes_pod_ip]
      target_label: __address__
      replacement: $1:3000

  - job_name: 'kubernetes-nodes'
    kubernetes_sd_configs:
    - role: node
```

### 5.2 Alertmanager

**alertmanager.yml:**

```yaml
global:
  resolve_timeout: 5m
  slack_api_url: ${SLACK_WEBHOOK_URL}

route:
  group_by: ['alertname', 'severity']
  group_wait: 10s
  group_interval: 10s
  repeat_interval: 12h
  receiver: 'slack-notifications'

receivers:
- name: 'slack-notifications'
  slack_configs:
  - api_url: ${SLACK_WEBHOOK_URL}
    channel: '#nexus-alerts'
```

## 6. Backup e Restore

### 6.1 Estratégia de Backup

**O que backupar:**
- **Código:** Git repository (GitHub)
- **Configuração:** ConfigMaps, Secrets
- **Dados:** Redis (RDB), ChromaDB, Ollama models
- **Logs:** Prometheus TSDB

**Frequência:**
- **Código:** Continuous (Git)
- **Configuração:** Diário (automated)
- **Dados:** Diário (automated)
- **Logs:** Semanal (retention 30 dias)

### 6.2 Script de Backup

```bash
#!/bin/bash
# backup.sh

DATE=$(date +%Y%m%d)
BACKUP_DIR="/backups/$DATE"

mkdir -p $BACKUP_DIR

# Backup Redis
kubectl exec -it redis-0 -- redis-cli BGSAVE
kubectl cp redis-0:/data/dump.rdb $BACKUP_DIR/redis-dump.rdb

# Backup ChromaDB
kubectl cp chromadb-0:/chroma/chroma.sqlite3 $BACKUP_DIR/chromadb.sqlite3

# Backup ConfigMaps
kubectl get configmaps -o yaml > $BACKUP_DIR/configmaps.yaml

# Backup Secrets (encrypted)
kubectl get secrets -o yaml > $BACKUP_DIR/secrets.yaml.enc

# Upload to S3
aws s3 sync $BACKUP_DIR s3://nexus-ide-backups/$DATE

# Cleanup old backups (keep 30 days)
find /backups -type d -mtime +30 -exec rm -rf {} \;
```

### 6.3 Script de Restore

```bash
#!/bin/bash
# restore.sh

DATE=$1
BACKUP_DIR="/backups/$DATE"

# Restore Redis
kubectl cp $BACKUP_DIR/redis-dump.rdb redis-0:/data/dump.rdb
kubectl exec -it redis-0 -- redis-cli SHUTDOWN NOSAVE

# Restore ChromaDB
kubectl cp $BACKUP_DIR/chromadb.sqlite3 chromadb-0:/chroma/chroma.sqlite3

# Restore ConfigMaps
kubectl apply -f $BACKUP_DIR/configmaps.yaml

# Restore Secrets
kubectl apply -f $BACKUP_DIR/secrets.yaml.enc
```

## 7. Rollback Strategy

### 7.1 Kubernetes Rollback

```bash
# Rollback deployment
kubectl rollout undo deployment/nexus-backend

# Rollback to specific revision
kubectl rollout undo deployment/nexus-backend --to-revision=3

# Check rollout status
kubectl rollout status deployment/nexus-backend
```

### 7.2 Docker Rollback

```bash
# Stop current
docker-compose down

# Pull previous version
docker pull nexuside/backend:v1.0.0

# Update docker-compose.yml with previous version
# ...

# Start
docker-compose up -d
```

## 8. Disaster Recovery

### 8.1 RPO/RTO

- **RPO (Recovery Point Objective):** 24 horas (perda de dados aceitável)
- **RTO (Recovery Time Objective):** 4 horas (tempo para recuperar)

### 8.2 Plan de Disaster Recovery

1. **Detecção:** Monitorização alerta sobre falha
2. **Avaliação:** Avaliar extensão do dano
3. **Recuperação:** Restore de backup mais recente
4. **Verificação:** Verificar integridade dos dados
5. **Comunicação:** Notificar stakeholders

## 9. Performance Tuning

### 9.1 Ollama Tuning

```bash
# Quantization para reduzir VRAM
ollama pull qwen2.5-coder:32b-q4_K_M

# Context window tuning
ollama run qwen2.5-coder:32b --ctx-size 32768

# Num threads
ollama run qwen2.5-coder:32b --num-thread 4
```

### 9.2 Redis Tuning

```bash
# redis.conf
maxmemory 8gb
maxmemory-policy allkeys-lru
save 900 1
save 300 10
save 60 10000
```

### 9.3 Backend Tuning

```python
# uvicorn command
uvicorn orchestrator.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --loop uvloop \
  --limit-concurrency 100
```

**Por que estes parâmetros?**
- **--workers 4:** 1 worker por core
- **--worker-class uvicorn.workers.UvicornWorker:** Melhor performance
- **--loop uvloop:** uvloop é mais rápido que asyncio
- **--limit-concurrency 100:** Previne overload

## 10. Conclusão

Deployment de NEXUS IDE é desenhado para ser:
- **Simples:** Docker Compose para development
- **Escalável:** Kubernetes para production
- **Seguro:** SSL/TLS, firewall, RBAC
- **Observável:** Prometheus, Grafana, Jaeger
- **Resiliente:** Backups, rollback, disaster recovery

A escolha de estratégia depende do scale:
- **Development:** Docker Compose (simples)
- **Staging:** Docker Compose em VPS (médio)
- **Production:** Kubernetes em cloud (grande)

# XNO Deployment Workflows

Reusable GitHub Actions workflows for building and deploying Docker services to Docker Swarm, with per-environment Traefik routing.

## Architecture

```
Internet
   │
   ▼
[ nginx ]  (external, not in swarm)
   │
   ├─── :8081 ──► [ traefik-dev ]     ──► dev services     (overlay: traefik-dev)
   ├─── :8082 ──► [ traefik-staging ] ──► staging services (overlay: traefik-staging)
   └─── :8083 ──► [ traefik-prod ]    ──► prod services    (overlay: traefik-prod)

Each Traefik instance only sees services on its own overlay network.
Services also share an internal app-net for service-to-service calls.

Docker Swarm Cluster
┌─────────────────────────────────────────────────┐
│  Manager node (runs Traefik + GitHub runner)    │
│  Worker node 1 (role=worker, env=dev)           │
│  Worker node 2 (role=worker, env=staging)       │
│  Worker node 3 (role=worker, env=prod)          │
└─────────────────────────────────────────────────┘
```

## Prerequisites

- Ubuntu 22.04+ (or any Linux with Docker 24+)
- Docker installed on all nodes
- SSH access between manager and workers (for initial setup only)
- Ports open on the manager: `2377` (swarm), `7946` (gossip), `4789` (overlay VXLAN)

---

## Step 1 — Initialize Docker Swarm

Run on the **manager node**:

```bash
docker swarm init --advertise-addr <MANAGER_IP>
```

Get join tokens:

```bash
# For worker nodes
docker swarm join-token worker

# For additional managers (HA setup)
docker swarm join-token manager
```

---

## Step 2 — Add Worker Nodes

Run the join command **on each worker node**:

```bash
docker swarm join --token <WORKER_TOKEN> <MANAGER_IP>:2377
```

Verify from the manager:

```bash
docker node ls
```

---

## Step 3 — Label Nodes

Labels control which services deploy to which nodes.

```bash
# Label workers by role
docker node update --label-add role=worker <NODE_ID>

# Optionally restrict a node to a specific environment
docker node update --label-add env=dev     <NODE_ID>
docker node update --label-add env=staging <NODE_ID>
docker node update --label-add env=prod    <NODE_ID>

# Label the manager
docker node update --label-add role=manager <MANAGER_NODE_ID>
```

View current labels:

```bash
docker node inspect <NODE_ID> --format '{{ json .Spec.Labels }}' | jq
```

**Label strategy examples:**

| Setup | node_label input | Placement |
|---|---|---|
| All workers share all envs | `role == worker` | Any worker |
| Isolated per env | `env == dev` | Only dev-labeled nodes |
| Role + env | `role == worker` + `env == prod` | Use two constraints (see note) |

> **Note:** `node_label` takes a single constraint. For multiple constraints, extend the `docker-compose.yaml` placement section directly.

---

## Step 4 — Create Overlay Networks

Run on the **manager node**:

```bash
# Internal service mesh (all environments share this for service-to-service calls)
docker network create --driver overlay --attachable app-net

# Per-environment Traefik networks (each Traefik only sees services on its own network)
docker network create --driver overlay --attachable traefik-dev
docker network create --driver overlay --attachable traefik-staging
docker network create --driver overlay --attachable traefik-prod
```

For a **fully air-gapped** internal network (no internet egress from containers):

```bash
# Add --internal flag — containers cannot reach the internet
docker network create --driver overlay --internal --attachable app-net
```

Verify:

```bash
docker network ls --filter driver=overlay
```

---

## Step 5 — Deploy Traefik (one per environment)

Each environment gets its own Traefik v3 stack so services are fully isolated.

```bash
# Dev — dashboard at http://manager:8081/dashboard/
RUN_ENV=dev TRAEFIK_PORT=8081 docker stack deploy -c docker-compose.traefik.yml traefik-dev

# Staging — dashboard at http://manager:8082/dashboard/
RUN_ENV=staging TRAEFIK_PORT=8082 docker stack deploy -c docker-compose.traefik.yml traefik-staging

# Prod — dashboard at http://manager:8083/dashboard/ (disable api.insecure in prod)
RUN_ENV=prod TRAEFIK_PORT=8083 docker stack deploy -c docker-compose.traefik.yml traefik-prod
```

Verify:

```bash
docker stack ls
docker service ls
```

### Disable Traefik dashboard in production

Edit `docker-compose.traefik.yml` and remove or replace:

```yaml
- "--api.insecure=true"
```

---

## Step 6 — Configure Nginx (external)

Nginx lives outside the swarm and routes traffic to the correct Traefik by environment.

```nginx
upstream traefik_dev     { server <MANAGER_IP>:8081; }
upstream traefik_staging { server <MANAGER_IP>:8082; }
upstream traefik_prod    { server <MANAGER_IP>:8083; }

# Dev environment
server {
    listen 80;
    server_name dev.yourdomain.com;
    location / {
        proxy_pass         http://traefik_dev;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}

# Staging environment
server {
    listen 80;
    server_name staging.yourdomain.com;
    location / {
        proxy_pass         http://traefik_staging;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}

# Production
server {
    listen 80;
    server_name yourdomain.com;
    location / {
        proxy_pass         http://traefik_prod;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

---

## Step 7 — Set Up GitHub Actions Runners

Each environment needs a **self-hosted runner on the manager node**, labeled with the environment name. The runner must be on the manager because only the manager can run `docker stack deploy`.

### Install a runner (repeat for each environment)

1. Go to your GitHub org → **Settings → Actions → Runners → New self-hosted runner**
2. Follow the install steps. When prompted for labels, add the environment name:

```
Labels: self-hosted,linux,dev        # for the dev runner
Labels: self-hosted,linux,staging    # for the staging runner
Labels: self-hosted,linux,prod       # for the prod runner
```

### Configure env-specific secrets in the systemd service

The runner service file is at:
```
/etc/systemd/system/actions.runner.<org>.<name>-<env>.service
```

Add your environment variables under `[Service]`:

```ini
[Service]
# ... existing lines ...
Environment="POSTGRES_HOST=10.10.1.10"
Environment="POSTGRES_PORT=5432"
Environment="POSTGRES_USER=myuser"
Environment="POSTGRES_PASSWORD=secret"
Environment="KAFKA_SERVERS=10.10.1.20:9092"
Environment="REDIS_HOST=10.10.1.30"
Environment="REDIS_PASSWORD=secret"
```

Reload after editing:

```bash
sudo systemctl daemon-reload
sudo systemctl restart actions.runner.<org>.<name>-<env>.service
```

> Each environment has its own runner service file with its own secrets. No conflicts between envs.

---

## Step 8 — Configure GitHub Secrets

In each **project repository** → **Settings → Secrets and variables → Actions**:

| Secret | Value |
|---|---|
| `GHCR_TOKEN` | GitHub personal access token with `write:packages` scope |

> `GHCR_TOKEN` is the only secret the workflow needs from GitHub. All other env-specific secrets live in the systemd runner service file on the server.

---

## Step 9 — Deploy a Service

### Workflow inputs reference

| Input | Required | Description |
|---|---|---|
| `environment` | yes | `dev`, `staging`, or `prod` |
| `stack` | yes | Docker Swarm stack name |
| `services` | yes | `root` for single service, or `service1,service2` for multi |
| `dockerfiles` | no | Custom Dockerfile path(s), aligned with services |
| `node_label` | no | Swarm placement constraint. Default: `role == worker` |

### Caller workflow examples

**Deploy on push to main → dev:**

```yaml
name: Deploy MyApp — Dev

on:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  deploy:
    uses: vn-fin/xno_deployment_workflows/.github/workflows/workflow-swarm.yml@main
    with:
      environment: dev
      services: root
      stack: myapp
      node_label: "role == worker"
    secrets:
      GHCR_TOKEN: ${{ secrets.GHCR_TOKEN }}
```

**Deploy on push to staging branch:**

```yaml
name: Deploy MyApp — Staging

on:
  push:
    branches: [staging]
  workflow_dispatch:

jobs:
  deploy:
    uses: vn-fin/xno_deployment_workflows/.github/workflows/workflow-swarm.yml@main
    with:
      environment: staging
      services: root
      stack: myapp
      node_label: "env == staging"
    secrets:
      GHCR_TOKEN: ${{ secrets.GHCR_TOKEN }}
```

**Deploy on release → prod:**

```yaml
name: Deploy MyApp — Production

on:
  release:
    types: [published]
  workflow_dispatch:

jobs:
  deploy:
    uses: vn-fin/xno_deployment_workflows/.github/workflows/workflow-swarm.yml@main
    with:
      environment: prod
      services: root
      stack: myapp
      node_label: "env == prod"
    secrets:
      GHCR_TOKEN: ${{ secrets.GHCR_TOKEN }}
```

---

## Docker Compose — Traefik Labels

In swarm mode, Traefik reads labels from the **swarm service**, not the container.
Labels must be under `deploy.labels`:

```yaml
deploy:
  labels:
    - "traefik.enable=true"
    # ${RUN_ENV} makes the router name unique per environment — no collisions
    - "traefik.http.routers.myapp_${RUN_ENV}.rule=PathPrefix(`/myapp`)"
    - "traefik.http.routers.myapp_${RUN_ENV}.entrypoints=web"
    - "traefik.http.services.myapp_${RUN_ENV}.loadbalancer.server.port=3000"
```

The service must also connect to the `traefik-${RUN_ENV}` network so the correct Traefik instance can discover it:

```yaml
networks:
  traefik-net:
    external: true
    name: traefik-${RUN_ENV}    # dev → traefik-dev, staging → traefik-staging, etc.
```

---

## Internet Access Control

| Network | Internet egress | Use for |
|---|---|---|
| `app-net` (regular overlay) | Yes (via host NAT) | Services that call external APIs |
| `app-net` with `--internal` | No | Fully isolated services |
| `traefik-${RUN_ENV}` | Inbound only via Traefik | Frontend-facing services |

To make a service completely offline after deploy:
1. Create `app-net` with `--internal`
2. Only connect the service to `app-net` (not `traefik-net`)

---

## Automated Setup

Run the setup script on the manager node to perform steps 1–5 automatically:

```bash
git clone https://github.com/vn-fin/xno_deployment_workflows.git
cd xno_deployment_workflows
chmod +x scripts/setup-swarm.sh
./scripts/setup-swarm.sh
```

The script will:
- Initialize the swarm
- Print worker join tokens
- Guide you through labeling nodes interactively
- Create all overlay networks
- Deploy Traefik for dev, staging, and prod
- Print the nginx config snippet

---

## Useful Commands

```bash
# List all stacks
docker stack ls

# List services in a stack
docker stack services hello

# View service logs
docker service logs hello_api --follow

# Scale a service
docker service scale hello_api=3

# Redeploy a single service (rolling update)
docker service update --force hello_api

# Remove a stack
docker stack rm hello

# Inspect node labels
docker node ls -q | xargs docker node inspect --format '{{.Description.Hostname}}: {{json .Spec.Labels}}'
```

# XNO Deployment Workflows

Reusable GitHub Actions workflows for building and deploying Docker services to Docker Swarm, with per-environment Traefik routing.

## Architecture

```
                         ┌──────────────┐
                         │   Internet   │
                         └──────┬───────┘
                                │
                                ▼
                       ┌────────────────┐
                       │     nginx      │
                       │ (external)     │
                       └──────┬─────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
  :8081 HTTP            :8082 HTTP            :8083 HTTP
  :50051 gRPC           :50052 gRPC           :50053 gRPC
        │                     │                     │
        ▼                     ▼                     ▼
 ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
 │ traefik-dev  │     │traefik-stg   │     │ traefik-prod │
 └──────┬───────┘     └──────┬───────┘     └──────┬───────┘
        │                     │                     │
        ▼                     ▼                     ▼
   Dev Services         Staging Services        Prod Services
 (overlay: dev)       (overlay: staging)     (overlay: prod)

        └───────────────┬───────────────────────┘
                        │
                 Shared internal
                    app-net


==============================================================
                DOCKER SWARM CLUSTER
==============================================================

 ┌──────────────────────────────────────────────────────────┐
 │ Manager Node                                             │
 │ - Traefik instances                                      │
 │ - GitHub Runner                                          │
 │                                                          │
 │ Worker Nodes (role=worker)                               │
 ├──────────────────────────────────────────────────────────┤
 │                                                          │
 │  STACK: hello-dev                                        │
 │                                                          │
 │   ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐         │
 │   │ api01  │  │ api02  │  │ grpc01 │  │ grpc02 │         │
 │   │ x1..4  │  │ x1..4  │  │ x1..4  │  │ x1..4  │         │
 │   └────┬───┘  └────┬───┘  └────┬───┘  └────┬───┘         │
 │        └───────────┴───────────┴───────────┘             │
 │                 traefik-dev + app-net                    │
 │                                                          │
 │  STACK: hello-staging (same layout, traefik-staging)     │
 │  STACK: hello-prod    (same layout, traefik-prod)        │
 │                                                          │
 └──────────────────────────────────────────────────────────┘


======================== ROUTING ==============================

HTTP:
  /hello-api-01  ───► api01 (replicas 1–4)
  /hello-api-02  ───► api02 (replicas 1–4)

gRPC:
  /hello01.HelloService01/* ───► grpc01 (replicas 1–4)
  /hello02.HelloService02/* ───► grpc02 (replicas 1–4)
  /grpc.reflection/*        ───► grpc01
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
# Dev — HTTP :8081, gRPC :50051
RUN_ENV=dev TRAEFIK_PORT=8081 TRAEFIK_GRPC_PORT=50051 \
  docker stack deploy -c docker-compose.traefik.yml traefik-dev

# Staging — HTTP :8082, gRPC :50052
RUN_ENV=staging TRAEFIK_PORT=8082 TRAEFIK_GRPC_PORT=50052 \
  docker stack deploy -c docker-compose.traefik.yml traefik-staging

# Prod — HTTP :8083, gRPC :50053 (disable api.insecure in prod)
RUN_ENV=prod TRAEFIK_PORT=8083 TRAEFIK_GRPC_PORT=50053 \
  docker stack deploy -c docker-compose.traefik.yml traefik-prod
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

---

## Step 6 — Set Up GitHub Actions Runners

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

## Step 7 — Configure GitHub Secrets

In each **project repository** → **Settings → Secrets and variables → Actions**:

| Secret | Value |
|---|---|
| `GHCR_TOKEN` | GitHub personal access token with `write:packages` scope |

> `GHCR_TOKEN` is the only secret the workflow needs from GitHub. All other env-specific secrets live in the systemd runner service file on the server.

---

## Step 8 — Deploy a Service

### Workflow inputs reference

| Input | Required | Description |
|---|---|---|
| `environment` | yes | `dev`, `staging`, or `prod` |
| `stack` | yes | Docker Swarm stack name |
| `services` | yes | `root` for single service, or `service1,service2` for multi |
| `dockerfiles` | no | Custom Dockerfile path(s), aligned with services |
| `node_label` | no | Swarm placement constraint. Default: `role == worker` |
| `build_args` | no | Newline-separated `KEY=VALUE` pairs passed as `--build-arg` to docker build |

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
    uses: vn-fin/xno_deployment_workflows/.github/workflows/new-worflow-swarm.yml@main
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
    uses: vn-fin/xno_deployment_workflows/.github/workflows/new-worflow-swarm.yml@main
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
    uses: vn-fin/xno_deployment_workflows/.github/workflows/new-worflow-swarm.yml@main
    with:
      environment: prod
      services: root
      stack: myapp
      node_label: "env == prod"
    secrets:
      GHCR_TOKEN: ${{ secrets.GHCR_TOKEN }}
```

**Deploy with build args (e.g. Vite frontend):**

```yaml
name: Deploy Web — Dev

on:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  deploy:
    uses: vn-fin/xno_deployment_workflows/.github/workflows/new-worflow-swarm.yml@main
    with:
      environment: dev
      services: root
      stack: xweb
      build_args: |
        VITE_API_BASE_URL=https://public.dev.xno.vn
        VITE_SOCKET_URL=wss://public.dev.xno.vn
    secrets:
      GHCR_TOKEN: ${{ secrets.GHCR_TOKEN }}
```

> **Note:** Build args are baked into the image at build time. In the Dockerfile, use `ARG` to receive them and `ENV` to persist them at runtime:
> ```dockerfile
> ARG VITE_API_BASE_URL=https://default.example.com
> ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
> ```

---

## Docker Compose — Traefik Labels

In swarm mode, Traefik reads labels from the **swarm service**, not the container.
Labels must be under `deploy.labels`:

**HTTP service:**

```yaml
deploy:
  labels:
    - "traefik.enable=true"
    - "traefik.env=${RUN_ENV}"
    - "traefik.http.routers.myapp_${RUN_ENV}.rule=PathPrefix(`/myapp`)"
    - "traefik.http.routers.myapp_${RUN_ENV}.entrypoints=web"
    - "traefik.http.services.myapp_${RUN_ENV}.loadbalancer.server.port=3000"
```

**Single gRPC service (catch-all):**

```yaml
deploy:
  labels:
    - "traefik.enable=true"
    - "traefik.env=${RUN_ENV}"
    - "traefik.http.routers.myapp_grpc_${RUN_ENV}.rule=PathPrefix(`/`)"
    - "traefik.http.routers.myapp_grpc_${RUN_ENV}.entrypoints=grpc"
    - "traefik.http.services.myapp_grpc_${RUN_ENV}.loadbalancer.server.port=50051"
    - "traefik.http.services.myapp_grpc_${RUN_ENV}.loadbalancer.server.scheme=h2c"
```

**Multiple gRPC services (route by package path):**

Each gRPC service gets a `PathPrefix` matching its proto package + service name. One service also handles the reflection path so `grpcurl list` works.

```yaml
# grpc01 — handles hello01.HelloService01 + reflection
grpc01:
  deploy:
    labels:
      - "traefik.enable=true"
      - "traefik.env=${RUN_ENV}"
      - "traefik.http.routers.grpc01_${RUN_ENV}.rule=PathPrefix(`/hello01.HelloService01`)"
      - "traefik.http.routers.grpc01_${RUN_ENV}.entrypoints=grpc"
      - "traefik.http.services.grpc01_${RUN_ENV}.loadbalancer.server.port=50051"
      - "traefik.http.services.grpc01_${RUN_ENV}.loadbalancer.server.scheme=h2c"
      # Reflection router — grpcurl list/describe hits this service
      - "traefik.http.routers.grpc_reflect_${RUN_ENV}.rule=PathPrefix(`/grpc.reflection`)"
      - "traefik.http.routers.grpc_reflect_${RUN_ENV}.entrypoints=grpc"
      - "traefik.http.routers.grpc_reflect_${RUN_ENV}.priority=1"
      - "traefik.http.routers.grpc_reflect_${RUN_ENV}.service=grpc01_${RUN_ENV}"

# grpc02 — handles hello02.HelloService02
grpc02:
  deploy:
    labels:
      - "traefik.enable=true"
      - "traefik.env=${RUN_ENV}"
      - "traefik.http.routers.grpc02_${RUN_ENV}.rule=PathPrefix(`/hello02.HelloService02`)"
      - "traefik.http.routers.grpc02_${RUN_ENV}.entrypoints=grpc"
      - "traefik.http.services.grpc02_${RUN_ENV}.loadbalancer.server.port=50051"
      - "traefik.http.services.grpc02_${RUN_ENV}.loadbalancer.server.scheme=h2c"
```

> **Note:** `grpcurl list` only shows services from the server handling `/grpc.reflection`. To call a specific service, use its full path directly (e.g. `hello02.HelloService02/SayHello`).

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

## Testing gRPC Services

### Install grpcurl

```bash
curl -sSL "https://github.com/fullstorydev/grpcurl/releases/download/v1.9.2/grpcurl_1.9.2_linux_x86_64.tar.gz"


sudo tar -xz -C /usr/local/bin grpcurl
```

### List available gRPC services (uses server reflection)

Reflection routes to `grpc01` by default, so `list` shows grpc01's services:

```bash
# Dev (gRPC port 50051)
grpcurl -plaintext manager01-dev.xno:50051 list

# Staging (gRPC port 50052)
grpcurl -plaintext manager01-dev.xno:50052 list
```

Expected output:

```
grpc.reflection.v1alpha.ServerReflection
hello01.HelloService01
```

### Describe a service

```bash
grpcurl -plaintext manager01-dev.xno:50051 describe hello01.HelloService01
```

### Call each gRPC service

Traefik routes by the gRPC package path — each service is reachable independently:

```bash
# Call HelloService01 (dev)
grpcurl -plaintext -d '{"name": "world"}' \
  manager01-dev.xno:50051 hello01.HelloService01/SayHello

# Call HelloService02 (dev)
grpcurl -plaintext -d '{"name": "world"}' \
  manager01-dev.xno:50051 hello02.HelloService02/SayHello

# Same services on staging (port 50052)
grpcurl -plaintext -d '{"name": "world"}' \
  manager01-dev.xno:50052 hello01.HelloService01/SayHello

grpcurl -plaintext -d '{"name": "world"}' \
  manager01-dev.xno:50052 hello02.HelloService02/SayHello
```

Expected output:

```json
{"message": "hello dev from gRPC server 01, world!"}
{"message": "hello dev from gRPC server 02, world!"}
```

### Test from another service inside the swarm (service-to-service via app-net)

```bash
# From any container on app-net, use the swarm DNS name:
# <stack>-<env>_<service>:<port>
grpcurl -plaintext hello-dev_grpc01:50051 hello01.HelloService01/SayHello -d '{"name": "internal"}'
grpcurl -plaintext hello-dev_grpc02:50051 hello02.HelloService02/SayHello -d '{"name": "internal"}'
```

### Test HTTP APIs

```bash
# API 01 (dev, port 8081)
curl http://manager01-dev.xno:8081/hello-api-01

# API 02 (dev, port 8081 — same port, different path)
curl http://manager01-dev.xno:8081/hello-api-02

# Staging
curl http://manager01-dev.xno:8082/hello-api-01
curl http://manager01-dev.xno:8082/hello-api-02
```

Expected output:

```json
{"service": "api-01", "message": "hello dev", "build_args": {"EXAMPLE_ARG_01": "arg_01", "EXAMPLE_ARG_02": "arg_02"}}
{"service": "api-02", "message": "hello dev", "build_args": {"EXAMPLE_ARG_01": "arg_01", "EXAMPLE_ARG_02": "arg_02"}}
```

### Test HTTP + gRPC together

```bash
# HTTP
curl http://manager01-dev.xno:8081/hello-api-01
curl http://manager01-dev.xno:8081/hello-api-02

# gRPC (same Traefik, different entrypoint)
grpcurl -plaintext -d '{"name": "test"}' \
  -proto protos/hello01.proto \
  manager01-dev.xno:50051 hello01.HelloService01/SayHello

grpcurl -plaintext -d '{"name": "test"}' \
  -proto protos/hello02.proto \
  manager01-dev.xno:50051 hello02.HelloService02/SayHello
```

### Port reference

| Environment | HTTP port | gRPC port |
|---|---|---|
| dev | 8081 | 50051 |
| staging | 8082 | 50052 |
| prod | 8083 | 50053 |

---

## Scaling Replicas

Each service supports configurable replicas via environment variables (default: 1). Set them in the runner's systemd service file or pass via `envsubst`.

| Variable | Service | Default |
|---|---|---|
| `API01_REPLICAS` | api01 (HTTP) | 1 |
| `API02_REPLICAS` | api02 (HTTP) | 1 |
| `GRPC01_REPLICAS` | grpc01 (gRPC) | 1 |
| `GRPC02_REPLICAS` | grpc02 (gRPC) | 1 |

### Set replicas in systemd (persistent per env)

```ini
# /etc/systemd/system/actions.runner.<org>.<name>-dev.service
[Service]
Environment="API01_REPLICAS=2"
Environment="API02_REPLICAS=2"
Environment="GRPC01_REPLICAS=1"
Environment="GRPC02_REPLICAS=1"
```

```bash
sudo systemctl daemon-reload
sudo systemctl restart actions.runner.<org>.<name>-dev.service
```

### Scale manually (immediate, non-persistent)

```bash
# Scale api01 to 4 replicas
docker service scale hello-dev_api01=4

# Scale all services at once
docker service scale hello-dev_api01=2 hello-dev_api02=2 hello-dev_grpc01=3 hello-dev_grpc02=3
```

Traefik automatically load-balances across all replicas.

---

## Demo Services Reference

This repo ships with 4 demo services sharing a single Docker image:

| Service | Type | Entrypoint | Route | Port |
|---|---|---|---|---|
| `api01` | HTTP (FastAPI) | `api_server_01.py` | `/hello-api-01` | 8000 |
| `api02` | HTTP (FastAPI) | `api_server_02.py` | `/hello-api-02` | 8000 |
| `grpc01` | gRPC | `grpc_server_01.py` | `/hello01.HelloService01/*` | 50051 |
| `grpc02` | gRPC | `grpc_server_02.py` | `/hello02.HelloService02/*` | 50051 |

All services run from the same image — the `entrypoint` in docker-compose selects which server to start.

---

## Useful Commands

```bash
# List all stacks
docker stack ls

# List services in a stack
docker stack services hello-dev

# View service logs
docker service logs hello-dev_api01 --follow
docker service logs hello-dev_api02 --follow
docker service logs hello-dev_grpc01 --follow
docker service logs hello-dev_grpc02 --follow

# Check replica status
docker service ls --filter name=hello-dev

# Scale a service
docker service scale hello-dev_api01=4

# Scale multiple services
docker service scale hello-dev_api01=2 hello-dev_api02=2 hello-dev_grpc01=3 hello-dev_grpc02=3

# Redeploy a single service (rolling update)
docker service update --force hello-dev_api01

# Remove a stack
docker stack rm hello-dev

# Inspect node labels
docker node ls -q | xargs docker node inspect --format '{{.Description.Hostname}}: {{json .Spec.Labels}}'
```

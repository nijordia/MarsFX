# MarsFX Kubernetes Cluster Audit Report

**Audit Date:** 2026-04-01
**Cluster:** kind-marsfx (Kubernetes 1.31.0)
**Nodes:** 3 (1 control-plane + 2 workers)
**Total Pods Deployed:** 12 across 8 namespaces

---

## Executive Summary

Your KIND cluster is **functionally operational** but has **significant gaps in production-grade standards**. The cluster successfully deploys all core data platform components (Kafka, Trino, Lakekeeper, Arroyo, MinIO, PostgreSQL, PgBouncer), but lacks:

1. **Inconsistent resource limits** — Some workloads have none; others are aggressive
2. **Missing health checks** — Critical services (Kafka, PostgreSQL) have no liveness/readiness probes
3. **Weak RBAC** — Most services use default ServiceAccount; no least-privilege roles
4. **No network policies** — Zero NetworkPolicy resources; all-allow-all network model
5. **No security contexts** — Inconsistent pod-level security hardening

**Learning Value:** ✅ Excellent for understanding component interactions
**Production Readiness:** ❌ Not suitable without remediation
**Complexity Assessment:** ⚠️ Good balance for a learning project—don't over-engineer, but fix the critical gaps

---

## Detailed Findings

### 1. Resource Management DONE

#### Current State

| Component | CPU Request | CPU Limit | Memory Request | Memory Limit | Status |
|-----------|-------------|-----------|-----------------|--------------|--------|
| **Arroyo Controller** | ❌ NONE | ❌ NONE | ❌ NONE | ❌ NONE | 🔴 CRITICAL |
| **Arroyo Worker Job** | 900m | ❌ NONE | ❌ NONE | ❌ NONE | 🔴 CRITICAL |
| **Kafka Broker** | 250m | 1000m | 512Mi | 1Gi | 🟢 Good |
| **Lakekeeper REST API** | ❌ NONE | ❌ NONE | ❌ NONE | ❌ NONE | 🔴 CRITICAL |
| **Lakekeeper PostgreSQL** | ❌ NONE | ❌ NONE | ❌ NONE | ❌ NONE | 🔴 CRITICAL |
| **PgBouncer** | 100m | 500m | 128Mi | 512Mi | 🟢 Good |
| **MinIO** | 250m | 2000m | 512Mi | 4Gi | 🟡 Oversized |
| **PostgreSQL (seed)** | 250m | 1000m | 512Mi | 2Gi | 🟡 Oversized |
| **Trino Coordinator** | 1000m | 2000m | 4Gi | 8Gi | 🟡 Oversized for learning |
| **Trino Workers (×2)** | 1000m | 2000m | 4Gi | 8Gi | 🟡 Oversized for learning |

#### Issues

- **Arroyo:** No resource limits → OOM-kill risk; worker jobs spawn dynamically with only request (900m), no limit
- **Lakekeeper & PostgreSQL:** Charts don't specify resources → K8s scheduler has no eviction triggers
- **Trino:** 4Gi request per pod (8Gi with 2 workers) is **aggressive for a 3-node KIND cluster**; leaves minimal room for other services
- **MinIO:** 2 CPU limit is oversized for a learning project

#### Recommended Action

**Priority: HIGH** — Fix before next cluster recreation

1. **Arroyo Controller:** Add requests (500m CPU, 512Mi RAM) and limits (1000m CPU, 1Gi RAM)
2. **Arroyo Worker:** Set limits (1500m CPU, 2Gi RAM) to prevent runaway resource usage
3. **Lakekeeper:** Add to Helm values (requests: 250m/512Mi, limits: 1000m/2Gi)
4. **Lakekeeper PostgreSQL:** Add to StatefulSet (requests: 250m/512Mi, limits: 1000m/2Gi)
5. **Trino:** Reduce for local learning (coordinator: 1000m/2Gi request → 500m/1Gi request; workers: same)

---

### 2. Health Checks (Liveness & Readiness Probes) DONE

#### Current State

| Component | Liveness Probe | Readiness Probe | Status |
|-----------|--------|----------|--------|
| **Arroyo Controller** | ✅ http://:admin/status | ✅ http://:admin/status | 🟢 Good |
| **Kafka Broker** | ✅ tcp-socket :9092 | ✅ tcp-socket :9092 | 🟢 Good |
| **Lakekeeper REST API** | ❌ NONE | ❌ NONE | 🔴 CRITICAL |
| **Lakekeeper PostgreSQL** | ✅ exec pg_isready | ✅ exec pg_isready | 🟢 Good |
| **PgBouncer** | ✅ tcp-socket :5432 | ✅ tcp-socket :5432 | 🟢 Good |
| **MinIO** | ✅ /minio/health/live | ✅ /minio/health/ready | 🟢 Good |
| **PostgreSQL (seed)** | ❌ NONE | ❌ NONE | 🔴 CRITICAL |
| **Trino Coordinator** | ✅ /v1/info | ❌ NONE | 🟡 Partial |
| **Trino Workers** | ❌ NONE | ❌ NONE | 🔴 CRITICAL |

#### Issues

- **Lakekeeper REST API:** No probes → K8s can't detect if it's unresponsive
- **PostgreSQL (seed):** No probes → crashes won't trigger automatic restart
- **Trino Workers:** No liveness or readiness probes → undetected hung workers
- **Trino Coordinator:** Liveness only (no readiness) → might receive traffic before fully initialized

#### Recommended Action

**Priority: HIGH** — Crashes won't be detected/recovered without these

1. **Lakekeeper REST API:** Add http-get probe: `GET /health` (delay: 15s, period: 10s)
2. **PostgreSQL (seed):** Add exec probe: `pg_isready -h localhost` (delay: 10s, period: 10s)
3. **Trino Coordinator:** Add readiness probe: `GET /v1/info` (delay: 10s, period: 10s)
4. **Trino Workers:** Add liveness & readiness: `GET /v1/info` (delay: 20s, period: 10s)

---

### 3. RBAC (Role-Based Access Control)

#### Current State

- **Namespaces:** 8 (data-arroyo, data-kafka, data-lakekeeper, data-pgbouncer, data-storage, data-trino, data-ingress, ingress-nginx)
- **Custom ServiceAccounts:** Only 3 (arroyo, lakekeeper-chart, trino)
- **Custom Roles:** Only 2 (lakekeeper-chart, ingress-nginx)
- **Default ServiceAccount Usage:** ✅ PgBouncer, Kafka, PostgreSQL, MinIO use default → potential privilege escalation vector

#### Issues

- **Weak Pod Identity:** Most pods run as `default` ServiceAccount → can access secrets, config, logs in their namespace
- **No Least-Privilege:** No custom Roles/RoleBindings to restrict pod capabilities
- **Kafka:** No ServiceAccount defined → uses default → can read/write all ConfigMaps/Secrets in data-kafka
- **PostgreSQL:** No ServiceAccount defined → same issue
- **MinIO:** No ServiceAccount defined → same issue

#### Recommended Action

**Priority: MEDIUM** — Not urgent for a learning cluster, but good practice

Create dedicated ServiceAccount + minimal Role for each component:

```yaml
# Example: Kafka
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: kafka
  namespace: data-kafka
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: kafka
  namespace: data-kafka
rules:
  - apiGroups: [""]
    resources: ["configmaps"]
    verbs: ["get", "list"]  # Kafka may need to read config
  # Add more specific rules as needed (check Kafka docs)
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: kafka
  namespace: data-kafka
subjects:
  - kind: ServiceAccount
    name: kafka
    namespace: data-kafka
roleRef:
  kind: Role
  name: kafka
  apiGroup: rbac.authorization.k8s.io
```

---

### 4. Network Policies

#### Current State

- **NetworkPolicy Resources:** 0 (zero)
- **Network Model:** All-allow-all (default Kubernetes behavior)
- **Pod-to-Pod Communication:** Unrestricted across all namespaces
- **External Access:** Controlled only by Service types (ClusterIP, NodePort, Ingress)

#### Issues

- **No Network Segmentation:** A pod in data-kafka can talk to any pod in any namespace
- **No Egress Control:** Pods can reach external networks (Internet) without restriction
- **Attack Surface:** Compromised pod in one domain could access data in another
- **Not Critical for Learning:** Fine for local development, but bad practice to leave unimplemented

#### Recommended Action

**Priority: LOW** — Skip for now; implement after Phase 2 multi-domain setup

When you add a second data domain (Phase 2), add NetworkPolicy:

```yaml
# Default-deny all ingress and egress
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: data-kafka
spec:
  podSelector: {}
  policyTypes: ["Ingress", "Egress"]
---
# Allow traffic to Kafka from Trino and Arroyo only
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-kafka-clients
  namespace: data-kafka
spec:
  podSelector:
    matchLabels:
      app: kafka
  policyTypes: ["Ingress"]
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app: trino
            namespaceSelector:
              matchLabels:
                name: data-trino
        - podSelector:
            matchLabels:
              app: arroyo
            namespaceSelector:
              matchLabels:
                name: data-arroyo
      ports:
        - protocol: TCP
          port: 9092
---
# Allow DNS egress (all pods need this)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns-egress
  namespace: data-kafka
spec:
  podSelector: {}
  policyTypes: ["Egress"]
  egress:
    - to:
        - namespaceSelector: {}
      ports:
        - protocol: UDP
          port: 53
```

---

### 5. Security Contexts

#### Current State

- **Pod-Level Security:** Inconsistent
  - ✅ PgBouncer: `runAsUser: 1000, runAsNonRoot: true`
  - ✅ Trino: `runAsUser: 1000, runAsNonRoot: true`
  - ❌ Arroyo: No security context
  - ❌ Kafka: No security context (runs as root)
  - ❌ PostgreSQL: No security context
  - ❌ MinIO: No security context
  - ❌ Lakekeeper: No security context

- **Capability Dropping:** None (all pods have default capabilities)
- **Read-Only Root Filesystem:** Not enforced anywhere
- **Privilege Escalation:** Not blocked

#### Issues

- **Kafka & PostgreSQL run as root:** Container compromise = host compromise risk
- **No capability dropping:** Pods have CAP_SYS_ADMIN, CAP_NET_RAW, etc. (unnecessary)
- **Write access to root FS:** Pods can modify themselves (malware persistence)

#### Recommended Action

**Priority: MEDIUM** — Good hygiene; implement for Phase 2

Add to Helm values or manifests:

```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  runAsGroup: 1000
  fsGroup: 1000
  capabilities:
    drop: ["ALL"]
  readOnlyRootFilesystem: true  # May break some services; test first

# Note: readOnlyRootFilesystem may need tmpfs mounts for logs/tmp
volumeMounts:
  - name: tmp
    mountPath: /tmp
  - name: logs
    mountPath: /var/log
volumes:
  - name: tmp
    emptyDir: {}
  - name: logs
    emptyDir: {}
```

---

### 6. Image Management

#### Current State

| Component | Image | Tag | Pull Policy |
|-----------|-------|-----|-------------|
| Arroyo | ghcr.io/arroyosystems/arroyo | 0.15 | IfNotPresent |
| Kafka | confluentinc/cp-kafka | 7.6.0 | IfNotPresent |
| Lakekeeper | lakekeeper/lakekeeper | (Helm default) | IfNotPresent |
| MinIO | minio/minio | (Helm default) | IfNotPresent |
| PostgreSQL | postgres | 17.7 | IfNotPresent |
| PgBouncer | edoburu/pgbouncer | latest | IfNotPresent |
| Trino | trinodb/trino | 445 | IfNotPresent |

#### Issues

- **PgBouncer uses `latest` tag:** ⚠️ Unpinned; can receive breaking updates
- **No image pull secrets:** Only works if images are public
- **No image scanning:** No scanning for vulnerabilities

#### Recommended Action

**Priority: LOW** — Fix PgBouncer tag

Replace `latest` with a pinned version (e.g., `1.21.0`).

---

### 7. Storage & Persistence

#### Current State

- **PostgreSQL StatefulSet:** Uses PVC with default storage class (100Gi default limit on KIND)
- **MinIO StatefulSet:** Uses PVC (500Gi default limit on KIND)
- **Arroyo Checkpoints:** LocalPath hostPath (ephemeral—lost on pod eviction)
- **Trino:** Ephemeral (memory-only query state)

#### Issues

- **Arroyo checkpoints on /tmp/arroyo-data (hostPath):** ⚠️ Not replicated; single point of failure
- **No backup strategy:** If KIND cluster is deleted, all data is lost (expected for learning)
- **hostPath volume on worker node:** Can't migrate if node dies

#### Recommended Action

**Priority: LOW** — Acceptable for learning; document the limitation

For Phase 3 (scale-up), migrate Arroyo checkpoints to MinIO (S3-backed).

---

### 8. Ingress & Networking

#### Current State

| Service | Type | Port | Ingress |
|---------|------|------|---------|
| Trino | ClusterIP | 8080 | ✅ Yes (trino.local.platform) |
| Lakekeeper | ClusterIP | 8181 | ❌ No |
| Arroyo | NodePort | 30115 → 5115 | ❌ No |
| MinIO Console | ClusterIP | 9001 | ❌ No |
| Kafka | ClusterIP | 9092 | ✅ Internal only |

#### Issues

- **Inconsistent exposure:** Some via Ingress, some via NodePort, some ClusterIP-only
- **No Ingress for Lakekeeper, MinIO, Arroyo:** Requires manual port-forward
- **Trino Ingress uses local hostname:** Requires DNS config or `/etc/hosts` entry

#### Recommended Action

**Priority: LOW** — Port-forward works fine for learning

For better UX, add Ingress rules:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: data-platform
  namespace: data-ingress
spec:
  ingressClassName: nginx
  rules:
    - host: trino.local.platform
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: trino
                port:
                  number: 8080
    - host: lakekeeper.local.platform
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: lakekeeper-chart
                port:
                  number: 8181
    - host: minio.local.platform
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: minio
                port:
                  number: 9001
```

Then add to `/etc/hosts`:
```
127.0.0.1 trino.local.platform lakekeeper.local.platform minio.local.platform
```

---

### 9. Logging & Monitoring

#### Current State

- **Log aggregation:** None (container logs only; lost on pod deletion)
- **Metrics collection:** None (no Prometheus/Grafana)
- **Alert rules:** None

#### Recommended Action

**Priority: LOW** — Not critical for learning; add in Phase 3 if needed

For future learning:
- Add Prometheus + Grafana for metrics
- Configure ELK or Loki for centralized logging
- Set up alert rules for SLA violations

---

## Cluster Deployment Standards Review

### Strengths ✅

1. **Clear namespace organization:** 8 logical namespaces by component (data-kafka, data-trino, etc.)
2. **Infrastructure-as-Code:** Helm charts + kustomize for reproducibility
3. **Dependency ordering:** Makefile ensures correct deployment sequence (storage → lakekeeper → trino)
4. **Good labeling:** Pods labeled with app names for easy filtering
5. **Secret management:** Using K8s Secrets (not hardcoded in manifests)
6. **Port mapping clarity:** KIND config well-documented with comments

### Gaps ❌

1. **No resource governance:** Namespaces lack ResourceQuotas or LimitRanges
2. **No pod security standards:** No baseline PSS enforcement
3. **No monitoring/observability:** Can't see what's happening inside the cluster
4. **No backup/disaster recovery:** Ephemeral local cluster
5. **No documentation of architecture:** No ADR (Architecture Decision Records)

---

## Recommendations by Priority

### Phase 1: Immediate (Before Next Cluster Use)
- [ ] Add resource limits to Arroyo, Lakekeeper, PostgreSQL
- [ ] Add health checks to Lakekeeper REST API, PostgreSQL, Trino workers
- [ ] Pin PgBouncer image tag from `latest` → specific version
- [ ] Add liveness probe to Trino coordinator, readiness probe to workers

### Phase 2: Short-term (Before Multi-Domain Setup)
- [ ] Create ServiceAccounts for Kafka, PostgreSQL, MinIO
- [ ] Add basic RBAC Roles/RoleBindings (read-only for most)
- [ ] Add NetworkPolicy default-deny-all + allow rules
- [ ] Implement security contexts (runAsNonRoot, etc.)

### Phase 3: Long-term (Before Production-Like Testing)
- [ ] Add ResourceQuota + LimitRange per namespace
- [ ] Deploy Prometheus + Grafana for metrics
- [ ] Implement centralized logging (Loki or ELK)
- [ ] Create alerting rules for SLA violations
- [ ] Document architecture in ARCHITECTURE.md
- [ ] Add pod anti-affinity rules to spread replicas

---

## Learning Value Assessment

### ✅ What You're Learning Well

Your cluster is **excellent** for understanding:
- How multiple data services integrate (Kafka → Arroyo → Iceberg → Trino)
- How dbt transforms raw data into analytics-ready datasets
- How data contracts enforce producer-consumer agreements
- How Dagster orchestrates complex pipelines
- How Kubernetes namespaces organize logical domains

### ⚠️ What You're NOT Learning

By using all-allow-all networking and default ServiceAccounts, you're **missing**:
- Network security and microsegmentation
- Least-privilege RBAC design
- Pod security hardening
- Observability patterns (metrics, logs, traces)
- Disaster recovery & backup strategies

**Recommendation:** For your stated learning goal (data mesh + contracts), skip the above for now. Add them in Phase 3 if you want to deepen your production operations knowledge.

---

## Conclusion

**Your cluster is well-organized for learning, but needs hardening for robustness.**

| Aspect | Score | Comment |
|--------|-------|---------|
| **Organization** | 8/10 | Clear namespaces, good use of Helm/kustomize |
| **Resource Management** | 4/10 | Missing limits on critical services |
| **Reliability** | 5/10 | No health checks on 4 services |
| **Security** | 3/10 | No RBAC, no network policies, no security contexts |
| **Observability** | 2/10 | No logging, metrics, or alerting |
| **Production Readiness** | 3/10 | Fine for learning; not for production |

**Next Steps:**
1. Complete Phase 1 fixes (health checks, resource limits) before heavy testing
2. Skip Phase 2 security hardening unless you want deeper K8s knowledge
3. Focus on Phase 3: validate data contracts, test multi-domain governance
4. Document lessons learned in a learning journal for your new job

---

**Questions?** Ask about specific findings or remediation steps.
#!/usr/bin/env bash
set -euo pipefail

# Post-deploy verification for K3s HA cluster
# Checks nodes, kube-vip, MetalLB, Traefik, etcd, and runs a whoami test

VIP="192.168.0.10"
SSH_USER="pi"
FIRST_SERVER="192.168.0.11"
PASS=0
FAIL=0

ok()    { echo -e "\033[1;32m[PASS]\033[0m $*"; ((PASS++)); }
fail()  { echo -e "\033[1;31m[FAIL]\033[0m $*"; ((FAIL++)); }
info()  { echo -e "\033[1;34m[INFO]\033[0m $*"; }
header(){ echo ""; echo "=== $* ==="; }

# --- Nodes ---
header "Node Status"
node_count=$(kubectl get nodes --no-headers 2>/dev/null | wc -l)
ready_count=$(kubectl get nodes --no-headers 2>/dev/null | grep -c ' Ready' || true)
cp_count=$(kubectl get nodes --no-headers -l node-role.kubernetes.io/control-plane 2>/dev/null | wc -l)

if [[ $node_count -eq 4 && $ready_count -eq 4 ]]; then
    ok "All 4 nodes are Ready"
else
    fail "Expected 4 Ready nodes, got $ready_count/$node_count"
fi

if [[ $cp_count -eq 3 ]]; then
    ok "3 control-plane nodes found"
else
    fail "Expected 3 control-plane nodes, got $cp_count"
fi

kubectl get nodes -o wide

# --- kube-vip ---
header "kube-vip"
kvip_ready=$(kubectl -n kube-system get pods -l app.kubernetes.io/name=kube-vip --no-headers 2>/dev/null | grep -c 'Running' || true)
if [[ $kvip_ready -eq 3 ]]; then
    ok "3 kube-vip pods running"
else
    fail "Expected 3 kube-vip pods, got $kvip_ready running"
fi

kubectl -n kube-system get pods -l app.kubernetes.io/name=kube-vip -o wide

# --- VIP health ---
header "VIP Health"
if curl -sk --connect-timeout 5 "https://$VIP:6443/healthz" | grep -q "ok"; then
    ok "VIP $VIP:6443 responding healthy"
else
    fail "VIP $VIP:6443 not responding"
fi

# --- VIP holder ---
info "Current VIP leader:"
kubectl -n kube-system get lease plndr-cp-lock -o jsonpath='{.spec.holderIdentity}' 2>/dev/null && echo "" || echo "(could not determine)"

# --- etcd health ---
header "etcd Health"
etcd_health=$(ssh -o ConnectTimeout=5 -o BatchMode=yes "$SSH_USER@$FIRST_SERVER" \
    "sudo ETCDCTL_API=3 /var/lib/rancher/k3s/data/current/bin/etcdctl \
    --cacert /var/lib/rancher/k3s/server/tls/etcd/server-ca.crt \
    --cert /var/lib/rancher/k3s/server/tls/etcd/server-client.crt \
    --key /var/lib/rancher/k3s/server/tls/etcd/server-client.key \
    endpoint health --cluster -w table" 2>/dev/null || echo "FAILED")

if echo "$etcd_health" | grep -q "true"; then
    ok "etcd cluster healthy"
    echo "$etcd_health"
else
    fail "etcd health check failed"
    echo "$etcd_health"
fi

# --- MetalLB ---
header "MetalLB"
mlb_controller=$(kubectl -n metallb-system get pods -l app.kubernetes.io/name=metallb,app.kubernetes.io/component=controller --no-headers 2>/dev/null | grep -c 'Running' || true)
mlb_speakers=$(kubectl -n metallb-system get pods -l app.kubernetes.io/name=metallb,app.kubernetes.io/component=speaker --no-headers 2>/dev/null | grep -c 'Running' || true)

if [[ $mlb_controller -ge 1 ]]; then
    ok "MetalLB controller running ($mlb_controller)"
else
    fail "MetalLB controller not running"
fi

if [[ $mlb_speakers -eq 4 ]]; then
    ok "MetalLB speakers running on all 4 nodes"
else
    fail "Expected 4 MetalLB speakers, got $mlb_speakers"
fi

kubectl -n metallb-system get pods -o wide

# --- Traefik ---
header "Traefik"
traefik_ip=$(kubectl -n kube-system get svc traefik -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "")
if [[ -n "$traefik_ip" ]]; then
    ok "Traefik has external IP: $traefik_ip"
else
    fail "Traefik has no external IP"
fi

kubectl -n kube-system get svc traefik

# --- Node labels ---
header "Node Labels (storage-tier)"
for node in rpi5-8gb-crucial-p3-plus-500gb rpi5-8gb-samsung-980-500gb rpi5-8gb-rpi-256gb rpi5-8gb-crucial-bx500-500gb; do
    tier=$(kubectl get node "$node" -o jsonpath='{.metadata.labels.storage-tier}' 2>/dev/null || echo "")
    if [[ -n "$tier" ]]; then
        ok "$node: storage-tier=$tier"
    else
        fail "$node: no storage-tier label"
    fi
done

# --- whoami smoke test ---
header "Whoami Smoke Test"
if [[ -n "$traefik_ip" ]]; then
    info "Deploying whoami test..."
    kubectl apply -f ~/workspace/homelab/traefik/examples/whoami-test.yaml >/dev/null 2>&1
    kubectl -n default wait --for=condition=available deployment/whoami --timeout=60s >/dev/null 2>&1

    sleep 3
    whoami_response=$(curl -s --connect-timeout 5 -H "Host: whoami.local" "http://$traefik_ip" || echo "")
    if echo "$whoami_response" | grep -q "Hostname:"; then
        ok "whoami responded via Traefik IngressRoute"
        echo "$whoami_response" | head -5
    else
        fail "whoami did not respond"
    fi

    info "Cleaning up whoami test..."
    kubectl delete -f ~/workspace/homelab/traefik/examples/whoami-test.yaml >/dev/null 2>&1
else
    info "Skipping whoami test (no Traefik IP)"
fi

# --- Summary ---
header "Summary"
echo "Passed: $PASS"
echo "Failed: $FAIL"

if [[ $FAIL -gt 0 ]]; then
    fail "Some checks failed!"
    exit 1
else
    ok "All checks passed!"
fi

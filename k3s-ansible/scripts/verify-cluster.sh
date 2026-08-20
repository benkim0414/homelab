#!/usr/bin/env bash
set -euo pipefail

# Post-deploy verification for K3s HA cluster
# Checks nodes, kube-vip, MetalLB, Traefik, etcd, and runs a whoami test

VIP="192.168.0.10"
SSH_USER="pi"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/codex_homelab_ed25519}"
FIRST_SERVER="192.168.0.11"
EXPECTED_NODES=5
EXPECTED_CONTROL_PLANES=3
EXPECTED_KUBE_VIP_PODS=3
EXPECTED_METALLB_SPEAKERS=5
MACPRO_NODE="macpro-vm-16gb-samsung-980-120gb"
PASS=0
FAIL=0

ok()    { echo -e "\033[1;32m[PASS]\033[0m $*"; ((++PASS)); }
fail()  { echo -e "\033[1;31m[FAIL]\033[0m $*"; ((++FAIL)); }
info()  { echo -e "\033[1;34m[INFO]\033[0m $*"; }
header(){ echo ""; echo "=== $* ==="; }

# --- Nodes ---
header "Node Status"
node_count=$(kubectl get nodes --no-headers 2>/dev/null | wc -l)
ready_count=$(kubectl get nodes --no-headers 2>/dev/null | grep -c ' Ready' || true)
cp_count=$(kubectl get nodes --no-headers -l node-role.kubernetes.io/control-plane 2>/dev/null | wc -l)

if [[ $node_count -eq $EXPECTED_NODES && $ready_count -eq $EXPECTED_NODES ]]; then
    ok "All $EXPECTED_NODES nodes are Ready"
else
    fail "Expected $EXPECTED_NODES Ready nodes, got $ready_count/$node_count"
fi

if [[ $cp_count -eq $EXPECTED_CONTROL_PLANES ]]; then
    ok "$EXPECTED_CONTROL_PLANES control-plane nodes found"
else
    fail "Expected $EXPECTED_CONTROL_PLANES control-plane nodes, got $cp_count"
fi

kubectl get nodes -o wide

macpro_ready=$(kubectl get node "$MACPRO_NODE" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "")
macpro_cp_label=$(kubectl get node "$MACPRO_NODE" -o jsonpath='{.metadata.labels.node-role\.kubernetes\.io/control-plane}' 2>/dev/null || echo "")

if [[ "$macpro_ready" == "True" ]]; then
    ok "$MACPRO_NODE is Ready"
else
    fail "$MACPRO_NODE is not Ready"
fi

if [[ -z "$macpro_cp_label" ]]; then
    ok "$MACPRO_NODE is not labeled as control-plane"
else
    fail "$MACPRO_NODE unexpectedly has control-plane label"
fi

# --- kube-vip ---
header "kube-vip"
kvip_ready=$(kubectl -n kube-system get pods -l app.kubernetes.io/name=kube-vip --no-headers 2>/dev/null | grep -c 'Running' || true)
if [[ $kvip_ready -eq $EXPECTED_KUBE_VIP_PODS ]]; then
    ok "$EXPECTED_KUBE_VIP_PODS kube-vip pods running"
else
    fail "Expected $EXPECTED_KUBE_VIP_PODS kube-vip pods, got $kvip_ready running"
fi

kubectl -n kube-system get pods -l app.kubernetes.io/name=kube-vip -o wide

# --- VIP health ---
header "VIP Health"
vip_status=$(curl -sk -o /tmp/k3s-vip-healthz.out --connect-timeout 5 -w "%{http_code}" "https://$VIP:6443/healthz" || true)
if [[ "$vip_status" == "200" ]] && grep -q "ok" /tmp/k3s-vip-healthz.out; then
    ok "VIP $VIP:6443 responding healthy"
elif [[ "$vip_status" == "401" ]]; then
    ok "VIP $VIP:6443 reachable (healthz requires authentication)"
else
    fail "VIP $VIP:6443 not responding (HTTP ${vip_status:-none})"
fi

# --- VIP holder ---
info "Current VIP leader:"
kubectl -n kube-system get lease plndr-cp-lock -o jsonpath='{.spec.holderIdentity}' 2>/dev/null && echo "" || echo "(could not determine)"

# --- etcd health ---
header "etcd Health"
etcd_health=$(ssh -i "$SSH_KEY" -o IdentitiesOnly=yes -o ConnectTimeout=5 -o BatchMode=yes "$SSH_USER@$FIRST_SERVER" \
    "etcdctl=\$(sudo find /var/lib/rancher/k3s/data -path '*/bin/etcdctl' -type f 2>/dev/null | sort | tail -n1)
    if [[ -n \"\$etcdctl\" ]]; then
        sudo ETCDCTL_API=3 \"\$etcdctl\" \
        --cacert /var/lib/rancher/k3s/server/tls/etcd/server-ca.crt \
        --cert /var/lib/rancher/k3s/server/tls/etcd/server-client.crt \
        --key /var/lib/rancher/k3s/server/tls/etcd/server-client.key \
        endpoint health --cluster -w table
    else
        echo ETCDCTL_NOT_FOUND
    fi" 2>/dev/null || echo "FAILED")

if echo "$etcd_health" | grep -q "true"; then
    ok "etcd cluster healthy"
    echo "$etcd_health"
elif echo "$etcd_health" | grep -q "ETCDCTL_NOT_FOUND"; then
    readyz=$(kubectl get --raw='/readyz?verbose' 2>/dev/null || echo "FAILED")
    if echo "$readyz" | grep -Eq '^\[\+\]etcd ok$'; then
        ok "etcd reachable through Kubernetes API readyz"
        echo "$readyz" | grep -E '^\[\+\]etcd ok$'
    else
        fail "etcdctl missing and Kubernetes readyz etcd check failed"
        echo "$readyz"
    fi
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

if [[ $mlb_speakers -eq $EXPECTED_METALLB_SPEAKERS ]]; then
    ok "MetalLB speakers running on all $EXPECTED_METALLB_SPEAKERS nodes"
else
    fail "Expected $EXPECTED_METALLB_SPEAKERS MetalLB speakers, got $mlb_speakers"
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
header "Node Labels (Longhorn default disk)"
for node in rpi5-8gb-crucial-p3-plus-500gb rpi5-8gb-rpi-512gb rpi5-8gb-rpi-256gb rpi5-8gb-crucial-bx500-500gb; do
    default_disk=$(kubectl get node "$node" -o jsonpath='{.metadata.labels.node\.longhorn\.io/create-default-disk}' 2>/dev/null || echo "")
    if [[ "$default_disk" == "true" ]]; then
        ok "$node: node.longhorn.io/create-default-disk=true"
    else
        fail "$node: missing node.longhorn.io/create-default-disk=true label"
    fi
done

# --- Mac Pro VM labels ---
header "Mac Pro VM Labels"
declare -A macpro_labels=(
    ["homelab/host"]="macpro"
    ["homelab/node-class"]="vm"
    ["homelab/workload-tier"]="heavy"
)

for key in "${!macpro_labels[@]}"; do
    expected="${macpro_labels[$key]}"
    value=$(kubectl get node "$MACPRO_NODE" -o jsonpath="{.metadata.labels['$key']}" 2>/dev/null || echo "")
    if [[ "$value" == "$expected" ]]; then
        ok "$MACPRO_NODE: $key=$value"
    else
        fail "$MACPRO_NODE: expected $key=$expected, got '${value:-missing}'"
    fi
done

# --- Longhorn Mac Pro storage exclusion ---
header "Longhorn Mac Pro Storage"
if kubectl -n longhorn-system get nodes.longhorn.io "$MACPRO_NODE" >/dev/null 2>&1; then
    schedulable_disks=$(kubectl -n longhorn-system get nodes.longhorn.io "$MACPRO_NODE" \
        -o jsonpath='{range .spec.disks[*]}{.allowScheduling}{"\n"}{end}' 2>/dev/null \
        | grep -c '^true$' || true)
    replicas_on_macpro=$(kubectl -n longhorn-system get replicas.longhorn.io \
        -o jsonpath="{range .items[?(@.spec.nodeID=='$MACPRO_NODE')]}{.metadata.name}{'\n'}{end}" 2>/dev/null \
        | grep -c . || true)

    if [[ "$schedulable_disks" -eq 0 && "$replicas_on_macpro" -eq 0 ]]; then
        ok "$MACPRO_NODE has no schedulable Longhorn disks or replicas"
    else
        fail "$MACPRO_NODE has $schedulable_disks schedulable Longhorn disks and $replicas_on_macpro replicas"
    fi
else
    ok "$MACPRO_NODE is absent from Longhorn storage nodes"
fi

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

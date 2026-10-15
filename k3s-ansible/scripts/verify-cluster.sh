#!/usr/bin/env bash
set -euo pipefail

# Post-deploy verification for K3s HA cluster
# Checks nodes, kube-vip, MetalLB, Traefik, etcd, and runs a whoami test

VIP="192.168.0.10"
SSH_USER="pi"
SSH_CONFIG="${SSH_CONFIG:-$HOME/.ssh/homelab_config}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/pi_ed25519}"
FIRST_SERVER="192.168.0.11"
EXPECTED_NODES=5
EXPECTED_CONTROL_PLANES=3
EXPECTED_KUBE_VIP_PODS=3
EXPECTED_METALLB_SPEAKERS=5
MACPRO_NODE="k3s-05"
PASS=0
FAIL=0
VIP_BODY_FILE=$(mktemp)
trap 'rm -f "$VIP_BODY_FILE"' EXIT

ok()    { echo -e "\033[1;32m[PASS]\033[0m $*"; ((++PASS)); }
fail()  { echo -e "\033[1;31m[FAIL]\033[0m $*"; ((++FAIL)); }
info()  { echo -e "\033[1;34m[INFO]\033[0m $*"; }
header(){ echo ""; echo "=== $* ==="; }

# --- Nodes ---
header "Node Status"
node_count=$({ kubectl get nodes --no-headers 2>/dev/null || true; } | wc -l)
ready_count=$(kubectl get nodes --no-headers 2>/dev/null | grep -c ' Ready' || true)
cp_count=$({ kubectl get nodes --no-headers -l node-role.kubernetes.io/control-plane 2>/dev/null || true; } | wc -l)

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

kubectl get nodes -o wide || true

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

kubectl -n kube-system get pods -l app.kubernetes.io/name=kube-vip -o wide || true

# --- VIP health ---
header "VIP Health"
vip_status=$(curl -sk -o "$VIP_BODY_FILE" --connect-timeout 5 -w "%{http_code}" "https://$VIP:6443/healthz" || true)
if [[ "$vip_status" == "200" ]] && grep -q "ok" "$VIP_BODY_FILE"; then
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
etcd_health=$(ssh -F "$SSH_CONFIG" -i "$SSH_KEY" -o StrictHostKeyChecking=yes -o UpdateHostKeys=no -o IdentitiesOnly=yes -o ConnectTimeout=5 -o BatchMode=yes "$SSH_USER@$FIRST_SERVER" \
    "set -o pipefail
    find_output=\$(sudo find /var/lib/rancher/k3s/data -path '*/bin/etcdctl' -type f 2>&1)
    find_rc=\$?
    if [[ \$find_rc -ne 0 ]]; then
        echo ETCDCTL_FIND_FAILED
        echo \"\$find_output\"
        exit 0
    fi
    etcdctl=\$(printf '%s\n' \"\$find_output\" | sort | tail -n1)
    if [[ -n \"\$etcdctl\" ]]; then
        sudo ETCDCTL_API=3 \"\$etcdctl\" \
        --cacert /var/lib/rancher/k3s/server/tls/etcd/server-ca.crt \
        --cert /var/lib/rancher/k3s/server/tls/etcd/server-client.crt \
        --key /var/lib/rancher/k3s/server/tls/etcd/server-client.key \
        endpoint health --cluster -w table
    else
        echo ETCDCTL_NOT_FOUND
    fi" 2>/dev/null || echo "FAILED")

if echo "$etcd_health" | grep -q "ETCDCTL_FIND_FAILED"; then
    fail "etcdctl discovery failed on $FIRST_SERVER"
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
elif echo "$etcd_health" | grep -q "false"; then
    fail "etcd health check found one or more unhealthy endpoints"
    echo "$etcd_health"
elif [[ $(echo "$etcd_health" | grep -Ec '\|[[:space:]]*true[[:space:]]*\|') -eq $EXPECTED_CONTROL_PLANES ]]; then
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

if [[ $mlb_speakers -eq $EXPECTED_METALLB_SPEAKERS ]]; then
    ok "MetalLB speakers running on all $EXPECTED_METALLB_SPEAKERS nodes"
else
    fail "Expected $EXPECTED_METALLB_SPEAKERS MetalLB speakers, got $mlb_speakers"
fi

kubectl -n metallb-system get pods -o wide || true

# --- Traefik ---
header "Traefik"
traefik_ip=$(kubectl -n kube-system get svc traefik -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "")
if [[ -n "$traefik_ip" ]]; then
    ok "Traefik has external IP: $traefik_ip"
else
    fail "Traefik has no external IP"
fi

kubectl -n kube-system get svc traefik || true

# --- Node labels ---
header "Node Labels (Longhorn default disk)"
for node in k3s-01 k3s-02 k3s-03 k3s-04 "$MACPRO_NODE"; do
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

# --- Longhorn Mac Pro replica storage ---
header "Longhorn Mac Pro Storage"
if kubectl -n longhorn-system get nodes.longhorn.io "$MACPRO_NODE" -o json | python3 -c '
import json, sys
node = json.load(sys.stdin)
assert node["spec"].get("allowScheduling") is True
ready = any(c.get("type") == "Ready" and c.get("status") == "True"
            for c in node.get("status", {}).get("conditions", []))
assert ready
disks = node["spec"].get("disks", {})
statuses = node.get("status", {}).get("diskStatus", {})
assert any(disk.get("allowScheduling") is True and
           all(any(c.get("type") == condition and c.get("status") == "True"
                   for c in statuses.get(name, {}).get("conditions", []))
               for condition in ("Ready", "Schedulable"))
           for name, disk in disks.items())
'; then
    ok "$MACPRO_NODE is Ready with a schedulable Longhorn disk"
else
    fail "$MACPRO_NODE must have a Ready, schedulable Longhorn disk"
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

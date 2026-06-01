#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
SCRIPT="${ROOT}/.codex/hooks/cluster-session-start.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

make_kubectl() {
  local dir=$1
  local mode=$2

  cat > "${dir}/kubectl" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail

mode=${KUBECTL_STUB_MODE:-healthy}

if [[ "${mode}" == "unavailable" ]]; then
  exit 1
fi

case "$*" in
  "get nodes "*)
    printf 'node-a\tReady\tTrue\n'
    ;;
  "get pods -A --no-headers")
    cat <<'PODS'
default ok 1/1 Running 0 1m
default crashloop 0/1 CrashLoopBackOff 8 10m
default pending 0/1 Pending 0 30s
batch completed 0/1 Completed 0 2m
PODS
    ;;
  "get applications -n argocd --no-headers")
    cat <<'APPS'
app-a Synced Healthy
app-b OutOfSync Healthy
app-c Synced Degraded
APPS
    ;;
  *)
    echo "unexpected kubectl args: $*" >&2
    exit 2
    ;;
esac
STUB
  chmod +x "${dir}/kubectl"
  export KUBECTL_STUB_MODE="${mode}"
}

run_hook() {
  local tmp=$1
  PATH="${tmp}:$PATH" KUBECTL_TIMEOUT=2s bash "${SCRIPT}" <<< '{}'
}

assert_contains() {
  local output=$1
  local expected=$2

  if [[ "${output}" != *"${expected}"* ]]; then
    fail "expected output to contain '${expected}', got: ${output}"
  fi
}

tmp=$(mktemp -d)
trap 'rm -rf "${tmp}"' EXIT

make_kubectl "${tmp}" healthy
output=$(run_hook "${tmp}")
assert_contains "${output}" "[cluster-status] Unhealthy pods: 2"
assert_contains "${output}" "[cluster-status] ArgoCD apps OutOfSync/Degraded: 2"

make_kubectl "${tmp}" unavailable
output=$(run_hook "${tmp}")
assert_contains "${output}" "[cluster-status] Unhealthy pods: unknown (kubectl unavailable)"
assert_contains "${output}" "[cluster-status] ArgoCD apps OutOfSync/Degraded: unknown (kubectl unavailable)"

echo "cluster-session-start tests passed"

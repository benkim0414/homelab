#!/usr/bin/env bash
set -euo pipefail

# Pre-flight checks for K3s HA cluster nodes
# Validates SSH, cgroups, resources, and network interface

NODES=("192.168.0.11" "192.168.0.13" "192.168.0.14" "192.168.0.12")
NAMES=("rpi5-8gb-crucial-p3-plus-500gb" "rpi5-8gb-samsung-980-500gb" "rpi5-8gb-rpi-256gb" "rpi5-8gb-crucial-bx500-500gb")
SSH_USER="pi"
SSH_OPTS="-o ConnectTimeout=5 -o BatchMode=yes -o StrictHostKeyChecking=accept-new"

CGROUP_PARAMS="cgroup_enable=cpuset cgroup_memory=1 cgroup_enable=memory"
CMDLINE_FILE="/boot/firmware/cmdline.txt"

MIN_RAM_MB=3000
MIN_DISK_MB=10000

REBOOT_NEEDED=false
FAILED=false

info()  { echo -e "\033[1;34m[INFO]\033[0m  $*"; }
ok()    { echo -e "\033[1;32m[OK]\033[0m    $*"; }
warn()  { echo -e "\033[1;33m[WARN]\033[0m  $*"; }
error() { echo -e "\033[1;31m[FAIL]\033[0m  $*"; }

for i in "${!NODES[@]}"; do
    node="${NODES[$i]}"
    name="${NAMES[$i]}"
    echo ""
    echo "=========================================="
    info "Checking $name ($node)"
    echo "=========================================="

    # --- SSH connectivity ---
    if ! ssh $SSH_OPTS "$SSH_USER@$node" true 2>/dev/null; then
        error "$name: SSH connection failed"
        FAILED=true
        continue
    fi
    ok "$name: SSH connected"

    # --- cgroup parameters ---
    cmdline=$(ssh $SSH_OPTS "$SSH_USER@$node" "cat $CMDLINE_FILE 2>/dev/null || echo ''")
    missing_params=""
    for param in $CGROUP_PARAMS; do
        if ! echo "$cmdline" | grep -q "$param"; then
            missing_params="$missing_params $param"
        fi
    done

    if [[ -n "$missing_params" ]]; then
        warn "$name: Missing cgroup params:$missing_params"
        info "$name: Adding cgroup params to $CMDLINE_FILE"
        ssh $SSH_OPTS "$SSH_USER@$node" "sudo sed -i 's/$/ ${missing_params## }/' $CMDLINE_FILE"
        warn "$name: REBOOT REQUIRED for cgroup changes to take effect"
        REBOOT_NEEDED=true
    else
        ok "$name: cgroup params present"
    fi

    # --- RAM ---
    ram_kb=$(ssh $SSH_OPTS "$SSH_USER@$node" "grep MemTotal /proc/meminfo | awk '{print \$2}'")
    ram_mb=$((ram_kb / 1024))
    if [[ $ram_mb -lt $MIN_RAM_MB ]]; then
        error "$name: Insufficient RAM: ${ram_mb}MB (minimum ${MIN_RAM_MB}MB)"
        FAILED=true
    else
        ok "$name: RAM ${ram_mb}MB"
    fi

    # --- Disk ---
    disk_mb=$(ssh $SSH_OPTS "$SSH_USER@$node" "df -m / | awk 'NR==2 {print \$4}'")
    if [[ $disk_mb -lt $MIN_DISK_MB ]]; then
        error "$name: Insufficient disk: ${disk_mb}MB free (minimum ${MIN_DISK_MB}MB)"
        FAILED=true
    else
        ok "$name: Disk ${disk_mb}MB free"
    fi

    # --- eth0 interface ---
    if ssh $SSH_OPTS "$SSH_USER@$node" "ip link show eth0" &>/dev/null; then
        ok "$name: eth0 interface exists"
    else
        error "$name: eth0 interface not found"
        FAILED=true
    fi
done

echo ""
echo "=========================================="
echo "Summary"
echo "=========================================="

if $REBOOT_NEEDED; then
    warn "One or more nodes need a reboot for cgroup changes."
    warn "Reboot affected nodes, then re-run this script before proceeding."
fi

if $FAILED; then
    error "One or more checks failed. Fix issues before proceeding."
    exit 1
fi

if $REBOOT_NEEDED; then
    exit 2
fi

ok "All pre-flight checks passed!"

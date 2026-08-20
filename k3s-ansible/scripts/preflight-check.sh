#!/usr/bin/env bash
set -euo pipefail

# Pre-flight checks for K3s HA cluster nodes
# Validates SSH, cgroups, resources, and network interface

# Format: ip|name|ssh_user|required_interface|pi_cgroup_check
NODES=(
    "192.168.0.11|rpi5-8gb-crucial-p3-plus-500gb|pi|eth0|true"
    "192.168.0.12|rpi5-8gb-crucial-bx500-500gb|pi|eth0|true"
    "192.168.0.13|rpi5-8gb-rpi-512gb|pi|eth0|true"
    "192.168.0.14|rpi5-8gb-rpi-256gb|pi|eth0|true"
    "192.168.0.21|macpro-vm-16gb-samsung-980-120gb|benkim0414|eth0|false"
)
SSH_KEY="${SSH_KEY:-$HOME/.ssh/codex_homelab_ed25519}"
SSH_OPTS="-i $SSH_KEY -o IdentitiesOnly=yes -o ConnectTimeout=5 -o BatchMode=yes -o StrictHostKeyChecking=accept-new"

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

for record in "${NODES[@]}"; do
    IFS='|' read -r node name ssh_user required_interface pi_cgroup_check <<< "$record"
    echo ""
    echo "=========================================="
    info "Checking $name ($node)"
    echo "=========================================="

    # --- SSH connectivity ---
    if ! ssh $SSH_OPTS "$ssh_user@$node" true 2>/dev/null; then
        error "$name: SSH connection failed"
        FAILED=true
        continue
    fi
    ok "$name: SSH connected"

    # --- Raspberry Pi cgroup parameters ---
    if [[ "$pi_cgroup_check" == "true" ]]; then
        cmdline=$(ssh $SSH_OPTS "$ssh_user@$node" "cat $CMDLINE_FILE 2>/dev/null || echo ''")
        missing_params=""
        for param in $CGROUP_PARAMS; do
            if ! echo "$cmdline" | grep -q "$param"; then
                missing_params="$missing_params $param"
            fi
        done

        if [[ -n "$missing_params" ]]; then
            warn "$name: Missing cgroup params:$missing_params"
            info "$name: Adding cgroup params to $CMDLINE_FILE"
            ssh $SSH_OPTS "$ssh_user@$node" "sudo sed -i 's/$/ ${missing_params## }/' $CMDLINE_FILE"
            warn "$name: REBOOT REQUIRED for cgroup changes to take effect"
            REBOOT_NEEDED=true
        else
            ok "$name: cgroup params present"
        fi
    else
        ok "$name: Raspberry Pi cgroup cmdline check skipped"
    fi

    # --- RAM ---
    ram_kb=$(ssh $SSH_OPTS "$ssh_user@$node" "grep MemTotal /proc/meminfo | awk '{print \$2}'")
    ram_mb=$((ram_kb / 1024))
    if [[ $ram_mb -lt $MIN_RAM_MB ]]; then
        error "$name: Insufficient RAM: ${ram_mb}MB (minimum ${MIN_RAM_MB}MB)"
        FAILED=true
    else
        ok "$name: RAM ${ram_mb}MB"
    fi

    # --- Disk ---
    disk_mb=$(ssh $SSH_OPTS "$ssh_user@$node" "df -m / | awk 'NR==2 {print \$4}'")
    if [[ $disk_mb -lt $MIN_DISK_MB ]]; then
        error "$name: Insufficient disk: ${disk_mb}MB free (minimum ${MIN_DISK_MB}MB)"
        FAILED=true
    else
        ok "$name: Disk ${disk_mb}MB free"
    fi

    # --- required network interface ---
    if ssh $SSH_OPTS "$ssh_user@$node" "ip link show $required_interface" &>/dev/null; then
        ok "$name: $required_interface interface exists"
    else
        error "$name: $required_interface interface not found"
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

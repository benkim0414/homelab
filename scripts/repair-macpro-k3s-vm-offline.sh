#!/usr/bin/env bash
set -euo pipefail

PVE_HOST="${PVE_HOST:-pve-macpro}"
SSH_CONFIG="${SSH_CONFIG:-$HOME/.ssh/codex_homelab_config}"
VMID="${VMID:-210}"
VM_NAME="${VM_NAME:-macpro-vm-16gb-samsung-980-120gb}"
VM_IP="${VM_IP:-192.168.0.21}"
VM_CIDR="${VM_CIDR:-24}"
VM_GW="${VM_GW:-192.168.0.1}"
VM_DNS="${VM_DNS:-192.168.0.1}"
VM_USER="${VM_USER:-benkim0414}"
SSH_KEY_PATH="${SSH_KEY_PATH:-$HOME/.ssh/codex_homelab_ed25519.pub}"

if [[ ! -f "$SSH_KEY_PATH" ]]; then
    SSH_KEY_PATH="$HOME/.ssh/id_ed25519.pub"
fi

if [[ ! -f "$SSH_CONFIG" ]]; then
    echo "SSH config not found: $SSH_CONFIG" >&2
    exit 1
fi

if [[ ! -f "$SSH_KEY_PATH" ]]; then
    echo "SSH public key not found. Set SSH_KEY_PATH=/path/to/key.pub" >&2
    exit 1
fi

SSH_KEY_B64=$(base64 -w0 "$SSH_KEY_PATH")

cat <<EOF
This will stop VMID $VMID, edit its root disk offline, and start it again.

It bypasses Proxmox cloud-init by injecting directly into the guest disk:

  Hostname:  $VM_NAME
  IP:        $VM_IP/$VM_CIDR
  Gateway:   $VM_GW
  DNS:       $VM_DNS
  User:      $VM_USER
  SSH key:   $SSH_KEY_PATH

The remote step runs with sudo on Proxmox and may install libguestfs-tools.
EOF

read -r -p "Continue? [y/N] " answer
case "$answer" in
    y|Y|yes|YES) ;;
    *) echo "Aborted."; exit 1 ;;
esac

read -r -p "Type REPAIR-$VMID to confirm offline mutation of VMID $VMID: " repair_answer
if [[ "$repair_answer" != "REPAIR-$VMID" ]]; then
    echo "Repair confirmation did not match. Aborted."
    exit 1
fi

remote_script=$(mktemp)
remote_path="/tmp/repair-macpro-k3s-vm-${VMID}.sh"
cleanup() {
    rm -f "$remote_script"
}
trap cleanup EXIT

cat > "$remote_script" <<'REMOTE'
set -euo pipefail

need_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "Required command not found on Proxmox: $1" >&2
        return 1
    fi
}

need_cmd qm
need_cmd pvesm

if ! need_cmd virt-customize; then
    echo "Installing libguestfs-tools on Proxmox..."
    apt-get update
    apt-get install -y libguestfs-tools
fi

if ! qm status "$VMID" >/dev/null 2>&1; then
    echo "VMID $VMID does not exist." >&2
    exit 1
fi

disk_ref=$(qm config "$VMID" | awk -F': ' '/^scsi0:/ {split($2, a, ","); print a[1]; exit}')
if [[ -z "${disk_ref:-}" ]]; then
    echo "Could not find scsi0 disk for VMID $VMID." >&2
    qm config "$VMID"
    exit 1
fi

disk_path=$(pvesm path "$disk_ref")
if [[ -z "${disk_path:-}" || ! -e "$disk_path" ]]; then
    echo "Could not resolve disk path for $disk_ref." >&2
    exit 1
fi

mac=$(qm config "$VMID" \
    | sed -n 's/^net0: virtio=\([^,]*\),.*/\1/p' \
    | tr '[:upper:]' '[:lower:]' \
    | head -n1)
if [[ -z "${mac:-}" ]]; then
    echo "Could not find net0 virtio MAC for VMID $VMID." >&2
    qm config "$VMID"
    exit 1
fi

if qm status "$VMID" | grep -q 'status: running'; then
    qm shutdown "$VMID" --timeout 60 || qm stop "$VMID"
fi

tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT

printf '%s' "$SSH_KEY_B64" | base64 -d > "$tmpdir/authorized_keys"
printf '\n' >> "$tmpdir/authorized_keys"

cat > "$tmpdir/10-macpro-vm.network" <<EOF
[Match]
MACAddress=$mac

[Network]
Address=$VM_IP/$VM_CIDR
Gateway=$VM_GW
DNS=$VM_DNS
EOF

cat > "$tmpdir/10-macpro-vm.link" <<EOF
[Match]
MACAddress=$mac

[Link]
Name=eth0
EOF

cat > "$tmpdir/hosts" <<EOF
127.0.0.1 localhost
127.0.1.1 $VM_NAME

::1 localhost ip6-localhost ip6-loopback
ff02::1 ip6-allnodes
ff02::2 ip6-allrouters
EOF

cat > "$tmpdir/sudoers" <<EOF
$VM_USER ALL=(ALL) NOPASSWD:ALL
EOF

echo "Customizing guest disk: $disk_path"
virt-customize -a "$disk_path" \
    --hostname "$VM_NAME" \
    --run-command "getent group sudo >/dev/null 2>&1 || groupadd sudo" \
    --run-command "id -u '$VM_USER' >/dev/null 2>&1 || useradd -m -s /bin/bash -G sudo '$VM_USER'" \
    --mkdir "/home/$VM_USER/.ssh" \
    --mkdir "/etc/systemd/network" \
    --mkdir "/etc/sudoers.d" \
    --upload "$tmpdir/authorized_keys:/home/$VM_USER/.ssh/authorized_keys" \
    --upload "$tmpdir/10-macpro-vm.network:/etc/systemd/network/10-macpro-vm.network" \
    --upload "$tmpdir/10-macpro-vm.link:/etc/systemd/network/10-macpro-vm.link" \
    --upload "$tmpdir/hosts:/etc/hosts" \
    --upload "$tmpdir/sudoers:/etc/sudoers.d/90-$VM_USER" \
    --run-command "chmod 700 '/home/$VM_USER/.ssh'" \
    --run-command "chmod 600 '/home/$VM_USER/.ssh/authorized_keys'" \
    --run-command "chown -R '$VM_USER:$VM_USER' '/home/$VM_USER/.ssh'" \
    --run-command "chmod 0440 '/etc/sudoers.d/90-$VM_USER'" \
    --run-command "touch /etc/cloud/cloud-init.disabled" \
    --run-command "systemctl enable ssh 2>/dev/null || true" \
    --run-command "systemctl enable systemd-networkd 2>/dev/null || true" \
    --run-command "systemctl enable qemu-guest-agent 2>/dev/null || true" \
    --run-command "systemctl disable cloud-init cloud-init-local cloud-config cloud-final 2>/dev/null || true"

if ! virt-ls -a "$disk_path" /etc/ssh >/dev/null 2>&1; then
    echo "OpenSSH server is missing in the guest; installing guest packages..."
    virt-customize --network -a "$disk_path" \
        --run-command "apt-get update" \
        --run-command "DEBIAN_FRONTEND=noninteractive apt-get install -y openssh-server sudo qemu-guest-agent" \
        --run-command "systemctl enable ssh 2>/dev/null || true" \
        --run-command "systemctl enable qemu-guest-agent 2>/dev/null || true"
fi

qm start "$VMID"
qm status "$VMID"
qm config "$VMID"
REMOTE

scp -F "$SSH_CONFIG" "$remote_script" "$PVE_HOST:$remote_path"
ssh -tt -F "$SSH_CONFIG" "$PVE_HOST" \
    "VMID='$VMID' VM_NAME='$VM_NAME' VM_IP='$VM_IP' VM_CIDR='$VM_CIDR' VM_GW='$VM_GW' VM_DNS='$VM_DNS' VM_USER='$VM_USER' SSH_KEY_B64='$SSH_KEY_B64' sudo -E bash '$remote_path'; status=\$?; rm -f '$remote_path'; exit \$status"

echo
echo "Waiting for SSH on $VM_IP..."
grow_guest_root() {
    ssh -F "$SSH_CONFIG" \
        -i "${SSH_KEY_PATH%.pub}" \
        -o BatchMode=yes \
        -o IdentitiesOnly=yes \
        "$VM_USER@$VM_IP" '
set -euo pipefail

if ! command -v growpart >/dev/null 2>&1; then
    sudo apt-get update
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y cloud-guest-utils
fi

root_source=$(findmnt -n -o SOURCE /)
disk_name=$(lsblk -no PKNAME "$root_source" | head -n1)
part_name=$(lsblk -no NAME "$root_source" | head -n1)
part_num="${part_name##*[!0-9]}"

if [[ -n "$disk_name" && -n "$part_num" ]]; then
    sudo growpart "/dev/$disk_name" "$part_num" || true
fi

fs_type=$(findmnt -n -o FSTYPE /)
case "$fs_type" in
    ext*) sudo resize2fs "$root_source" ;;
    xfs) sudo xfs_growfs / ;;
    *) echo "Skipping unsupported root filesystem resize for $fs_type" ;;
esac
'
}

for _ in {1..60}; do
    if ssh -F "$SSH_CONFIG" \
        -i "${SSH_KEY_PATH%.pub}" \
        -o ConnectTimeout=3 \
        -o BatchMode=yes \
        -o IdentitiesOnly=yes \
        -o StrictHostKeyChecking=accept-new \
        "$VM_USER@$VM_IP" 'hostname' >/dev/null 2>&1; then
        echo "SSH is ready."
        echo "Ensuring guest root filesystem uses the resized disk..."
        grow_guest_root
        ssh -F "$SSH_CONFIG" \
            -i "${SSH_KEY_PATH%.pub}" \
            -o IdentitiesOnly=yes \
            "$VM_USER@$VM_IP" \
            'hostname; ip -br addr; free -h; lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS; ip route'
        exit 0
    fi
    sleep 5
done

echo "Offline repair completed, but SSH did not become ready within 5 minutes." >&2
echo "Check the Proxmox console for VMID $VMID." >&2
exit 1

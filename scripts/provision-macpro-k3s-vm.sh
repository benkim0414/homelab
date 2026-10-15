#!/usr/bin/env bash
set -euo pipefail

PVE_HOST="${PVE_HOST:-pve-macpro}"
SSH_CONFIG="${SSH_CONFIG:-$HOME/.ssh/homelab_config}"
VMID="${VMID:-210}"
VM_NAME="${VM_NAME:-k3s-05}"
VM_IP="${VM_IP:-192.168.0.22}"
VM_CIDR="${VM_CIDR:-24}"
VM_GW="${VM_GW:-192.168.0.1}"
VM_DNS="${VM_DNS:-1.1.1.1}"
VM_USER="${VM_USER:-benkim0414}"
VM_CORES="${VM_CORES:-4}"
VM_MEMORY_MB="${VM_MEMORY_MB:-16384}"
VM_DISK="${VM_DISK:-128G}"
VM_BRIDGE="${VM_BRIDGE:-vmbr0}"
PVE_STORAGE="${PVE_STORAGE:-local-lvm}"
CLOUDINIT_DRIVE="${CLOUDINIT_DRIVE:-scsi1}"
IMAGE_URL="${IMAGE_URL:-https://cloud.debian.org/images/cloud/trixie/latest/debian-13-generic-amd64.qcow2}"
IMAGE_PATH="${IMAGE_PATH:-/var/lib/vz/template/iso/debian-13-generic-amd64.qcow2}"
SSH_KEY_PATH="${SSH_KEY_PATH:-$HOME/.ssh/pi_ed25519.pub}"
RECREATE_EXISTING="${RECREATE_EXISTING:-0}"

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
This will create and start a Proxmox VM:

  PVE host:  $PVE_HOST
  VMID:      $VMID
  Hostname:  $VM_NAME
  IP:        $VM_IP/$VM_CIDR
  Gateway:   $VM_GW
  CPU/RAM:   $VM_CORES vCPU / $VM_MEMORY_MB MiB
  Disk:      $VM_DISK on $PVE_STORAGE
  CloudInit: $CLOUDINIT_DRIVE on $PVE_STORAGE
  Bridge:    $VM_BRIDGE
  User:      $VM_USER
  SSH key:   $SSH_KEY_PATH
  Recreate:  $RECREATE_EXISTING

The remote step runs with sudo on Proxmox and may prompt for your sudo password.
EOF

read -r -p "Continue? [y/N] " answer
case "$answer" in
    y|Y|yes|YES) ;;
    *) echo "Aborted."; exit 1 ;;
esac

remote_script=$(mktemp)
remote_path="/tmp/provision-macpro-k3s-vm-${VMID}.sh"
cleanup() {
    rm -f "$remote_script"
}
trap cleanup EXIT

cat > "$remote_script" <<'REMOTE'
set -euo pipefail

need_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "Required command not found on Proxmox: $1" >&2
        exit 1
    fi
}

need_cmd qm
need_cmd pvesm

if qm list | awk -v id="$VMID" -v name="$VM_NAME" \
    'NR > 1 && $1 != id && $2 == name {found=1} END {exit !found}'; then
    echo "A VM named $VM_NAME already exists. Choose another VMID or inspect manually." >&2
    qm list
    exit 1
fi

if ! pvesm status | awk 'NR > 1 {print $1}' | grep -Fxq "$PVE_STORAGE"; then
    echo "Storage $PVE_STORAGE not found." >&2
    pvesm status
    exit 1
fi

# Verify a complete image before any destructive VM operation.
need_cmd sha512sum
need_cmd curl
mkdir -p "$(dirname "$IMAGE_PATH")"
image_name="${IMAGE_URL##*/}"
checksums=$(mktemp)
trap 'rm -f "$checksums"' EXIT
curl --proto '=https' --tlsv1.2 -L --fail --silent --show-error \
    "${IMAGE_URL%/*}/SHA512SUMS" -o "$checksums"
image_sha512=$(awk -v file="$image_name" '$2 == file || $2 == "*" file {print $1}' "$checksums")
if [[ ! "$image_sha512" =~ ^[[:xdigit:]]{128}$ ]]; then
    echo "No unique SHA512 checksum for $image_name. Aborted before VM deletion." >&2
    exit 1
fi
if [[ ! -s "$IMAGE_PATH" ]]; then
    echo "Downloading Debian cloud image..."
    curl --proto '=https' --tlsv1.2 -L --fail --progress-bar \
        "$IMAGE_URL" -o "${IMAGE_PATH}.partial"
    printf '%s  %s\n' "$image_sha512" "${IMAGE_PATH}.partial" | sha512sum --check --status
    mv "${IMAGE_PATH}.partial" "$IMAGE_PATH"
else
    echo "Verifying existing Debian image..."
    printf '%s  %s\n' "$image_sha512" "$IMAGE_PATH" | sha512sum --check --status
fi
echo "Debian image SHA512 verified."
rm -f "$checksums"
trap - EXIT

if qm status "$VMID" >/dev/null 2>&1; then
    echo "VMID $VMID already exists:"
    qm config "$VMID"

    if [[ "$RECREATE_EXISTING" != "1" ]]; then
        echo
        echo "Set RECREATE_EXISTING=1 to destroy and recreate this VMID."
        exit 0
    fi

    echo
    echo "RECREATE_EXISTING=1 is set."
    read -r -p "Type DESTROY-$VMID to stop, destroy, and recreate VMID $VMID: " destroy_answer
    if [[ "$destroy_answer" != "DESTROY-$VMID" ]]; then
        echo "Destroy confirmation did not match. Aborted."
        exit 1
    fi

    if qm status "$VMID" | grep -q 'status: running'; then
        qm shutdown "$VMID" --timeout 60 || qm stop "$VMID"
    fi
    qm destroy "$VMID" --purge
fi

key_file=$(mktemp)
printf '%s' "$SSH_KEY_B64" | base64 -d > "$key_file"
printf '\n' >> "$key_file"
trap 'rm -f "$key_file"' EXIT

echo "Creating VM $VMID ($VM_NAME)..."
qm create "$VMID" \
    --name "$VM_NAME" \
    --machine q35 \
    --ostype l26 \
    --cpu host \
    --cores "$VM_CORES" \
    --memory "$VM_MEMORY_MB" \
    --net0 "virtio,bridge=$VM_BRIDGE" \
    --scsihw virtio-scsi-single \
    --agent enabled=1 \
    --serial0 socket \
    --vga serial0

qm importdisk "$VMID" "$IMAGE_PATH" "$PVE_STORAGE"
disk_ref=$(qm config "$VMID" | awk -F': ' '/^unused[0-9]+:/ {print $2; exit}')
if [[ -z "${disk_ref:-}" ]]; then
    echo "Imported disk was not found in VM config." >&2
    qm config "$VMID"
    exit 1
fi

qm set "$VMID" --scsi0 "${disk_ref},discard=on,ssd=1,iothread=1"
qm resize "$VMID" scsi0 "$VM_DISK"
qm set "$VMID" --"$CLOUDINIT_DRIVE" "$PVE_STORAGE:cloudinit"
qm set "$VMID" --boot order=scsi0
qm set "$VMID" --citype nocloud
qm set "$VMID" --ciupgrade 0
qm set "$VMID" --ciuser "$VM_USER"
qm set "$VMID" --sshkeys "$key_file"
qm set "$VMID" --ipconfig0 "ip=$VM_IP/$VM_CIDR,gw=$VM_GW"
qm set "$VMID" --nameserver "$VM_DNS"
qm set "$VMID" --onboot 1

echo "Starting VM..."
qm start "$VMID"

echo
echo "VM created:"
qm status "$VMID"
qm config "$VMID"
REMOTE

scp -F "$SSH_CONFIG" "$remote_script" "$PVE_HOST:$remote_path"
ssh -tt -F "$SSH_CONFIG" "$PVE_HOST" \
    "VMID='$VMID' VM_NAME='$VM_NAME' VM_IP='$VM_IP' VM_CIDR='$VM_CIDR' VM_GW='$VM_GW' VM_DNS='$VM_DNS' VM_USER='$VM_USER' VM_CORES='$VM_CORES' VM_MEMORY_MB='$VM_MEMORY_MB' VM_DISK='$VM_DISK' VM_BRIDGE='$VM_BRIDGE' PVE_STORAGE='$PVE_STORAGE' CLOUDINIT_DRIVE='$CLOUDINIT_DRIVE' IMAGE_URL='$IMAGE_URL' IMAGE_PATH='$IMAGE_PATH' SSH_KEY_B64='$SSH_KEY_B64' RECREATE_EXISTING='$RECREATE_EXISTING' sudo -E bash '$remote_path'; status=\$?; rm -f '$remote_path'; exit \$status"

echo
echo "Waiting for SSH on $VM_IP..."
grow_guest_root() {
    ssh -F "$SSH_CONFIG" \
        -o StrictHostKeyChecking=yes \
        -o UpdateHostKeys=no \
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
        -o StrictHostKeyChecking=yes \
        -o UpdateHostKeys=no \
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

echo "VM was created, but SSH did not become ready within 5 minutes." >&2
echo "Check the Proxmox console for $VM_NAME, then retry:" >&2
echo "  ssh -F $SSH_CONFIG -i ${SSH_KEY_PATH%.pub} -o IdentitiesOnly=yes $VM_USER@$VM_IP" >&2
exit 1

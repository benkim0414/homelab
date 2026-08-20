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
VM_CORES="${VM_CORES:-4}"
VM_MEMORY_MB="${VM_MEMORY_MB:-16384}"
VM_DISK="${VM_DISK:-120G}"
VM_BRIDGE="${VM_BRIDGE:-vmbr0}"
PVE_STORAGE="${PVE_STORAGE:-local-lvm}"
IMAGE_URL="${IMAGE_URL:-https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-nocloud-amd64.qcow2}"
IMAGE_PATH="${IMAGE_PATH:-/var/lib/vz/template/iso/debian-12-nocloud-amd64.qcow2}"
SSH_KEY_PATH="${SSH_KEY_PATH:-$HOME/.ssh/codex_homelab_ed25519.pub}"
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

if qm list | awk 'NR > 1 {print $2}' | grep -Fxq "$VM_NAME"; then
    echo "A VM named $VM_NAME already exists. Choose another VMID or inspect manually." >&2
    qm list
    exit 1
fi

if ! pvesm status | awk 'NR > 1 {print $1}' | grep -Fxq "$PVE_STORAGE"; then
    echo "Storage $PVE_STORAGE not found." >&2
    pvesm status
    exit 1
fi

mkdir -p "$(dirname "$IMAGE_PATH")"
if [[ ! -s "$IMAGE_PATH" ]]; then
    echo "Downloading Debian cloud image..."
    if command -v curl >/dev/null 2>&1; then
        curl -L --fail --progress-bar "$IMAGE_URL" -o "$IMAGE_PATH"
    elif command -v wget >/dev/null 2>&1; then
        wget -O "$IMAGE_PATH" "$IMAGE_URL"
    else
        echo "Neither curl nor wget is available on Proxmox." >&2
        exit 1
    fi
else
    echo "Using existing image: $IMAGE_PATH"
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
qm set "$VMID" --ide2 "$PVE_STORAGE:cloudinit"
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
    "VMID='$VMID' VM_NAME='$VM_NAME' VM_IP='$VM_IP' VM_CIDR='$VM_CIDR' VM_GW='$VM_GW' VM_DNS='$VM_DNS' VM_USER='$VM_USER' VM_CORES='$VM_CORES' VM_MEMORY_MB='$VM_MEMORY_MB' VM_DISK='$VM_DISK' VM_BRIDGE='$VM_BRIDGE' PVE_STORAGE='$PVE_STORAGE' IMAGE_URL='$IMAGE_URL' IMAGE_PATH='$IMAGE_PATH' SSH_KEY_B64='$SSH_KEY_B64' RECREATE_EXISTING='$RECREATE_EXISTING' sudo -E bash '$remote_path'; status=\$?; rm -f '$remote_path'; exit \$status"

echo
echo "Waiting for SSH on $VM_IP..."
for _ in {1..60}; do
    if ssh -F "$SSH_CONFIG" \
        -o ConnectTimeout=3 \
        -o BatchMode=yes \
        -o StrictHostKeyChecking=accept-new \
        "$VM_USER@$VM_IP" 'hostname' >/dev/null 2>&1; then
        echo "SSH is ready."
        ssh -F "$SSH_CONFIG" "$VM_USER@$VM_IP" \
            'hostname; ip -br addr; free -h; lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS; ip route'
        exit 0
    fi
    sleep 5
done

echo "VM was created, but SSH did not become ready within 5 minutes." >&2
echo "Check the Proxmox console for $VM_NAME, then retry:" >&2
echo "  ssh -F $SSH_CONFIG $VM_USER@$VM_IP" >&2
exit 1

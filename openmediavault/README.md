# Raspberry Pi 5 NAS Setup with OpenMediaVault and ZFS

Complete guide to setting up a production-ready NAS on Raspberry Pi 5 with OpenMediaVault 7, ZFS RAID10, and NFS integration for Kubernetes (K3s).

## Table of Contents

- [Hardware](#hardware)
- [Overview](#overview)
- [Architecture](#architecture)
- [Initial Setup](#initial-setup)
- [OpenMediaVault Installation](#openmediavault-installation)
- [ZFS Configuration](#zfs-configuration)
- [Directory Structure](#directory-structure)
- [NFS Configuration](#nfs-configuration)
- [SMB Configuration](#smb-configuration)
- [Monitoring and Maintenance](#monitoring-and-maintenance)
- [K3s Integration](#k3s-integration)
- [Troubleshooting](#troubleshooting)

---

## Hardware

### Components

- **SBC**: Raspberry Pi 5 (16GB RAM)
- **Storage HAT**: Radxa Penta SATA HAT
- **SSDs**: 4x Crucial BX500 500GB SATA SSDs
- **Power Supply**: Radxa Power DC12 60W (required for Penta SATA HAT + 4 SSDs)
- **Cooling**: Active cooling recommended (Radxa HAT includes fan header)
- **SD Card**: 128GB+ for OS (used 119.4GB in this setup)

### Network

- Network range: 192.168.0.0/24 (adjust for your network)
- NAS IP: 192.168.0.40 (static IP recommended)

---

## Overview

### What This Setup Provides

**Storage Configuration:**

- ~930GB usable storage (RAID10 with 4x 500GB drives)
- ZFS filesystem with compression and optimization
- Two main datasets: `k3s` (apps) and `media` (files)
- NFS exports for K3s cluster integration
- SMB shares for workstation access

**Use Cases:**

- Immich (photo management with PostgreSQL)
- \*arr stack (Sonarr, Radarr, Lidarr, Prowlarr, Bazarr)
- Jellyfin (media server)
- Download clients (Transmission, qBittorrent)
- Any K3s workload requiring persistent storage

**Key Features:**

- RAID10: Best performance + redundancy for SSD setup
- ZFS: Enterprise-grade filesystem with compression
- OMV: Web UI for management and monitoring
- NFS: High-performance network storage for K3s
- SMB: Easy file access from Windows/Mac/Linux

---

## Architecture

### Storage Layout

```
Hardware Layer:
├── /dev/sda - Crucial BX500 500GB ─┐
├── /dev/sdb - Crucial BX500 500GB ─┘ Mirror 1
├── /dev/sdc - Crucial BX500 500GB ─┐
└── /dev/sdd - Crucial BX500 500GB ─┘ Mirror 2

ZFS Pool: storage (RAID10, ~930GB usable)
├── Dataset: storage/k3s (300GB quota)
│   └── /storage/k3s/
│       ├── immich/
│       │   ├── library/    (Immich photos)
│       │   └── redis/      (Immich cache)
│       ├── sonarr/
│       ├── radarr/
│       ├── lidarr/
│       ├── prowlarr/
│       ├── bazarr/
│       ├── jellyfin/
│       ├── transmission/
│       └── qbittorrent/
│
└── Dataset: storage/media (600GB quota)
    └── /storage/media/
        ├── movies/
        ├── tv/
        ├── music/
        └── downloads/
            ├── complete/
            └── incomplete/

NFS Exports (NFSv4):
├── /k3s-storage → /storage/k3s (bind mount via /export/k3s-storage)
└── /media-storage → /storage/media (bind mount via /export/media-storage)

SMB Shares:
├── media-storage → /storage/media
└── (optional) k3s-storage → /storage/k3s
```

### K3s Storage Integration

```
K3s Cluster:
├── StorageClass: nfs-k3s (for app data)
├── StorageClass: nfs-media (for media files)
├── StorageClass: local-path (for PostgreSQL databases)
│
├── PersistentVolume: k3s-nfs-pv (300Gi, RWX)
│   └── NFS: 192.168.0.40:/k3s-storage
│
└── PersistentVolume: media-nfs-pv (600Gi, RWX)
    └── NFS: 192.168.0.40:/media-storage

Application Storage Strategy:
├── Immich:
│   ├── Photos: NFS (k3s-nfs-pv, subPath: immich/library)
│   ├── Redis: NFS (k3s-nfs-pv, subPath: immich/redis)
│   └── PostgreSQL: Local storage (local-path, on K3s node)
│
├── *arr stack:
│   ├── App configs: NFS (k3s-nfs-pv, subPath: <app-name>)
│   └── Media files: NFS (media-nfs-pv)
│
└── Jellyfin:
    ├── Config: NFS (k3s-nfs-pv, subPath: jellyfin)
    └── Media: NFS (media-nfs-pv, read-only)
```

---

## Initial Setup

### 1. Raspberry Pi OS Installation

**Install Raspberry Pi OS Lite (64-bit):**

```bash
# Use Raspberry Pi Imager
# OS: Raspberry Pi OS Lite (64-bit)
# Configure: SSH, username, WiFi/Ethernet, hostname
```

**First boot:**

```bash
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

### 2. Enable PCIe for Radxa Penta SATA HAT

**Edit boot configuration:**

```bash
sudo nano /boot/firmware/config.txt
```

**Add these lines at the bottom:**

```ini
# Enable PCIe Gen 3 (required for Radxa Penta SATA HAT)
dtparam=pciex1_gen=3

# Enable PCIe
dtparam=pciex1
```

**Save and reboot:**

```bash
sudo reboot
```

**Verify PCIe and drives are detected:**

```bash
# Check PCIe controller
lspci

# Should show:
# 0000:01:00.0 SATA controller: JMicron Technology Corp. JMB58x AHCI SATA controller

# Check drives
lsblk

# Should show sda, sdb, sdc, sdd (your 4 SSDs)
```

---

## OpenMediaVault Installation

### Install OMV 7

```bash
# Download and run official install script
wget -O - https://github.com/OpenMediaVault-Plugin-Developers/installScript/raw/master/install | sudo bash
```

**Installation takes 15-30 minutes.**

### Initial OMV Configuration

**Access web interface:**

```
URL: http://<raspberry-pi-ip>
Default login: admin
Default password: openmediavault
```

**Immediately change default password:**

1. Go to **System → General Settings → Web Administrator Password**
1. Set new password
1. Click **Save**

### Install OMV-Extras and ZFS Plugin

**Install OMV-Extras:**

```bash
wget -O - https://github.com/OpenMediaVault-Plugin-Developers/packages/raw/master/install | sudo bash
```

**In OMV Web UI:**

1. Go to **System → Plugins**
1. Search for and install: `openmediavault-zfs`
1. Reboot after installation

---

## ZFS Configuration

### Install ZFS Utilities

```bash
# Install ZFS kernel module
sudo apt install -y linux-headers-rpi-v8 zfs-dkms zfsutils-linux

# Enable ZFS module
sudo modprobe zfs

# Make it load on boot
echo zfs | sudo tee -a /etc/modules
```

### Create ZFS RAID10 Pool

**Why RAID10:**

- Best performance for mixed I/O workloads (Immich + databases)
- Fast rebuild times (~30-60 min vs 1-2 hours for RAIDZ1)
- Can lose 1 drive per mirror (2 drives in best case)
- SSD-optimized (no parity calculations)
- ~930GB usable (50% efficiency with 4 drives)

**Create pool via CLI:**

```bash
# OMV UI doesn't properly support RAID10, use CLI
sudo zpool create -f -o ashift=12 storage \
  mirror /dev/disk/by-id/<ata-DRIVE1-serial> /dev/disk/by-id/<ata-DRIVE2-serial> \
  mirror /dev/disk/by-id/<ata-DRIVE3-serial> /dev/disk/by-id/<ata-DRIVE4-serial>

# To find your drive IDs:
# ls -l /dev/disk/by-id/ | grep -v part
```

**Parameter explanations:**

- `-f`: Force (overwrite any existing signatures)
- `-o ashift=12`: Optimize for 4K sectors (critical for SSDs)
- `storage`: Pool name
- `mirror <id1> <id2>`: First mirror pair
- `mirror <id3> <id4>`: Second mirror pair
- Using `/dev/disk/by-id/` paths ensures stable device references across reboots

**Set pool-level properties:**

```bash
# Enable automatic pool expansion
sudo zpool set autoexpand=on storage

# Set failmode to continue
sudo zpool set failmode=continue storage

# Enable autotrim for SSDs (important!)
sudo zpool set autotrim=on storage
```

**Verify pool creation:**

```bash
sudo zpool status
```

**Expected output:**

```
  pool: storage
 state: ONLINE
config:

        NAME        STATE     READ WRITE CKSUM
        storage     ONLINE       0     0     0
          mirror-0  ONLINE       0     0     0
            sda     ONLINE       0     0     0
            sdb     ONLINE       0     0     0
          mirror-1  ONLINE       0     0     0
            sdc     ONLINE       0     0     0
            sdd     ONLINE       0     0     0
```

### Import Pool into OMV

**In OMV Web UI:**

1. Go to **Storage → ZFS → Pools**
1. Click **Scan** or **Refresh** button
1. Pool `storage` should appear with status “ONLINE”

**If it doesn’t appear:**

```bash
sudo omv-salt deploy run zfs
sudo systemctl restart openmediavault-engined
# Refresh browser
```

### Create ZFS Datasets

**In OMV Web UI:**

1. Go to **Storage → ZFS → Filesystems**

**Create k3s dataset:**

- Click **+ Add**
- Name: `k3s`
- Pool: `storage`
- Click **Save** and **Apply**

**Create media dataset:**

- Click **+ Add**
- Name: `media`
- Pool: `storage`
- Click **Save** and **Apply**

### Optimize Dataset Properties

**OMV UI doesn’t expose all ZFS properties, set via CLI:**

**K3s dataset (mixed workload - apps + databases):**

```bash
sudo zfs set recordsize=128K storage/k3s
sudo zfs set compression=lz4 storage/k3s
sudo zfs set atime=off storage/k3s
sudo zfs set primarycache=all storage/k3s
sudo zfs set logbias=latency storage/k3s
sudo zfs set xattr=sa storage/k3s
sudo zfs set acltype=posixacl storage/k3s
```

**Media dataset (large sequential files - videos):**

```bash
sudo zfs set recordsize=1M storage/media
sudo zfs set compression=lz4 storage/media
sudo zfs set atime=off storage/media
sudo zfs set primarycache=all storage/media
sudo zfs set logbias=throughput storage/media
sudo zfs set xattr=sa storage/media
sudo zfs set acltype=posixacl storage/media
```

**Set quotas (optional but recommended):**

```bash
# Reserve space per dataset
sudo zfs set quota=300G storage/k3s
sudo zfs set quota=600G storage/media

# NOTE: 300G + 600G = 900GB of ~930GB usable, leaving ~30GB for ZFS
# metadata, snapshots, and overhead. If you plan to use automated
# snapshots (e.g., sanoid), consider lowering these quotas to leave
# more headroom.

# Or use reservations to guarantee minimum space
sudo zfs set reservation=200G storage/k3s
sudo zfs set reservation=400G storage/media
```

**Verify properties:**

```bash
sudo zfs get all storage/k3s | grep -E "recordsize|compression|atime|primarycache|logbias|quota"
sudo zfs get all storage/media | grep -E "recordsize|compression|atime|primarycache|logbias|quota"
```

### Verify in OMV File Systems

**In OMV Web UI:**

1. Go to **Storage → File Systems**
1. Should see:

- `storage` - 930GB - Status: **Available** ✅
- `storage/k3s` - 930GB - Status: **Available** ✅
- `storage/media` - 930GB - Status: **Available** ✅

All should show green “Available” status with checkmarks in “Mounted” column.

---

## Directory Structure

### Create Directory Structure

**Create application directories:**

```bash
# Immich (nested structure - complex app)
sudo mkdir -p /storage/k3s/immich/library
sudo mkdir -p /storage/k3s/immich/redis

# *arr apps (flat structure - simpler apps)
sudo mkdir -p /storage/k3s/sonarr
sudo mkdir -p /storage/k3s/radarr
sudo mkdir -p /storage/k3s/lidarr
sudo mkdir -p /storage/k3s/prowlarr
sudo mkdir -p /storage/k3s/bazarr

# Media player
sudo mkdir -p /storage/k3s/jellyfin

# Download clients
sudo mkdir -p /storage/k3s/transmission
sudo mkdir -p /storage/k3s/qbittorrent

# Media directories (required structure for *arr apps)
sudo mkdir -p /storage/media/movies
sudo mkdir -p /storage/media/tv
sudo mkdir -p /storage/media/music
sudo mkdir -p /storage/media/downloads/complete
sudo mkdir -p /storage/media/downloads/incomplete
```

### Set Ownership and Permissions

**Most containers run as UID 1000:**

```bash
# Immich
sudo chown -R 1000:1000 /storage/k3s/immich
sudo chmod -R 775 /storage/k3s/immich

# *arr apps
sudo chown -R 1000:1000 /storage/k3s/sonarr
sudo chown -R 1000:1000 /storage/k3s/radarr
sudo chown -R 1000:1000 /storage/k3s/lidarr
sudo chown -R 1000:1000 /storage/k3s/prowlarr
sudo chown -R 1000:1000 /storage/k3s/bazarr

sudo chmod -R 775 /storage/k3s/sonarr
sudo chmod -R 775 /storage/k3s/radarr
sudo chmod -R 775 /storage/k3s/lidarr
sudo chmod -R 775 /storage/k3s/prowlarr
sudo chmod -R 775 /storage/k3s/bazarr

# Jellyfin
sudo chown -R 1000:1000 /storage/k3s/jellyfin
sudo chmod -R 775 /storage/k3s/jellyfin

# Download clients
sudo chown -R 1000:1000 /storage/k3s/transmission
sudo chown -R 1000:1000 /storage/k3s/qbittorrent
sudo chmod -R 775 /storage/k3s/transmission
sudo chmod -R 775 /storage/k3s/qbittorrent

# Media
sudo chown -R 1000:1000 /storage/media
sudo chmod -R 775 /storage/media
```

### Verify Structure

```bash
# Verify k3s structure
tree -L 3 /storage/k3s/

# Expected output:
# /storage/k3s/
# ├── immich/
# │   ├── library/
# │   └── redis/
# ├── sonarr/
# ├── radarr/
# ├── lidarr/
# ├── prowlarr/
# ├── bazarr/
# ├── jellyfin/
# ├── transmission/
# └── qbittorrent/

# Verify media structure
tree -L 2 /storage/media/

# Expected output:
# /storage/media/
# ├── movies/
# ├── tv/
# ├── music/
# └── downloads/
#     ├── complete/
#     └── incomplete/

# Verify permissions (should show 1000:1000)
ls -lan /storage/k3s/
ls -lan /storage/k3s/immich/
ls -lan /storage/media/
```

---

## NFS Configuration

### Create OMV Shared Folders

**In OMV Web UI:**

1. Go to **Storage → Shared Folders**

**Create k3s-storage shared folder:**

- Click **+ Add**
- Name: `k3s-storage`
- File system: Select `storage/k3s` from dropdown
- Relative path: `/`
- Permissions: Read/Write = `Everyone` (or `Administrators`)
- Click **Save**

**Create media-storage shared folder:**

- Click **+ Add**
- Name: `media-storage`
- File system: Select `storage/media` from dropdown
- Relative path: `/`
- Permissions: Read/Write = `Everyone`
- Click **Save**

Click **Apply** (yellow banner)

### Enable NFS Service

**In OMV Web UI:**

1. Go to **Services → NFS → Settings**
1. Enable: ✓ Check
1. Versions: Leave all checked (NFSv3, NFSv4)
1. Click **Save** and **Apply**

### Create NFS Shares

**In OMV Web UI:**

1. Go to **Services → NFS → Shares**

**Create k3s NFS share:**

- Click **+ Add**
- Shared folder: `k3s-storage`
- Client: `192.168.0.0/24` (adjust to your network)
- Privilege: `Read/Write`
- Extra options:

  ```
  sync,no_subtree_check,no_root_squash,insecure
  ```

- Click **Save**

**Create media NFS share:**

- Click **+ Add**
- Shared folder: `media-storage`
- Client: `192.168.0.0/24`
- Privilege: `Read/Write`
- Extra options:

  ```
  sync,no_subtree_check,no_root_squash,insecure
  ```

- Click **Save**

Click **Apply**

### Create Bind Mounts

**OMV creates `/export` directories but they need to be bind mounted to actual ZFS storage:**

```bash
# Check if bind mounts already exist
mount | grep export

# If not mounted, create bind mounts
sudo mount --bind /storage/k3s /export/k3s-storage
sudo mount --bind /storage/media /export/media-storage

# Verify
mount | grep export
# Should show:
# storage/k3s on /export/k3s-storage type zfs (rw,noatime,xattr,posixacl,casesensitive)
# storage/media on /export/media-storage type zfs (rw,noatime,xattr,posixacl,casesensitive)
```

### Make Bind Mounts Permanent

```bash
sudo nano /etc/fstab
```

**Add at the end:**

```bash
# NFS exports bind mounts for ZFS storage
/storage/k3s    /export/k3s-storage    none    bind    0    0
/storage/media  /export/media-storage  none    bind    0    0
```

**Test fstab entries work:**

```bash
# Unmount
sudo umount /export/k3s-storage
sudo umount /export/media-storage

# Remount using fstab
sudo mount /export/k3s-storage
sudo mount /export/media-storage

# Verify
mount | grep export
```

### Restart NFS Service

```bash
sudo exportfs -ra
sudo systemctl restart nfs-kernel-server
```

### Verify NFS Configuration

```bash
# Check exports
sudo exportfs -v

# Should show:
# /export/k3s-storage    192.168.0.0/24(...)
# /export/media-storage  192.168.0.0/24(...)

# Show mountable shares
showmount -e localhost

# Should show:
# Export list for localhost:
# /export/k3s-storage   192.168.0.0/24
# /export/media-storage 192.168.0.0/24

# Verify export directories have content
ls -la /export/k3s-storage/
ls -la /export/media-storage/
```

### Test NFS from K3s Node

**On a K3s node (not the NAS):**

```bash
# Install NFS client
sudo apt install -y nfs-common

# Show available exports
showmount -e 192.168.0.40

# IMPORTANT: NFSv4 strips /export prefix
# Mount with /k3s-storage NOT /export/k3s-storage
sudo mkdir -p /mnt/test-k3s
sudo mount -t nfs -o nfsvers=4.1 192.168.0.40:/k3s-storage /mnt/test-k3s

# Verify directory structure
ls -la /mnt/test-k3s/
# Should show: immich/ sonarr/ radarr/ etc.

ls -la /mnt/test-k3s/immich/
# Should show: library/ redis/

# Test write permissions
sudo touch /mnt/test-k3s/immich/library/test-file
ls -la /mnt/test-k3s/immich/library/

# Verify on NAS
# On NAS: ls -la /storage/k3s/immich/library/
# Should see test-file

# Cleanup
sudo rm /mnt/test-k3s/immich/library/test-file
sudo umount /mnt/test-k3s

# Test media storage
sudo mkdir -p /mnt/test-media
sudo mount -t nfs -o nfsvers=4.1 192.168.0.40:/media-storage /mnt/test-media

ls -la /mnt/test-media/
# Should show: movies/ tv/ music/ downloads/

# Cleanup
sudo umount /mnt/test-media
```

**Key NFSv4 Behavior:**

- Export path: `/export/k3s-storage`
- Mount path: `/k3s-storage` (without /export prefix)
- NFSv4 automatically uses `/export` as pseudo filesystem root

---

## SMB Configuration

### Enable SMB Service

**In OMV Web UI:**

1. Go to **Services → SMB/CIFS → Settings**
1. Configure:

- Enable: ✓ Check
- Workgroup: `WORKGROUP` (or your network’s workgroup)
- Description: `rpi5-4bx500 NAS`
- Local Master Browser: Yes (optional)

1. Click **Save** and **Apply**

### Create SMB Shares

**In OMV Web UI:**

1. Go to **Services → SMB/CIFS → Shares**

**Create media share:**

- Click **+ Add**
- Enabled: ✓ Check
- Shared folder: `media-storage`
- Comment: `Media Files`
- Public: No (requires authentication)
- Read only: No
- Browseable: Yes
- Guest allowed: No
- Click **Save** and **Apply**

### Create Samba User

**Samba users must be added via CLI:**

```bash
# Add existing Linux user to Samba
sudo smbpasswd -a pi
# Enter password when prompted

# Enable the user
sudo smbpasswd -e pi
```

### Test SMB Access

**From Windows:**

```
\\192.168.0.40\media-storage
Username: pi
Password: (your password)
```

**From macOS:**

```
Finder → Go → Connect to Server (⌘K)
smb://192.168.0.40/media-storage
```

**From Linux:**

```bash
# List shares
smbclient -L //192.168.0.40 -U pi

# Mount
sudo mkdir -p /mnt/smb-media
sudo mount -t cifs //192.168.0.40/media-storage /mnt/smb-media -o username=pi
```

---

## Monitoring and Maintenance

### Enable SMART Monitoring

**In OMV Web UI:**

1. Go to **Storage → S.M.A.R.T. → Settings**
1. Configure:

- Enable: ✓ Check
- Interval: 1800 (30 minutes)
- Temperature difference: 10
- Temperature informational: 50
- Temperature critical: 65

1. Click **Save** and **Apply**
1. Go to **Storage → S.M.A.R.T. → Devices**
1. For each drive (sda, sdb, sdc, sdd):

- Select drive
- Click **Edit**
- Enable: ✓ Check
- Monitor: ✓ Check
- Click **Save**

1. Click **Apply**

### Setup Email Notifications

**In OMV Web UI:**

1. Go to **System → Notification → Settings**
1. Configure:

- Enable: ✓ Check
- SMTP server: (e.g., smtp.gmail.com)
- SMTP port: 587 (or 465 for SSL)
- Encryption: STARTTLS or SSL/TLS
- Sender email: your.email@example.com
- Authentication required: ✓ Check
- Username: your.email@example.com
- Password: (your app password for Gmail)
- Recipient: your.email@example.com

1. Click **Send test email**
1. Click **Save** and **Apply**

### Schedule ZFS Scrubs

**In OMV Web UI:**

1. Go to **System → Scheduled Tasks**
1. Click **+ Add → Cron Job**
1. Configure:

- Enabled: ✓ Check
- User: `root`
- Command: `zpool scrub storage`
- Schedule:
  - Minute: 0
  - Hour: 2
  - Day of month: 1
  - Month: \*
  - Day of week: \* (any)
- Or use Predefined: `Monthly`
- Comment: `Monthly ZFS scrub`

1. Click **Save** and **Apply**

### ZFS Maintenance Commands

**Check pool health:**

```bash
sudo zpool status
sudo zpool list
```

**Check dataset usage:**

```bash
sudo zfs list
df -h | grep storage
```

**Run manual scrub:**

```bash
sudo zpool scrub storage

# Watch progress
sudo zpool status
```

**Create snapshots:**

```bash
# Manual snapshots
sudo zfs snapshot storage/k3s@backup-$(date +%Y%m%d-%H%M)
sudo zfs snapshot storage/media@backup-$(date +%Y%m%d)

# List snapshots
sudo zfs list -t snapshot
```

**Monitor I/O:**

```bash
# Pool I/O stats (refresh every 1 second)
sudo zpool iostat storage 1

# Dataset I/O stats
sudo zfs iostat storage/k3s 1
```

---

## K3s Integration

### Prerequisites on K3s Nodes

**Install NFS client on all K3s nodes:**

```bash
sudo apt install -y nfs-common

# Enable rpcbind
sudo systemctl enable rpcbind
sudo systemctl start rpcbind
```

### Create Namespaces

```bash
kubectl create namespace immich
kubectl create namespace media
kubectl create namespace downloads
```

### Create StorageClasses

**File: `storage-classes.yaml`**

```yaml
---
# StorageClass for K3s app data (NFS)
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: nfs-k3s
provisioner: kubernetes.io/no-provisioner
volumeBindingMode: Immediate
---
# StorageClass for media data (NFS)
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: nfs-media
provisioner: kubernetes.io/no-provisioner
volumeBindingMode: Immediate
```

**Apply:**

```bash
kubectl apply -f storage-classes.yaml
kubectl get storageclass
```

### Create PersistentVolumes

**File: `persistent-volumes.yaml`**

```yaml
---
# PersistentVolume for K3s apps
apiVersion: v1
kind: PersistentVolume
metadata:
  name: k3s-nfs-pv
  labels:
    type: nfs
    storage: k3s
spec:
  capacity:
    storage: 300Gi
  volumeMode: Filesystem
  accessModes:
    - ReadWriteMany
  persistentVolumeReclaimPolicy: Retain
  storageClassName: nfs-k3s
  mountOptions:
    - hard
    - nfsvers=4.1
    - noatime
    - rsize=1048576
    - wsize=1048576
  nfs:
    server: 192.168.0.40 # Your NAS IP
    path: "/k3s-storage" # Note: no /export prefix for NFSv4
---
# PersistentVolume for media files
apiVersion: v1
kind: PersistentVolume
metadata:
  name: media-nfs-pv
  labels:
    type: nfs
    storage: media
spec:
  capacity:
    storage: 600Gi
  volumeMode: Filesystem
  accessModes:
    - ReadWriteMany
  persistentVolumeReclaimPolicy: Retain
  storageClassName: nfs-media
  mountOptions:
    - hard
    - nfsvers=4.1
    - noatime
    - rsize=1048576
    - wsize=1048576
  nfs:
    server: 192.168.0.40
    path: "/media-storage" # Note: no /export prefix for NFSv4
```

**Apply:**

```bash
kubectl apply -f persistent-volumes.yaml
kubectl get pv
```

**Expected output:**

```
NAME           CAPACITY   ACCESS MODES   RECLAIM POLICY   STATUS      STORAGECLASS
k3s-nfs-pv     300Gi      RWX            Retain           Available   nfs-k3s
media-nfs-pv   600Gi      RWX            Retain           Available   nfs-media
```

### Example: Immich PersistentVolumeClaims

**File: `immich-storage.yaml`**

```yaml
---
# Immich library storage (photos)
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: immich-library
  namespace: immich
spec:
  storageClassName: nfs-k3s
  accessModes:
    - ReadWriteMany
  resources:
    requests:
      storage: 100Gi
  selector:
    matchLabels:
      storage: k3s
---
# Immich Redis storage (cache)
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: immich-redis
  namespace: immich
spec:
  storageClassName: nfs-k3s
  accessModes:
    - ReadWriteMany
  resources:
    requests:
      storage: 1Gi
  selector:
    matchLabels:
      storage: k3s
---
# Immich PostgreSQL storage (local storage - NOT NFS)
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: immich-postgres
  namespace: immich
spec:
  storageClassName: local-path # K3s built-in local storage
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 20Gi
```

### Example: Immich Deployment with Storage

**Key points for using storage in deployments:**

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: immich
  namespace: immich
spec:
  template:
    spec:
      securityContext:
        fsGroup: 1000 # Ensures NFS mount has correct group
      containers:
        - name: immich
          image: ghcr.io/immich-app/immich-server:latest
          securityContext:
            runAsUser: 1000
            runAsGroup: 1000
          volumeMounts:
            - name: library
              mountPath: /usr/src/app/upload
              subPath: immich/library # Uses /storage/k3s/immich/library
      volumes:
        - name: library
          persistentVolumeClaim:
            claimName: immich-library
```

**PostgreSQL uses local storage (better performance):**

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: immich-postgres
  namespace: immich
spec:
  template:
    spec:
      containers:
        - name: postgres
          image: postgres:16-alpine
          securityContext:
            runAsUser: 999 # PostgreSQL runs as UID 999
            runAsGroup: 999
          volumeMounts:
            - name: data
              mountPath: /var/lib/postgresql/data
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: immich-postgres # Uses local-path storage
```

### Why PostgreSQL on Local Storage

**PostgreSQL should NOT use NFS:**

- ❌ Risk of data corruption with network issues
- ❌ fsync reliability concerns
- ❌ File locking can be unreliable on NFS
- ❌ 10-100x slower than local disk

**Use K3s local-path storage instead:**

- ✅ Fast (no network latency)
- ✅ Reliable (direct disk access)
- ✅ Small dataset (~1-5GB for Immich metadata)
- ✅ PostgreSQL best practices

**Location on K3s node:**

```
/var/lib/rancher/k3s/storage/immich-postgres/
```

---

## Troubleshooting

### ZFS Pool Issues

**Pool not showing in OMV:**

```bash
# Force OMV to detect pool
sudo omv-salt deploy run zfs
sudo systemctl restart openmediavault-engined
# Refresh browser
```

**Check pool health:**

```bash
sudo zpool status
sudo zpool list
```

**Pool degraded (drive failure):**

```bash
# Check which drive failed
sudo zpool status

# Replace failed drive
sudo zpool replace storage /dev/sdX /dev/sdY

# Monitor resilver progress
watch -n 5 'sudo zpool status'
```

### NFS Mount Issues

**“No such file or directory” when mounting:**

**Cause:** Bind mounts not active or NFS cache issue

**Solution:**

```bash
# On NAS - verify bind mounts
mount | grep export

# If missing, recreate
sudo mount --bind /storage/k3s /export/k3s-storage
sudo mount --bind /storage/media /export/media-storage

# Restart NFS
sudo exportfs -ra
sudo systemctl restart nfs-kernel-server

# Verify exports have content
ls -la /export/k3s-storage/
ls -la /export/media-storage/
```

**NFSv4 path issues:**

**Remember:** NFSv4 strips `/export` prefix

- ✅ Mount: `192.168.0.40:/k3s-storage`
- ❌ Don’t use: `192.168.0.40:/export/k3s-storage`

**Debugging NFS mounts:**

```bash
# On K3s node - verbose mount
sudo mount -t nfs -o nfsvers=4.1 -vvv 192.168.0.40:/k3s-storage /mnt/test

# Check RPC info
rpcinfo -p 192.168.0.40

# Test connectivity
nc -zv 192.168.0.40 2049
```

### Permission Issues

**K3s pods can’t write to NFS:**

**Check ownership:**

```bash
# On NAS
ls -lan /storage/k3s/immich/

# Should show 1000:1000
# If not, fix:
sudo chown -R 1000:1000 /storage/k3s/immich
sudo chmod -R 775 /storage/k3s/immich
```

**In pod deployment, ensure securityContext:**

```yaml
securityContext:
  runAsUser: 1000
  runAsGroup: 1000
  fsGroup: 1000 # Important for NFS!
```

### OMV Web UI Issues

**Can’t access OMV web interface:**

```bash
# Check OMV is running
sudo systemctl status openmediavault-engined

# Restart OMV
sudo systemctl restart openmediavault-engined

# Check network
ip addr show
```

**Forgotten admin password:**

```bash
# Reset to default (openmediavault)
sudo omv-firstaid
# Choose: Configure web control panel
```

### Performance Issues

**Slow NFS performance:**

**Check network:**

```bash
# On K3s node - test network speed to NAS
iperf3 -c 192.168.0.40
```

**Check ZFS ARC (cache):**

```bash
# On NAS
cat /proc/spl/kstat/zfs/arcstats | grep -E "^size|^c_max"
```

**Monitor I/O:**

```bash
# Real-time pool stats
sudo zpool iostat storage 1

# Per-dataset stats
sudo zfs iostat storage/k3s 1
```

---

## Configuration Summary

### Final Configuration Checklist

**Hardware:**

- ✅ Raspberry Pi 5 with Radxa Penta SATA HAT
- ✅ 4x Crucial BX500 500GB SSDs
- ✅ PCIe enabled in `/boot/firmware/config.txt`
- ✅ All drives detected (`lsblk` shows sda, sdb, sdc, sdd)

**ZFS:**

- ✅ Pool: `storage` (RAID10, ~930GB usable)
- ✅ Dataset: `storage/k3s` (300GB quota, 128K recordsize)
- ✅ Dataset: `storage/media` (600GB quota, 1M recordsize)
- ✅ Autotrim enabled for SSDs
- ✅ Monthly scrub scheduled

**Directory Structure:**

- ✅ `/storage/k3s/immich/{library,redis}`
- ✅ `/storage/k3s/{sonarr,radarr,lidarr,prowlarr,bazarr,jellyfin}`
- ✅ `/storage/k3s/{transmission,qbittorrent}`
- ✅ `/storage/media/{movies,tv,music,downloads/{complete,incomplete}}`
- ✅ All owned by 1000:1000 with 775 permissions

**NFS:**

- ✅ Service enabled in OMV
- ✅ Bind mounts: `/storage/k3s` → `/export/k3s-storage`
- ✅ Bind mounts: `/storage/media` → `/export/media-storage`
- ✅ Bind mounts in `/etc/fstab` (permanent)
- ✅ Exports: `/k3s-storage` and `/media-storage` (NFSv4)
- ✅ Tested from K3s nodes

**SMB:**

- ✅ Service enabled in OMV
- ✅ Share: `media-storage`
- ✅ Samba user created
- ✅ Tested from workstation

**K3s:**

- ✅ StorageClasses: nfs-k3s, nfs-media, local-path
- ✅ PersistentVolumes: k3s-nfs-pv, media-nfs-pv
- ✅ NFS client installed on all nodes
- ✅ Namespaces created: immich, media, downloads

**Monitoring:**

- ✅ SMART monitoring enabled
- ✅ Email notifications configured
- ✅ Monthly ZFS scrubs scheduled
- ✅ Dashboard accessible

### Key File Locations

**Configuration Files:**

- `/etc/fstab` - Bind mounts for NFS exports
- `/etc/exports` - NFS exports (auto-generated by OMV)
- `/etc/samba/smb.conf` - SMB shares (managed by OMV)
- `/boot/firmware/config.txt` - PCIe configuration

**Storage Paths:**

- `/storage/k3s/` - ZFS dataset for K3s apps
- `/storage/media/` - ZFS dataset for media files
- `/export/k3s-storage/` - NFS export path (bind mount)
- `/export/media-storage/` - NFS export path (bind mount)

**K3s Paths (on K3s nodes):**

- `/var/lib/rancher/k3s/storage/` - Local-path storage
- NFS mounts: `192.168.0.40:/k3s-storage`
- NFS mounts: `192.168.0.40:/media-storage`

---

## Additional Resources

### Documentation References

- **OpenMediaVault:** https://docs.openmediavault.org/
- **ZFS Documentation:** https://openzfs.github.io/openzfs-docs/
- **K3s Storage:** https://docs.k3s.io/storage
- **NFS Best Practices:** https://wiki.archlinux.org/title/NFS

### Useful Commands Reference

**ZFS Management:**

```bash
# Pool status and health
sudo zpool status
sudo zpool list
sudo zpool iostat storage 1

# Dataset management
sudo zfs list
sudo zfs get all storage/k3s
sudo zfs set quota=300G storage/k3s

# Snapshots
sudo zfs snapshot storage/k3s@$(date +%Y%m%d)
sudo zfs list -t snapshot
sudo zfs rollback storage/k3s@20260210

# Scrub
sudo zpool scrub storage
sudo zpool status  # Check progress
```

**NFS Management:**

```bash
# View exports
sudo exportfs -v
showmount -e localhost

# Reload exports
sudo exportfs -ra

# Restart NFS
sudo systemctl restart nfs-kernel-server
```

**OMV Management:**

```bash
# Restart OMV services
sudo systemctl restart openmediavault-engined

# Apply configuration
sudo omv-salt deploy run zfs

# First-aid tool
sudo omv-firstaid
```

**Monitoring:**

```bash
# System resources
htop
df -h
du -sh /storage/*

# Network
sudo iftop
ss -tuln | grep :2049  # NFS port

# Logs
sudo journalctl -u nfs-server.service -f
sudo journalctl -u openmediavault-engined -f
```

---

## Notes

### Design Decisions

**Why RAID10 over RAIDZ1:**

- Better random I/O performance (critical for databases)
- Faster rebuild times (30-60 min vs 1-2 hours)
- SSD-optimized (no parity calculations)
- Worth the 50% space efficiency for this use case

**Why nested structure for Immich:**

- Logical grouping of related components
- Easier to promote to a child dataset later for independent snapshots
- Clean separation when adding more services

**Why flat structure for \*arr apps:**

- Simpler K3s configuration (no nested subPaths)
- Each app is independent
- Traditional Kubernetes pattern

**Why PostgreSQL on local storage:**

- PostgreSQL + NFS = unreliable (fsync issues)
- 10-100x performance improvement
- Database is small (~1-5GB for metadata)
- Critical for data integrity

### Known Limitations

**OMV ZFS Plugin:**

- Cannot create RAID10 via UI (must use CLI)
- Cannot modify dataset properties via UI
- Filesystem management UI sometimes broken (use CLI)

**NFSv4:**

- Automatically uses `/export` as pseudo root
- Mount paths don’t include `/export` prefix
- Can be confusing for first-time setup

**Bind Mounts:**

- Required for OMV NFS exports to work with ZFS
- Must be in `/etc/fstab` to survive reboot
- Not obvious in OMV UI that this is needed

### Future Improvements

**Potential upgrades:**

- Add UPS for power protection
- ~~ZFS deduplication~~ — not recommended; the dedup table (DDT) can easily exhaust 16GB RAM and destroy performance. Compression (already enabled) is the practical alternative.
- Setup automated snapshots with sanoid
- Configure ZFS send/receive for offsite backups
- Add more drives for capacity expansion

---

## License

This documentation is provided as-is for personal and educational use.

## Contributing

Found an issue or have an improvement? Please document any changes made to this setup for future reference.

---

**Last Updated:** February 2026  
**Hardware:** Raspberry Pi 5 16GB + Radxa Penta SATA HAT + 4x Crucial BX500 500GB  
**Software:** Raspberry Pi OS (64-bit), OpenMediaVault 7, ZFS on Linux, K3s  
**Configuration:** RAID10, NFS, SMB, optimized for Immich + media server workloads

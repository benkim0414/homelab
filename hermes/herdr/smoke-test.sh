#!/usr/bin/env bash
# Disposable image test. Run with a Docker daemon, never against Kubernetes.
set -euo pipefail
image=${1:?usage: smoke-test.sh IMAGE}
test_dir=$(mktemp -d)
container_name="herdr-smoke-${RANDOM}-$$"
volume_name="${container_name}-data"
access_volume="${container_name}-access"
cleanup() {
  result=$?
  if ((result != 0)); then
    docker logs "$container_name" 2>/dev/null || true
  fi
  docker rm -f "$container_name" >/dev/null 2>&1 || true
  docker volume rm "$volume_name" >/dev/null 2>&1 || true
  docker volume rm "$access_volume" >/dev/null 2>&1 || true
  rm -rf "$test_dir"
}
trap cleanup EXIT
ssh-keygen -q -t ed25519 -N '' -f "$test_dir/client"
cp "$test_dir/client.pub" "$test_dir/authorized_keys"
chmod 0755 "$test_dir"
chmod 0644 "$test_dir/authorized_keys"
docker volume create "$volume_name" >/dev/null
docker volume create "$access_volume" >/dev/null
# Match Kubernetes ConfigMap ownership. A runner-owned bind-mounted key file
# fails OpenSSH StrictModes even when its mode is 0644.
docker run --rm --entrypoint /bin/sh \
  -v "$access_volume:/access" -v "$test_dir/authorized_keys:/incoming:ro" \
  "$image" -c 'cp /incoming /access/authorized_keys; chmod 0644 /access/authorized_keys'
docker run -d --name "$container_name" --read-only --cap-drop ALL \
  --cap-add AUDIT_WRITE --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER --cap-add KILL \
  --cap-add SETGID --cap-add SETUID --cap-add SYS_CHROOT \
  --security-opt no-new-privileges:true \
  --tmpfs /run --tmpfs /tmp \
  -v "$volume_name:/data" \
  -v "$access_volume:/etc/herdr-access:ro" \
  -p 127.0.0.1::2222 "$image" >/dev/null
wait_healthy() {
  for _attempt in $(seq 1 45); do
    if docker exec "$container_name" python3 -B /usr/local/libexec/healthcheck.py >/dev/null 2>&1; then
      return
    fi
    sleep 1
  done
  docker logs "$container_name"
  return 1
}
wait_healthy
port=$(docker port "$container_name" 2222/tcp | cut -d: -f2)
docker exec "$container_name" cat /data/ssh/ssh_host_ed25519_key.pub \
  | sed "s/^/[127.0.0.1]:$port /" > "$test_dir/known_hosts"
ssh_options=(-p "$port" -i "$test_dir/client" -o IdentitiesOnly=yes \
  -o BatchMode=yes -o StrictHostKeyChecking=yes -o UpdateHostKeys=no \
  -o "UserKnownHostsFile=$test_dir/known_hosts")
test "$(ssh "${ssh_options[@]}" herdr@127.0.0.1 id -u)" = 10000
test "$(ssh -tt "${ssh_options[@]}" herdr@127.0.0.1 id -u 2>/dev/null | tr -d '\r')" = 10000
ssh "${ssh_options[@]}" herdr@127.0.0.1 herdr status server
# Closing the SSH connection must not stop the supervised Herdr server.
ssh "${ssh_options[@]}" herdr@127.0.0.1 herdr status server
original_key=$(docker exec "$container_name" cat /data/ssh/ssh_host_ed25519_key.pub)
docker restart "$container_name" >/dev/null
wait_healthy
test "$original_key" = "$(docker exec "$container_name" cat /data/ssh/ssh_host_ed25519_key.pub)"
echo 'Herdr image smoke test passed: nonroot SSH, server persistence, stable host key.'

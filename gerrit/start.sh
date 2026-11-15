#!/bin/bash
set -euo pipefail
umask 077
export GERRIT_TMP=/tmp/gerrit
mkdir -p "$GERRIT_TMP"
site=/site
version=3.14.6
java_options=(-Xms256m -Xmx2g -Duser.home=/site --add-opens=java.base/java.net=ALL-UNNAMED --add-opens=java.base/java.lang.invoke=ALL-UNNAMED)
war=/var/gerrit/bin/gerrit.war

if [[ -f "$site/.homelab-version" ]]; then
  [[ "$(cat "$site/.homelab-version")" == "$version" ]] || {
    printf '%s\n' 'Site version differs; reviewed migration required.' >&2
    exit 1
  }
  [[ -d "$site/git/All-Projects.git" && -d "$site/git/All-Users.git" && -s "$site/.homelab-server-id" ]] || {
    printf '%s\n' 'Initialized site is incomplete; preserve it for recovery.' >&2
    exit 1
  }
else
  # A failed initialization must not be silently retried against partial data.
  if [[ -e "$site/.homelab-initializing" || -e "$site/git/All-Projects.git" ]]; then
    printf '%s\n' 'Unmarked or partial site; manual recovery review required.' >&2
    exit 1
  fi
  shopt -s nullglob dotglob
  for existing in "$site"/*; do
    if [[ "$existing" != "$site/lost+found" || ! -d "$existing" || -L "$existing" ]]; then
      printf '%s\n' 'Unmarked nonempty site; refusing initialization.' >&2
      exit 1
    fi
  done
  shopt -u nullglob dotglob
  touch "$site/.homelab-initializing"
  mkdir -p "$site/etc"
  cp /config/gerrit.config "$site/etc/gerrit.config"
  java "${java_options[@]}" -jar "$war" init --batch --no-auto-start \
    --skip-all-downloads --install-plugin gitiles -d "$site"
  java "${java_options[@]}" -jar "$war" reindex -d "$site"
  git config --file "$site/etc/gerrit.config" --get gerrit.serverId > "$site/.homelab-server-id"
  printf '%s\n' "$version" > "$site/.homelab-version"
  rm "$site/.homelab-initializing"
fi

# Only nonsecret declarative configuration is reconciled. secure.config,
# SSH keys, repositories and plugin state remain on the same retained claim.
cp /config/gerrit.config "$site/etc/gerrit.config.next"
git config --file "$site/etc/gerrit.config.next" gerrit.serverId "$(cat "$site/.homelab-server-id")"
mv "$site/etc/gerrit.config.next" "$site/etc/gerrit.config"
exec java "${java_options[@]}" -jar "$war" daemon -d "$site" --console-log

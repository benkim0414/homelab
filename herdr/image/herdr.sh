#!/bin/sh
set -eu
export XDG_RUNTIME_DIR=/run/herdr
exec /usr/local/libexec/herdr "$@"

#!/usr/bin/python3
"""Open the existing cluster Hermes as its application user, without retries."""
import argparse
import json
import os
import subprocess
import sys

KUBECONFIG = "/etc/herdr-access/kubeconfig"


def select_pod(items):
    candidates = [p for p in items
                  if p.get("metadata", {}).get("labels", {}).get("app") == "hermes"
                  and not p["metadata"].get("deletionTimestamp")
                  and p.get("status", {}).get("phase") == "Running"
                  and any(c.get("type") == "Ready" and c.get("status") == "True"
                          for c in p["status"].get("conditions", []))]
    if len(candidates) != 1:
        raise ValueError(f"Expected one Ready Hermes pod; found {len(candidates)}. Nothing started.")
    return candidates[0]["metadata"]["name"]


def exec_command(pod, session=None):
    command = ["kubectl", "--kubeconfig", KUBECONFIG, "-n", "hermes",
               "exec", "-it", pod, "-c", "hermes", "--",
               "/command/s6-setuidgid", "hermes", "/usr/bin/env",
               "HOME=/opt/data", "HERMES_HOME=/opt/data",
               "/bin/sh", "-c", 'cd /opt/data/workspace && exec hermes "$@"', "hermes"]
    if session is not None:
        command += ["--resume", session]
    return command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", metavar="SESSION_ID")
    args = parser.parse_args()
    if args.resume is not None and (not args.resume or args.resume.startswith("-")
                                    or any(c.isspace() for c in args.resume)):
        parser.error("SESSION_ID must be a nonempty session identifier without whitespace or a leading dash")
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        parser.error("Run this command in an interactive Herdr terminal")
    try:
        result = subprocess.run(["kubectl", "--kubeconfig", KUBECONFIG, "-n", "hermes",
                                 "get", "pods", "-l", "app=hermes", "-o", "json",
                                 "--request-timeout=15s"],
                                check=True, capture_output=True, text=True)
        pod = select_pod(json.loads(result.stdout)["items"])
    except (subprocess.CalledProcessError, ValueError, KeyError) as exc:
        print(f"Cannot open Hermes: {exc}", file=sys.stderr)
        return 1
    print(f"Connecting to {pod} as user hermes. Reconnect explicitly if this connection ends.", flush=True)
    # The hint must be visible on the process outside the target container.
    # Replace this process so Herdr sees the foreground kubectl, without a retry loop.
    os.execvpe("kubectl", exec_command(pod, args.resume), dict(os.environ, HERDR_AGENT="hermes"))


if __name__ == "__main__":
    sys.exit(main())

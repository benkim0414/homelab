#!/usr/bin/python3
"""Open a named conversation on the existing cluster OpenClaw gateway."""
import argparse
import json
import os
import subprocess
import sys

KUBECONFIG = "/etc/herdr-access/kubeconfig"


def select_pod(items):
    candidates = [p for p in items
                  if p.get("metadata", {}).get("labels", {}).get("app") == "openclaw"
                  and not p["metadata"].get("deletionTimestamp")
                  and p.get("status", {}).get("phase") == "Running"
                  and any(c.get("type") == "Ready" and c.get("status") == "True"
                          for c in p["status"].get("conditions", []))]
    if len(candidates) != 1:
        raise ValueError(f"Expected one Ready OpenClaw pod; found {len(candidates)}. Nothing started.")
    return candidates[0]["metadata"]["name"]


def exec_command(pod, session="herdr"):
    return ["kubectl", "--kubeconfig", KUBECONFIG, "-n", "openclaw",
            "exec", "-it", pod, "-c", "gateway", "--",
            "/bin/sh", "-c",
            'cd /home/node/.openclaw/workspace && exec openclaw tui --session "$1"',
            "openclaw", session]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", default="herdr", metavar="NAME",
                        help="conversation name (default: herdr)")
    args = parser.parse_args()
    if (not args.session or args.session.startswith("-")
            or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in args.session)):
        parser.error("NAME must be nonempty, without whitespace, control characters, or a leading dash")
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        parser.error("Run this command in an interactive Herdr terminal")
    try:
        result = subprocess.run(["kubectl", "--kubeconfig", KUBECONFIG, "-n", "openclaw",
                                 "get", "pods", "-l", "app=openclaw", "-o", "json",
                                 "--request-timeout=15s"],
                                check=True, capture_output=True, text=True)
        pod = select_pod(json.loads(result.stdout)["items"])
    except (OSError, subprocess.CalledProcessError, ValueError, KeyError) as exc:
        print(f"Cannot open OpenClaw: {exc}", file=sys.stderr)
        return 1
    print(f"Connecting to {pod}, session {args.session}. Reconnect explicitly if this connection ends.",
          flush=True)
    # OpenClaw is not a supported Herdr detection manifest. Do not inherit a
    # different agent's hint from the launching shell.
    env = dict(os.environ)
    env.pop("HERDR_AGENT", None)
    os.execvpe("kubectl", exec_command(pod, args.session), env)


if __name__ == "__main__":
    sys.exit(main())

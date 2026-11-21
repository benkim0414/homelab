"""Commit only the two tested Herdr image references, without force or credentials.

The main-branch image workflow calls this after publishing its tested artifact.
A newer Herdr tree wins: an older build must never roll it back. Use configured
`gh` authentication; do not read or print tokens or change repository settings.
"""
import argparse
import base64
import json
import re
import subprocess

REPO = "benkim0414/homelab"
IMAGE = "ghcr.io/benkim0414/hermes-herdr"


def api(method, endpoint, payload=None):
    command = ["gh", "api", "--method", method, f"repos/{REPO}/{endpoint}"]
    if payload is not None:
        command += ["--input", "-"]
    result = subprocess.run(command, input=None if payload is None else json.dumps(payload),
                            text=True, capture_output=True)
    if result.returncode:
        # GitHub's response may contain operational details; report only scope/status.
        raise RuntimeError(f"GitHub {method} failed for {endpoint} (exit {result.returncode})")
    return json.loads(result.stdout)


def image_update(source, digest):
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("Invalid image digest")
    pattern = re.compile(r"^(\s+image: )" + re.escape(IMAGE) + r"@(sha256:[0-9a-f]{64})$", re.M)
    matches = list(pattern.finditer(source))
    if len(matches) != 2 or len({match[2] for match in matches}) != 1:
        raise ValueError("Expected exactly two identical pinned Herdr image references")
    return pattern.sub(lambda match: match[1] + IMAGE + "@" + digest, source)


def tree_sha(commit, name):
    entries = api("GET", f"git/trees/{commit['tree']['sha']}")["tree"]
    matches = [entry for entry in entries if entry["path"] == name and entry["type"] == "tree"]
    if len(matches) != 1:
        raise ValueError("Missing source tree")
    return matches[0]["sha"]


def publish(source_sha, digest, run_url):
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise ValueError("Invalid tested source SHA")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("Invalid image digest")
    if not re.fullmatch(r"https://github\.com/benkim0414/homelab/actions/runs/[0-9]+", run_url):
        raise ValueError("Invalid workflow evidence URL")
    reference = api("GET", "git/ref/heads/main")
    base_sha = reference["object"]["sha"]
    base = api("GET", f"git/commits/{base_sha}")
    tested = api("GET", f"git/commits/{source_sha}")
    if tree_sha(base, "herdr") != tree_sha(tested, "herdr"):
        print("Skipped stale build: main already has a newer Herdr tree")
        return None
    original = api("GET", f"contents/herdr/deployment.yaml?ref={base_sha}")
    content = base64.b64decode(original["content"]).decode()
    updated = image_update(content, digest)
    if updated == content:
        print("Tested image is already declared")
        return None
    blob = api("POST", "git/blobs", {"content": updated, "encoding": "utf-8"})
    tree = api("POST", "git/trees", {"base_tree": base["tree"]["sha"], "tree": [
        {"path": "herdr/deployment.yaml", "mode": "100644", "type": "blob", "sha": blob["sha"]}]})
    commit = api("POST", "git/commits", {
        "message": f"chore(herdr): deploy tested image\n\nSource: {source_sha}\nImage: {IMAGE}@{digest}\nCI: {run_url}",
        "tree": tree["sha"], "parents": [base_sha]})
    # A concurrent commit makes this fail; never force, rebase, or silently retry.
    api("PATCH", "git/refs/heads/main", {"sha": commit["sha"], "force": False})
    actual = api("GET", "git/ref/heads/main")["object"]["sha"]
    readback = api("GET", f"contents/herdr/deployment.yaml?ref={commit['sha']}")
    if actual != commit["sha"] or base64.b64decode(readback["content"]).decode() != updated:
        raise RuntimeError("Generated deployment commit readback did not match")
    print(f"Published tested deployment commit {commit['sha']}")
    return commit["sha"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--run-url", required=True)
    args = parser.parse_args()
    publish(args.source_sha, args.digest, args.run_url)

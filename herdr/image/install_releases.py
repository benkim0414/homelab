"""Install only checksum-pinned upstream binaries while building the image."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile

ARCHES = {"amd64": "x86_64", "arm64": "aarch64"}
COMPONENTS = ("herdr", "herdr-core")
MAX_BINARY = 256 * 1024 * 1024


def load_pins(path):
    pins = json.loads(Path(path).read_text())
    expected = {f"{name}-{arch}" for name in COMPONENTS for arch in ARCHES}
    if not isinstance(pins, dict) or set(pins) != expected:
        raise ValueError("Release pins must contain exactly both components and architectures")
    for pin in pins.values():
        if not isinstance(pin, dict) or set(pin) != {"version", "digest"}:
            raise ValueError("Invalid release pin fields")
        if not isinstance(pin["version"], str) or not re.fullmatch(
                r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", pin["version"]):
            raise ValueError("Release version must be stable numeric semver")
        if not isinstance(pin["digest"], str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", pin["digest"]):
            raise ValueError("Release digest must be SHA256")
    for name in COMPONENTS:
        if len({pins[f"{name}-{arch}"]["version"] for arch in ARCHES}) != 1:
            raise ValueError("Architectures must advance together")
    return pins


def download(url, destination):
    subprocess.run(["curl", "--proto", "=https", "--proto-redir", "=https", "-fsSL",
                    "--retry", "2", "--connect-timeout", "10", "--max-time", "180",
                    "--max-filesize", str(MAX_BINARY), url, "-o", str(destination)], check=True)


def verify(path, digest):
    if path.stat().st_size > MAX_BINARY:
        raise ValueError("Release exceeds size limit")
    with path.open("rb") as stream:
        actual = "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != digest:
        raise ValueError("Upstream release checksum mismatch")


def extract_core(archive, destination):
    # Retain required notices, but never extract paths, links or devices.
    with tarfile.open(archive, "r:gz") as source:
        members = source.getmembers()
        names = [member.name for member in members]
        allowed = {"herdr-core", "LICENSE", "THIRD-PARTY-NOTICES"}
        if set(names) != allowed or len(names) != len(allowed):
            raise ValueError("Unexpected Core archive members")
        for member in members:
            if not member.isreg() or not 0 < member.size <= MAX_BINARY:
                raise ValueError("Invalid Core archive member")
            incoming = source.extractfile(member)
            if incoming is None:
                raise ValueError("Core archive member is unreadable")
            output = destination if member.name == "herdr-core" else destination.with_name(
                "herdr-core." + member.name)
            with incoming, output.open("wb") as outgoing:
                shutil.copyfileobj(incoming, outgoing)


def install(pins_path, arch, destination):
    pins = load_pins(pins_path)
    target = ARCHES[arch]
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        cache = Path(directory)
        legacy = pins[f"herdr-{arch}"]
        binary = cache / "herdr"
        url = ("https://github.com/herdrdev/herdr/releases/download/"
               f"v{legacy['version']}/herdr-linux-{target}")
        try:
            download(url, binary)
        except subprocess.CalledProcessError:
            # GitHub's public asset endpoint is a fallback, never an unpinned release.
            metadata = cache / "release.json"
            download("https://api.github.com/repos/herdrdev/herdr/releases/tags/"
                     f"v{legacy['version']}", metadata)
            release = json.loads(metadata.read_text())
            if release.get("tag_name") != f"v{legacy['version']}":
                raise ValueError("Unexpected GitHub release tag")
            assets = [asset for asset in release["assets"]
                      if asset["name"] == f"herdr-linux-{target}"]
            if len(assets) != 1 or not isinstance(assets[0]["id"], int):
                raise ValueError("Ambiguous GitHub release asset")
            subprocess.run(["curl", "--proto", "=https", "--proto-redir", "=https", "-fsSL",
                            "--retry", "2", "--connect-timeout", "10", "--max-time", "180",
                            "--max-filesize", str(MAX_BINARY), "-H", "Accept: application/octet-stream",
                            "https://api.github.com/repos/herdrdev/herdr/releases/assets/"
                            f"{assets[0]['id']}", "-o", str(binary)], check=True)
        verify(binary, legacy["digest"])
        core = pins[f"herdr-core-{arch}"]
        archive = cache / "core.tar.gz"
        download(f"https://releases.herdr.dev/core/{core['version']}/"
                 f"herdr-core-linux-{target}.tar.gz", archive)
        verify(archive, core["digest"])
        core_binary = cache / "herdr-core"
        extract_core(archive, core_binary)
        for name in COMPONENTS:
            shutil.copyfile(cache / name, destination / name)
            (destination / name).chmod(0o755)
        for name in ("LICENSE", "THIRD-PARTY-NOTICES"):
            shutil.copyfile(cache / f"herdr-core.{name}", destination / f"herdr-core.{name}")
            (destination / f"herdr-core.{name}").chmod(0o644)
    print(f"Installed pinned Herdr {legacy['version']} and Core {core['version']} ({arch})")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pins", type=Path, required=True)
    parser.add_argument("--arch", choices=ARCHES, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    install(args.pins, args.arch, args.destination)


if __name__ == "__main__":
    main()

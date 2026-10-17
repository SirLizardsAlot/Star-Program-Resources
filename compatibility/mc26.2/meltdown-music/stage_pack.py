"""Stage checked v25 in the existing resource-pack publication checkout."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

from build_pack import validate

ROOT = Path(__file__).resolve().parent
PACK_ROOT, REPO = ROOT.parent, ROOT.parent / "repository"
PREFIX = "compatibility/mc26.2/"
EXPECTED_PARENT = "4f4f7fdc2c36606063478fdcb6249ccd6c178e5b"


def git(*args):
    return subprocess.check_output(["git", "-c", "safe.directory=" + REPO.as_posix(), "-C", str(REPO), *args], text=True).strip()


def main():
    if git("status", "--porcelain") or git("rev-parse", "HEAD") != EXPECTED_PARENT:
        raise ValueError("Preserve publication checkout changes before staging.")
    if git("remote", "get-url", "origin") != "https://github.com/SirLizardsAlot/Star-Program-Resources.git":
        raise ValueError("Unexpected publication destination.")
    report = validate()
    report_data = (PACK_ROOT / "build-report-v25.json").read_bytes()
    if json.loads(report_data) != report:
        raise ValueError("Rebuild the validated v25 report before staging.")
    data = (PACK_ROOT / report["output"]).read_bytes()
    payload = {report["output"]: data, PREFIX + "build-report-v25.json": report_data}
    for path in ROOT.rglob("*"):
        if path.is_file() and not any(part in {"__pycache__", "previews", "analysis"} for part in path.relative_to(ROOT).parts):
            payload[PREFIX + "meltdown-music/" + path.relative_to(ROOT).as_posix()] = path.read_bytes()
    previous = (REPO / PREFIX / "README.md").read_text(encoding="utf-8")
    intro = ("# STAR PROGRAM resource pack v25\n\n"
             "Replaces the complete meltdown song with its approved intro, repeatable middle, and ending sections. "
             "The first boundary is 67.5 seconds; middle phrases repeat every 15 seconds with 60 ms overlap. "
             "The ending lasts 62 seconds after removing only 4.5256875 seconds of digital silence. "
             "Ogg packets are copied without re-encoding; every retained decoded PCM sample matches the approved splice.\n\n"
             "Only the old song asset and its registration change from v24. All unrelated assets and every alarm "
             "recording remain byte-identical. The old event is an alias to the new intro. Previous packs remain available. "
             f"ZIP size: {len(data):,} bytes, below DiamondFire's 40 MiB limit.\n\n"
             "## Previous compatibility notes\n\n")
    payload[PREFIX + "README.md"] = (intro + previous).encode()
    for relative, contents in payload.items():
        path = REPO / relative
        if path.exists() and relative != PREFIX + "README.md":
            raise ValueError("Refusing to overwrite an existing publication file: " + relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
    print(json.dumps({"files": len(payload), "parent": EXPECTED_PARENT,
                      "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}))


if __name__ == "__main__":
    main()

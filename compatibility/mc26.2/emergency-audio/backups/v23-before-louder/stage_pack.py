"""Stage v23 in the existing resource publication checkout without overwrites."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent
PACK_ROOT, REPO = ROOT.parent, ROOT.parent / "repository"
PREFIX = "compatibility/mc26.2/"
EXPECTED_PARENT = "ff9cce4760d46285fcc0ab1bc2eb16b438ee132b"


def git(*args):
    return subprocess.check_output(["git", "-c", "safe.directory=" + REPO.as_posix(), "-C", str(REPO), *args], text=True).strip()


def main():
    if git("status", "--porcelain") or git("rev-parse", "HEAD") != EXPECTED_PARENT:
        raise ValueError("Preserve publication checkout changes before staging.")
    report = json.loads((PACK_ROOT / "build-report-v23.json").read_text(encoding="utf-8"))
    data = (PACK_ROOT / report["output"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != report["sha256"] or len(data) > 40 * 1024 * 1024:
        raise ValueError("Validated archive hash or size mismatch.")
    payload = {report["output"]: data, PREFIX + "build-report-v23.json": (PACK_ROOT / "build-report-v23.json").read_bytes()}
    for path in ROOT.rglob("*"):
        if path.is_file() and not any(part in {"__pycache__", "previews"} for part in path.relative_to(ROOT).parts):
            payload[PREFIX + "emergency-audio/" + path.relative_to(ROOT).as_posix()] = path.read_bytes()
    previous = (REPO / PREFIX / "README.md").read_text(encoding="utf-8")
    intro = ("# STAR PROGRAM resource pack v23\n\n"
             "Adds the selected Poligonstudio single siren sweep and a complete Matthew Code Black evacuation announcement. "
             "The siren is 13.4 seconds (268 ticks); runtime repeats it. The PA lasts 307 ticks including its room tail.\n\n"
             "This archive uses published v21 as its base, preserving the restored original core recordings and every "
             "other existing asset byte-for-byte. It adds only two mono emergency audio files, event routing, and credits. "
             f"ZIP size: {len(data):,} bytes, below DiamondFire's 40 MiB limit.\n\n"
             "## Previous compatibility notes\n\n")
    payload[PREFIX + "README.md"] = (intro + previous).encode()
    for relative, contents in payload.items():
        path = REPO / relative
        if path.exists() and relative not in {PREFIX + "README.md"}:
            raise ValueError("Refusing to overwrite existing publication file: " + relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
    print(json.dumps({"files": len(payload), "parent": EXPECTED_PARENT, "size": len(data), "sha256": report["sha256"]}))


if __name__ == "__main__":
    main()

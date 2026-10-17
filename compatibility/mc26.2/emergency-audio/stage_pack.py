"""Stage v24 in the existing guarded resource publication checkout."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent
PACK_ROOT, REPO = ROOT.parent, ROOT.parent / "repository"
PREFIX = "compatibility/mc26.2/"
EXPECTED_PARENT = "4a3507a83ac299c213be0a306f9cc4a61980d16f"


def git(*args):
    return subprocess.check_output(["git", "-c", "safe.directory=" + REPO.as_posix(), "-C", str(REPO), *args], text=True).strip()


def main():
    if git("status", "--porcelain") or git("rev-parse", "HEAD") != EXPECTED_PARENT:
        raise ValueError("Preserve publication checkout changes before staging.")
    report = json.loads((PACK_ROOT / "build-report-v24.json").read_text(encoding="utf-8"))
    data = (PACK_ROOT / report["output"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != report["sha256"] or len(data) > 40 * 1024 * 1024:
        raise ValueError("Validated archive hash or size mismatch.")
    payload = {report["output"]: data, PREFIX + "build-report-v24.json": (PACK_ROOT / "build-report-v24.json").read_bytes()}
    for path in ROOT.rglob("*"):
        if path.is_file() and not any(part in {"__pycache__", "previews"} for part in path.relative_to(ROOT).parts):
            payload[PREFIX + "emergency-audio/" + path.relative_to(ROOT).as_posix()] = path.read_bytes()
    previous = (REPO / PREFIX / "README.md").read_text(encoding="utf-8")
    intro = ("# STAR PROGRAM resource pack v24\n\n"
             "Raises the Code Black siren by 7.10 dB measured PCM RMS and the Matthew announcement by 3.79 dB. "
             "Smooth anticipatory peak control avoids waveform clipping; decoded peaks remain below 0.95. "
             "The siren stays 13.4 seconds (268 ticks); PA stays 307 ticks including its tail.\n\n"
             "Only the two emergency Ogg files and their credits differ from v23. All other assets, including the "
             "restored original core recordings, remain byte-identical. Previous assets and build scripts are backed up. "
             f"ZIP size: {len(data):,} bytes, below DiamondFire's 40 MiB limit.\n\n"
             "## Previous compatibility notes\n\n")
    payload[PREFIX + "README.md"] = (intro + previous).encode()
    for relative, contents in payload.items():
        path = REPO / relative
        if path.exists() and relative not in {PREFIX + "README.md"} and not relative.startswith(PREFIX + "emergency-audio/"):
            raise ValueError("Refusing to overwrite existing publication file: " + relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
    print(json.dumps({"files": len(payload), "parent": EXPECTED_PARENT, "size": len(data), "sha256": report["sha256"]}))


if __name__ == "__main__":
    main()

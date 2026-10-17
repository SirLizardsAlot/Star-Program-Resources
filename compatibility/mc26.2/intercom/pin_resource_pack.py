"""Verify the published immutable pack before pinning the STAR game to it."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import urllib.request

ROOT = Path(__file__).resolve().parent.parent


def main(commit, version=18):
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("Expected a full publication commit")
    report = json.loads((ROOT / f"build-report-v{version}.json").read_text())
    config_path = ROOT.parent / "config/resource-pack.json"
    original = config_path.read_bytes()
    config = json.loads(original)
    if config["sha256"] != report["previousPack"]["sha256"]:
        raise ValueError("Resource-pack configuration changed since the validated build")
    local = (ROOT / report["output"]).read_bytes()
    if hashlib.sha256(local).hexdigest() != report["sha256"]:
        raise ValueError("Local pack differs from the validated artifact")
    repository = config["source"]["repository"]
    if repository != "SirLizardsAlot/Star-Program-Resources":
        raise ValueError("Unexpected resource-pack publication repository")
    url = f"https://raw.githubusercontent.com/{repository}/{commit}/{report['output']}"
    request = urllib.request.Request(url, headers={"User-Agent": "STAR-Program-pack-verification"})
    with urllib.request.urlopen(request, timeout=30) as response:
        remote = response.read()
        status = response.status
    if remote != local or hashlib.sha256(remote).hexdigest() != report["sha256"]:
        raise ValueError("Published pack bytes differ from the approved local artifact")
    if len(remote) > 40 * 1024 * 1024:
        raise ValueError("Published pack exceeds 40 MiB")
    destination = ROOT / f"validation/public-v{version}.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(remote)
    backup = config_path.parent / "backups" / f"resource-pack-before-v{version}-{config['sha256'][:12]}.json"
    if backup.exists() and backup.read_bytes() != original:
        raise ValueError("Refusing to overwrite a different resource-pack backup")
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_bytes(original)
    verified = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    blob = hashlib.sha1(b"blob " + str(len(remote)).encode() + b"\0" + remote).hexdigest()
    previous_urls = config.setdefault("previousUrls", [])
    if config["url"] not in previous_urls:
        previous_urls.append(config["url"])
    config.update({"url": url, "sha1": report["sha1"], "sha256": report["sha256"],
                   "size": len(remote), "sizeLimitBytes": 40 * 1024 * 1024,
                   "elevatorChime": report["elevatorChime"], "elevatorDoors": report["elevatorDoors"]})
    if "turbines" in report:
        config["turbines"] = report["turbines"]
    if "coreAudio" in report:
        config["coreAudio"] = report["coreAudio"]
    config["publication"].update({"status": "published", "commit": commit,
        "gitBlob": blob, "verifiedBlob": blob, "verifiedAt": verified})
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    publication = {"version": 1, "status": "published", "commit": commit,
        "branch": config["publication"]["branch"], "url": url, "httpStatus": status,
        "verifiedAt": verified, "size": len(remote), "sha1": report["sha1"],
        "sha256": report["sha256"], "gitBlob": blob, "matchesApprovedLocalArtifact": True,
        "elevatorChime": report["elevatorChime"], "elevatorDoors": report["elevatorDoors"]}
    if "turbines" in report:
        publication["turbines"] = report["turbines"]
    if "coreAudio" in report:
        publication["coreAudio"] = report["coreAudio"]
    (ROOT / f"upload-report-v{version}.json").write_text(json.dumps(publication, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"url": url, "verifiedBytes": len(remote), "sha256": report["sha256"],
                      "configUpdated": True, "backup": str(backup)}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("commit")
    parser.add_argument("--version", type=int, default=18)
    args = parser.parse_args()
    main(args.commit, args.version)

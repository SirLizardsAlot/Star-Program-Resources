"""Verify v23's immutable published bytes, preserve config backup, then pin it."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import urllib.request

ROOT = Path(__file__).resolve().parent.parent


def main(commit):
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("Expected an immutable full publication commit.")
    report = json.loads((ROOT / "build-report-v23.json").read_text(encoding="utf-8"))
    config_path = ROOT.parent / "config/resource-pack.json"
    original = config_path.read_bytes()
    config = json.loads(original)
    if config["sha256"] != report["previousPack"]["sha256"] or config.get("coreAudio"):
        raise ValueError("Active original-core pack pin changed; preserve and review it.")
    repository = config["source"]["repository"]
    if repository != "SirLizardsAlot/Star-Program-Resources":
        raise ValueError("Unexpected publication destination.")
    local = (ROOT / report["output"]).read_bytes()
    url = f"https://raw.githubusercontent.com/{repository}/{commit}/{report['output']}"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "STAR-Program-pack-verification"}), timeout=45) as response:
        remote, status = response.read(), response.status
    if (local != remote or hashlib.sha256(remote).hexdigest() != report["sha256"]
            or hashlib.sha1(remote).hexdigest() != report["sha1"] or len(remote) > 40 * 1024 * 1024):
        raise ValueError("Published archive does not match the validated local pack.")
    backup = config_path.parent / "backups" / f"resource-pack-before-v23-{config['sha256'][:12]}.json"
    if backup.exists() and backup.read_bytes() != original:
        raise ValueError("Preserve the different existing backup.")
    backup.write_bytes(original)
    verified = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    config["previousUrls"] = list(dict.fromkeys([*config.get("previousUrls", []), config["url"]]))
    config.update({"url": url, "sha1": report["sha1"], "sha256": report["sha256"], "size": len(remote),
                   "sizeLimitBytes": report["sizeLimitBytes"], "emergencyAudio": report["emergencyAudio"]})
    config["publication"].update({"status": "published", "commit": commit, "gitBlob": report["gitBlob"],
                                   "verifiedBlob": report["gitBlob"], "verifiedAt": verified})
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    publication = {"version": 1, "status": "published", "commit": commit, "branch": config["publication"]["branch"],
                   "url": url, "httpStatus": status, "verifiedAt": verified, "size": len(remote),
                   "sha1": report["sha1"], "sha256": report["sha256"], "gitBlob": report["gitBlob"],
                   "matchesApprovedLocalArtifact": True, "originalCoreRecordingsPreserved": True,
                   "emergencyAudio": report["emergencyAudio"]}
    (ROOT / "upload-report-v23.json").write_text(json.dumps(publication, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"url": url, "verifiedBytes": len(remote), "sha256": report["sha256"], "configUpdated": True,
                      "backup": str(backup)}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("commit")
    main(parser.parse_args().commit)

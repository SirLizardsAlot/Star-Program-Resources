"""Extract an official eSpeak NG MSI locally; does not run an installer."""
from pathlib import Path
import ctypes
import hashlib
import subprocess

ROOT = Path(__file__).resolve().parent
TOOLS = ROOT / "vendor"
MSI = TOOLS / "espeak-ng-1.52.0.msi"
OUT = TOOLS / "espeak-ng"


def extract():
    expected = "7f673c709ea5dd579d3b5ebb98688cc575328a6ab7438d2bc405b88cedaeafb9"
    if hashlib.sha256(MSI.read_bytes()).hexdigest() != expected:
        raise ValueError("MSI is not the verified official eSpeak NG 1.52.0 download")
    if (OUT / "libespeak-ng.dll").exists():
        print(f"Reusing the extracted eSpeak NG library in {OUT}")
        return
    msi = ctypes.WinDLL("msi")
    handle = ctypes.c_uint()
    check = lambda code: None if code == 0 else (_ for _ in ()).throw(OSError(code))
    check(msi.MsiOpenDatabaseW(str(MSI), None, ctypes.byref(handle)))
    view = ctypes.c_uint()
    check(msi.MsiDatabaseOpenViewW(handle, "SELECT `Data` FROM `_Streams` WHERE `Name`='cab1.cab'", ctypes.byref(view)))
    check(msi.MsiViewExecute(view, 0))
    record = ctypes.c_uint()
    check(msi.MsiViewFetch(view, ctypes.byref(record)))
    cab = TOOLS / "espeak-ng.cab"
    with cab.open("wb") as output:
        while True:
            buffer = ctypes.create_string_buffer(65536)
            length = ctypes.c_uint(len(buffer))
            check(msi.MsiRecordReadStream(record, 1, buffer, ctypes.byref(length)))
            if not length.value:
                break
            output.write(buffer.raw[:length.value])
    msi.MsiCloseHandle(record)
    msi.MsiCloseHandle(view)
    OUT.mkdir(exist_ok=True)
    subprocess.run(["expand.exe", "-F:*", str(cab), str(OUT)], check=True, capture_output=True)
    def query(sql, count):
        check(msi.MsiDatabaseOpenViewW(handle, sql, ctypes.byref(view)))
        check(msi.MsiViewExecute(view, 0))
        rows = []
        while msi.MsiViewFetch(view, ctypes.byref(record)) == 0:
            values = []
            for field in range(1, count + 1):
                buffer = ctypes.create_unicode_buffer(4096)
                length = ctypes.c_uint(len(buffer))
                check(msi.MsiRecordGetStringW(record, field, buffer, ctypes.byref(length)))
                values.append(buffer.value)
            rows.append(values)
            msi.MsiCloseHandle(record)
        msi.MsiCloseHandle(view)
        return rows

    # WiX stores File IDs in its cabinet. Recover paths from MSI metadata.
    files = query("SELECT `File`,`FileName`,`Component_` FROM `File`", 3)
    components = dict(query("SELECT `Component`,`Directory_` FROM `Component`", 2))
    directories = {name: (parent, leaf.split('|')[-1].split(':')[0]) for name, parent, leaf in query("SELECT `Directory`,`Directory_Parent`,`DefaultDir` FROM `Directory`", 3)}

    def relative(directory):
        if directory in ("TARGETDIR", "ProgramFilesFolder", "ProgramFiles64Folder", "INSTALLDIR"):
            return Path()
        parent, leaf = directories[directory]
        return relative(parent) / (leaf if leaf != "." else "")

    moves = []
    for file_id, filename, component in files:
        source = OUT / file_id
        dest = OUT / relative(components[component]) / filename.split('|')[-1].strip()
        moves.append((source, dest))
    # Move via temporary names to avoid collisions with folder/file names.
    for index, (source, dest) in enumerate(moves):
        source.rename(OUT / f"extract-{index}.tmp")
    for index, (source, dest) in enumerate(moves):
        dest.parent.mkdir(parents=True, exist_ok=True)
        (OUT / f"extract-{index}.tmp").rename(dest)
    msi.MsiCloseHandle(handle)
    import json
    (TOOLS / "msi-files.json").write_text(json.dumps(files, indent=2) + "\n")
    print(f"Extracted {len(files)} files into {OUT}")


if __name__ == "__main__":
    extract()

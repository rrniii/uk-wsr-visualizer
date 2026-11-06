"""Check the minimum OS required by every native binary in a Mac bundle."""

import argparse
import json
from pathlib import Path
import re
import subprocess


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--minimum", default="13.0")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    binaries = []
    for path in args.bundle.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        with path.open("rb") as handle:
            if handle.read(4) in (b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"):
                binaries.append(str(path))
    if not binaries:
        raise SystemExit("No native binaries found")
    output = subprocess.check_output(["otool", "-l", *binaries], text=True)
    current, records, legacy = "", [], False
    for line in output.splitlines():
        if line and not line[0].isspace() and line.endswith(":"):
            current = line[:-1]
        if line.strip().startswith("cmd "):
            legacy = line.strip() == "cmd LC_VERSION_MIN_MACOSX"
        match = re.match(r"\s+" + ("version" if legacy else "minos") + r" ([\d.]+)$", line)
        if match:
            records.append({"path": current, "minimum_macos": match.group(1)})
    def version(value):
        return tuple((list(map(int, value.split("."))) + [0, 0])[:3])
    incompatible = [record for record in records if version(record["minimum_macos"]) > version(args.minimum)]
    args.report.write_text(json.dumps({"checked_binaries": len(binaries), "minimum_macos": args.minimum, "incompatible": incompatible, "binaries": records}, indent=2) + "\n")
    if incompatible:
        raise SystemExit(f"{len(incompatible)} binaries require newer than macOS {args.minimum}; see {args.report}")
    print(f"Checked {len(binaries)} native binaries against macOS {args.minimum}")


if __name__ == "__main__":
    main()

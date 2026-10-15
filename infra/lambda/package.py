"""Zip src/<name>/*.py into build/<name>.zip (deterministic timestamps). Usage: python infra/lambda/package.py signals api"""
import pathlib
import sys
import zipfile

root = pathlib.Path(__file__).resolve().parents[2]
for name in sys.argv[1:]:
    out = root / "build" / f"{name}.zip"
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted((root / "src" / name).glob("*.py")):
            info = zipfile.ZipInfo(f.name, date_time=(2026, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, f.read_bytes())
    print(out, [n for n in zipfile.ZipFile(out).namelist()])

"""Build the small BP/RP bundle into package assets using only the standard library."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
assets = ROOT / "src/endstone_entity_displays/assets"
assets.mkdir(parents=True, exist_ok=True)
archive_path = assets / "display_packs.zip"
count = 0
with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    for directory in ("behavior_pack", "resource_pack"):
        for path in sorted((ROOT / directory).rglob("*.json")):
            data = path.read_bytes()
            json.loads(data)
            entry = zipfile.ZipInfo(path.relative_to(ROOT).as_posix(), date_time=(2026, 10, 19, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, data)
            count += 1
index = {"version": [0, 2, 1], "sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest()}
(assets / "pack_index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
print(f"Bundled {count} pack JSON files ({archive_path.stat().st_size:,} bytes); no scripts or custom textures.")

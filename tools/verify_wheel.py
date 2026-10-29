"""Verify a release and install/import it in an isolated disposable fixture.

Python 3.11+; Endstone must be available to the verification interpreter.
Does not install into the server, start a server or change world/pack lists.
"""
import argparse
import ast
import base64
import configparser
import csv
from email.parser import BytesParser
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "endstone_entity_displays"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify(path):
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version = project["version"]
    distribution = PACKAGE + "-" + version + ".dist-info/"
    expected_name = PACKAGE + "-" + version + "-py3-none-any.whl"
    require(path.name == expected_name, f"Expected release filename {expected_name}")
    require(path.stat().st_size < 10 * 1024 * 1024, "Unexpectedly large wheel")
    source = ROOT / "src" / PACKAGE
    disk_files = {PACKAGE + "/" + p.relative_to(source).as_posix(): p for p in source.rglob("*.py")}
    disk_files.update({PACKAGE + "/assets/" + name: source / "assets" / name
                       for name in ("display_packs.zip", "pack_index.json")})
    disk_files[PACKAGE + "/docs/README.md"] = ROOT / "README.md"
    expected = set(disk_files) | {distribution + name for name in ("METADATA", "WHEEL", "entry_points.txt", "RECORD")}
    with zipfile.ZipFile(path) as wheel:
        names = wheel.namelist()
        require(len(names) == len(set(names)) and set(names) == expected,
                f"Wheel has unexpected/missing/duplicate members: {set(names) ^ expected}")
        for name in names:
            relative = PurePosixPath(name)
            require(not relative.is_absolute() and ".." not in relative.parts and "\\" not in name and ":" not in name,
                    "Unsafe wheel member path")
        require(wheel.testzip() is None, "Wheel CRC check failed")
        files = {name: wheel.read(name) for name in names}
    for name, disk in disk_files.items():
        require(files[name] == disk.read_bytes(), "Release does not match source: " + name)
        if name.endswith(".py"):
            ast.parse(files[name], filename=name)
    rows = list(csv.reader(io.StringIO(files[distribution + "RECORD"].decode("utf-8"))))
    require(len(rows) == len(names) and {r[0] for r in rows} == set(names), "Incomplete/duplicate wheel RECORD")
    for name, digest, size in rows:
        if name == distribution + "RECORD":
            require(digest == size == "", "RECORD must not hash itself")
            continue
        actual = base64.urlsafe_b64encode(hashlib.sha256(files[name]).digest()).rstrip(b"=").decode("ascii")
        require(digest == "sha256=" + actual and size == str(len(files[name])), "Wrong RECORD hash/size: " + name)
    metadata = BytesParser().parsebytes(files[distribution + "METADATA"])
    require(metadata["Name"] == project["name"] and metadata["Version"] == version, "Wrong project metadata")
    require(metadata["Requires-Python"] == project["requires-python"], "Wrong Python requirement")
    require(not metadata.get_all("Requires-Dist"), "Unexpected runtime dependencies")
    require(metadata["Description-Content-Type"] == "text/markdown", "README metadata missing")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    require(metadata.get_payload(decode=True).decode("utf-8").strip() == readme.strip(), "README metadata differs from source")
    for index, snippet in enumerate(re.findall(r"^```python\n(.*?)^```", readme, re.MULTILINE | re.DOTALL)):
        ast.parse(snippet, filename=f"README Python example {index + 1}")
    for snippet in re.findall(r"^```json\n(.*?)^```", readme, re.MULTILINE | re.DOTALL):
        json.loads(snippet)
    headings = {re.sub(r"[^a-z0-9 -]", "", heading.lower()).replace(" ", "-")
                for heading in re.findall(r"^#{1,6} (.+)$", readme, re.MULTILINE)}
    require(all(anchor in headings for anchor in re.findall(r"\]\(#([a-z0-9-]+)\)", readme)), "Broken README contents link")
    entry = configparser.ConfigParser()
    entry.read_string(files[distribution + "entry_points.txt"].decode("utf-8"))
    require(dict(entry["endstone"]) == {"entity_displays": PACKAGE + ":EntityDisplaysPlugin"}, "Wrong Endstone entry point")
    wheel_metadata = BytesParser().parsebytes(files[distribution + "WHEEL"])
    require(wheel_metadata["Root-Is-Purelib"] == "true" and wheel_metadata.get_all("Tag") == ["py3-none-any"],
            "Unexpected wheel platform/tag")
    bundle = files[PACKAGE + "/assets/display_packs.zip"]
    index = json.loads(files[PACKAGE + "/assets/pack_index.json"])
    require(index["sha256"] == hashlib.sha256(bundle).hexdigest(), "Pack checksum mismatch")
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        require(archive.testzip() is None, "Pack CRC failure")
        for info in archive.infolist():
            require(archive.read(info.filename) == (ROOT / info.filename).read_bytes(), "Stale bundled pack source")
        for prefix in ("behavior_pack", "resource_pack"):
            manifest = json.loads(archive.read(prefix + "/manifest.json"))
            require(manifest["header"]["version"] == index["version"], "Pack version mismatch")
    print(f"Archive verified: {len(names)} wheel members, complete RECORD, embedded packs and README.", flush=True)
    with tempfile.TemporaryDirectory(prefix="wheel-check-", dir=ROOT / "tests") as directory:
        target = Path(directory) / "installed"
        subprocess.run([sys.executable, "-B", "-m", "pip", "install", "--no-index", "--no-deps", "--no-compile",
                        "--no-cache-dir", "--disable-pip-version-check", "--target", str(target), str(path.resolve())], check=True)
        probe = r"""
import importlib.metadata as metadata
from importlib.resources import files
from pathlib import Path
import sys
target = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(target))
dist = metadata.distribution('endstone-entity-displays')
assert dist.version == sys.argv[2] and Path(dist.locate_file('')).resolve() == target
points = list(dist.entry_points)
assert len(points) == 1 and points[0].group == 'endstone' and points[0].name == 'entity_displays'
from endstone.plugin import Plugin
from endstone.plugin.plugin_loader import _build_commands, _build_permissions
cls = points[0].load()
assert issubclass(cls, Plugin) and cls.api_version == '0.11'
assert _build_commands(cls.commands)[0].name == 'ed'
assert len(_build_permissions({k: dict(v) for k, v in cls.permissions.items()})) == 1
import endstone_entity_displays as package
assert Path(package.__file__).resolve().is_relative_to(target)
from endstone_entity_displays.packs import bundled_files, VERSION, install_packs, PACKS
from endstone_entity_displays.catalog import load_catalog, load_models
assert VERSION == [0, 2, 1] and len(bundled_files()) == 18
assert len(load_catalog()) == 1348 and len(load_models()) == 34
assert files(package).joinpath('docs/README.md').read_text(encoding='utf-8').startswith('# Entity Displays')
fixture_server = target.parent / 'server'
fixture_server.mkdir()
(fixture_server / 'server.properties').write_text('level-name=WheelFixture\n', encoding='utf-8')
assert install_packs(fixture_server) == 'installed/updated'
assert install_packs(fixture_server) == 'unchanged'
import json
for _, (pack_id, relative, world_file, _) in PACKS.items():
    assert (fixture_server / relative / 'manifest.json').is_file()
    assert json.loads((fixture_server / 'worlds/WheelFixture' / world_file).read_text()) == [{'pack_id': pack_id, 'version': VERSION}]
print('Isolated wheel import, entry point, native APIs, catalogs and BP/RP auto-install/idempotency verified.')
"""
        subprocess.run([sys.executable, "-B", "-I", "-c", probe, str(target), version], check=True)
    print("SHA256 " + hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path, nargs="?", default=ROOT / "dist/endstone_entity_displays-0.2.2-py3-none-any.whl")
    verify(parser.parse_args().wheel)

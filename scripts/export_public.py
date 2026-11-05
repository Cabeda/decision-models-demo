"""Export reviewed source files without private data, local state or Git history.

Usage: python3 scripts/export_public.py /tmp/decision-models-public
The destination must not exist. Review the export before publishing it.
"""

from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
DIRECTORIES = {"act1_primitives", "act2_weather", "act3_nhtsa", "act4_support", "dm", "fixtures", "scripts", "tests", ".github"}
FILES = {".gitignore", ".gitleaks.toml", ".python-version", "README.md", "GLOSSARY.md", "PRESENTER_GUIDE.md", "SECURITY.md", "PUBLICATION_REVIEW.md", "pyproject.toml", "uv.lock"}
EXCLUDED = {"act3_nhtsa/sample_300.csv", "fixtures/act3.jsonl"}


def export(destination: Path) -> int:
    paths = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT,
    ).decode().split("\0")
    selected = []
    for name in sorted(set(filter(None, paths))):
        path = Path(name)
        if name in EXCLUDED or not (name in FILES or path.parts[0] in DIRECTORIES):
            continue
        source = ROOT / path
        if source.is_symlink() or not source.is_file() or ROOT not in source.resolve().parents:
            raise ValueError(f"Refusing non-regular or external source: {name}")
        selected.append(path)
    destination.mkdir(parents=True, exist_ok=False)
    for path in selected:
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / path, target)
    return len(selected)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    destination = Path(sys.argv[1]).resolve()
    print(f"Exported {export(destination)} files to {destination}; no Git history included.")

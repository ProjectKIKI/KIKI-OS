#!/usr/bin/env python3
import os
import runpy
import sys
from pathlib import Path


def main():
    repo_root = Path(__file__).resolve().parents[2]
    installer = repo_root / "installer/alpine/overlay/usr/local/bin/kiki-install.py"
    default_config = repo_root / "installer/configs/install.example.yaml"

    if "--config" not in sys.argv:
        sys.argv.extend(["--config", str(default_config)])

    sys.path.insert(0, str(installer.parent))
    os.environ.setdefault("KIKI_REPO_ROOT", str(repo_root))
    runpy.run_path(str(installer), run_name="__main__")


if __name__ == "__main__":
    main()

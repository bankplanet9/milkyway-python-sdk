#!/usr/bin/env python3
"""Write the semantic-release-computed version into the package.

Invoked by @semantic-release/exec's prepareCmd as ``set_version.py <version>``.
Updates ``version = "..."`` in pyproject.toml and ``__version__`` in the package
``__init__.py`` so the built artifacts carry the right version.
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _replace(path: pathlib.Path, pattern: str, replacement: str) -> None:
    text = path.read_text()
    new_text, count = re.subn(pattern, replacement, text, count=1)
    if count != 1:
        raise SystemExit(f"Failed to update version in {path} (pattern not found).")
    path.write_text(new_text)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: set_version.py <version>")
    version = sys.argv[1]

    _replace(
        ROOT / "pyproject.toml",
        r'(?m)^version = "[^"]*"$',
        f'version = "{version}"',
    )
    _replace(
        ROOT / "src" / "milkyway_payments" / "__init__.py",
        r'(?m)^__version__ = "[^"]*"$',
        f'__version__ = "{version}"',
    )
    print(f"Set version to {version}")


if __name__ == "__main__":
    main()

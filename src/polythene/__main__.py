"""Module entry point for ``python -m polythene``."""

from __future__ import annotations


def main() -> None:
    """Invoke the package CLI entry point."""

    from . import main as package_main

    package_main()


if __name__ == "__main__":  # pragma: no cover - convenience execution
    main()

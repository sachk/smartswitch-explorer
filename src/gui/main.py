from __future__ import annotations

import argparse
import sys

from gui.version import get_app_version


def _parse_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--version", action="store_true", help="Print version and exit.")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Initialize Qt/app resources without launching the full UI.",
    )
    return parser.parse_known_args(argv)


def _run_app(argv: list[str]) -> int:
    from gui.app import run_app

    return run_app(argv)


def _run_smoke_test(argv: list[str]) -> int:
    from gui.app import run_smoke_test

    return run_smoke_test(argv)


def main(argv: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    args, qt_args = _parse_args(raw_args)

    if args.version:
        print(get_app_version())
        return 0

    app_argv = [sys.argv[0], *qt_args]
    if args.smoke_test:
        return _run_smoke_test(app_argv)
    return _run_app(app_argv)


if __name__ == "__main__":
    raise SystemExit(main())

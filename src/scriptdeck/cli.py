"""CLI entry: `scriptdeck` or `python -m scriptdeck`."""
import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(prog="scriptdeck")
    sub = parser.add_subparsers(dest="cmd", required=False)
    sub.add_parser("serve", help="Run the API server (default)")
    args = parser.parse_args()
    if args.cmd in (None, "serve"):
        from scriptdeck.app import run
        run()
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
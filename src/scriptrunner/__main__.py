"""Command-line entry point for ``python -m scriptrunner``."""

from .server import serve


def main() -> None:
    serve()


if __name__ == "__main__":
    main()

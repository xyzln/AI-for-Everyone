"""Enable ``python -m aife`` to launch the CLI (forwards to aife.cli.main)."""

from aife.cli import main

if __name__ == "__main__":
    raise SystemExit(main())

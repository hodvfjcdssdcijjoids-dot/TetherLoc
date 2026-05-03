from __future__ import annotations

import sys


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--pymobiledevice3":
        sys.argv = [sys.argv[0], *sys.argv[2:]]
        from pymobiledevice3.__main__ import main as pymobiledevice_main

        pymobiledevice_main()
        return

    try:
        from .app import main as app_main
    except ImportError:
        from ios_geo_spoofer.app import main as app_main

    app_main()


if __name__ == "__main__":
    main()

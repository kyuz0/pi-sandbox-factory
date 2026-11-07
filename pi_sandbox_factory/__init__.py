"""Pi Sandbox Factory: isolated Pi development environments."""
__version__ = "0.2.0a1"

import sys
if sys.platform == "win32":
    raise SystemExit("Run Pi Sandbox Factory inside WSL2 with Linux Podman. See docs/platforms.md for setup.")

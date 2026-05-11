"""macOS .app entry-point — wraps npcreate_studio.app.run() in absolute
imports so PyInstaller can run it as a top-level script.

Equivalent to ``python -m npcreate_studio`` but lives outside the package
so the bundle's launch script has no parent-package context to fight
against.
"""
import sys

from npcreate_studio.app import run

if __name__ == "__main__":
    sys.exit(run())

#!/usr/bin/env python3
"""Use --online --thread-ts <existing-ts> for read-only live checks."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from orca_dot_bridge.cli import main

# Usage: python3 scripts/check_install.py --config /abs/config.yaml [--online ...]
args = sys.argv[1:]
if "--config" in args:
    index = args.index("--config")
    cfg = args[index:index + 2]
    del args[index:index + 2]
else:
    cfg = []
sys.exit(main(cfg + ["doctor"] + args))

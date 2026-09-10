#!/usr/bin/env python3
"""Compatibility shim: the qualification runner moved to ``tools/qualify.py`` when Linux
qualification was added. The documented Windows commands keep working through this file."""
import runpy
import sys
from pathlib import Path

if __name__ == "__main__":
    sys.argv[0] = str(Path(__file__).with_name("qualify.py"))
    runpy.run_path(sys.argv[0], run_name="__main__")

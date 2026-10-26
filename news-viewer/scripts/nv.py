#!/usr/bin/env python3
"""news-viewer command line. Workflow: ../SKILL.md. Commands: `nv.py --help`."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from newsviewer.cli import main  # noqa: E402
from newsviewer.console import use_utf8  # noqa: E402

if __name__ == "__main__":
    use_utf8()
    sys.exit(main())

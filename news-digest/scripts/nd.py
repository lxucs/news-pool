#!/usr/bin/env python3
"""news-digest command line. Workflow: ../SKILL.md. Commands: `nd.py --help`."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from newsdigest.cli import main  # noqa: E402
from newsdigest.console import use_utf8  # noqa: E402

if __name__ == "__main__":
    use_utf8()
    sys.exit(main())

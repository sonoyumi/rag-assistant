"""Entry points: `python -m rag_assistant` or the `rag-assistant` command."""

import sys

from rag_assistant.cli import main

if __name__ == "__main__":
    sys.exit(main())

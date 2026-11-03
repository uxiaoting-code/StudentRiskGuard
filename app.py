"""Streamlit entry point for the StudentRiskGuard MVP."""

from __future__ import annotations

import sys
from pathlib import Path

# HuggingFace Spaces and local `streamlit run app.py` do not require an editable
# package install. Add the src layout explicitly so both paths work.
SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from riskguard.ui.streamlit_app import main  # noqa: E402


main()

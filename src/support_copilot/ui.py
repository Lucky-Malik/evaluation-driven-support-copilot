"""Launch the packaged Streamlit app, including from an installed wheel."""

import subprocess
import sys
from pathlib import Path


def main() -> None:
    app = Path(__file__).with_name("dashboard.py")
    raise SystemExit(
        subprocess.call(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                str(app),
                "--server.address=127.0.0.1",
                "--browser.gatherUsageStats=false",
                *sys.argv[1:],
            ]
        )
    )

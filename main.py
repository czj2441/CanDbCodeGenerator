"""CanMatrix Editor - Interactive CAN message/signal editor.

Entry point for the application.
"""

import sys
import os

# Ensure the project root is on sys.path for proper imports
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from PyQt6.QtWidgets import QApplication
from gui.main_window import MainWindow


def main() -> None:
    """Launch the CanMatrix Editor application."""
    app = QApplication(sys.argv)
    app.setApplicationName("CanMatrix Editor")
    app.setOrganizationName("CanMatrix")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
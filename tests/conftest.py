import os
import sys

# Make the project root importable (agents/, apis/, video/, config, gui)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("STUDIO_NO_BROWSER", "1")

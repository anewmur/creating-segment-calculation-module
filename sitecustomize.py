import sys
from pathlib import Path

stubs_path = Path(__file__).parent / '_local_stubs'
sys.path.insert(0, str(stubs_path))
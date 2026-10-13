import os
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
# Tests never use the user's database or key.
os.environ['ZBL_DATA_DIR']=tempfile.mkdtemp(prefix='zbl-tests-')
os.environ['DEEPSEEK_API_KEY']=''

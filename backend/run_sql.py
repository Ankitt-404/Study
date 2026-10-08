import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv()

sql = Path(sys.argv[1]).read_text()
with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
    conn.execute(sql)
print(f"Ran {sys.argv[1]}")
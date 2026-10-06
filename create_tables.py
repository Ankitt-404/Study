import os
from pathlib import Path
import psycopg
from dotenv import load_dotenv
load_dotenv()

sql = (Path(__file__).parent/"schema.sql").read_text()
with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
    conn.execute(sql)

    print("Tables created.")


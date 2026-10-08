import os

import psycopg
from dotenv import load_dotenv
from pgvector.psycopg import register_vector

load_dotenv()


def get_conn():
    # prepare_threshold=None: no server-side prepared statements (safe behind Neon's pooler)
    conn = psycopg.connect(os.environ["DATABASE_URL"], prepare_threshold=None)
    register_vector(conn)
    return conn
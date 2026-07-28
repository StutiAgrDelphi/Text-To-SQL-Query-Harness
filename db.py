import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

def get_connection():
    # Use the read-only role for anything the agent runs itself
    return psycopg2.connect(os.environ["AGENT_DATABASE_URL"])
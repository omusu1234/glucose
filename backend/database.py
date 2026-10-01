import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

# Example Neon DB URL format: postgresql://[user]:[password]@[neon_hostname]/[dbname]?sslmode=require
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://neondb_owner:npg_VtRPl2XdYj5J@ep-red-pine-b4xg7p4o-pooler.c-6.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require")

def get_db_connection():
    """
    Establish and return a connection to the Neon PostgreSQL database.
    """
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        return conn
    except Exception as e:
        print(f"Error connecting to database: {e}")
        raise e

def create_schema():
    """
    Creates tables if they don't exist and runs necessary ALTER statements.
    """
    schema = """
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        email VARCHAR(255) UNIQUE NOT NULL,
        password_hash VARCHAR(255) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS glucose_logs (
        id SERIAL PRIMARY KEY,
        glucose NUMERIC,
        carbs NUMERIC,
        insulin NUMERIC,
        alcohol BOOLEAN DEFAULT FALSE,
        timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );
    
    ALTER TABLE glucose_logs ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id);
    
    CREATE INDEX IF NOT EXISTS idx_glucose_logs_timestamp ON glucose_logs(timestamp);
    CREATE INDEX IF NOT EXISTS idx_glucose_logs_user_id ON glucose_logs(user_id);

    CREATE TABLE IF NOT EXISTS push_subscriptions (
        id SERIAL PRIMARY KEY,
        user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
        endpoint TEXT NOT NULL,
        p256dh TEXT NOT NULL,
        auth TEXT NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, endpoint)
    );
    """
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(schema)
        conn.commit()
        print("Schema ensured (V2).")
    except Exception as e:
        print(f"Schema creation failed: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    create_schema()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import uvicorn

from database import get_db_connection, create_schema
from analytics import generate_forecast

app = FastAPI(title="Glucose Management API")

# Allow CORS for local frontend testing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic models for incoming data
class LogEntry(BaseModel):
    glucose: Optional[float] = None
    carbs: Optional[float] = None
    insulin: Optional[float] = None
    alcohol: bool = False
    timestamp: datetime

@app.on_event("startup")
def startup_event():
    # Ensure database table exists on startup
    create_schema()

@app.post("/api/logs/bulk")
def bulk_insert_logs(logs: List[LogEntry]):
    """
    Endpoint for syncing offline data from the PWA's IndexedDB.
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            for log in logs:
                cur.execute(
                    """
                    INSERT INTO glucose_logs (glucose, carbs, insulin, alcohol, timestamp)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (log.glucose, log.carbs, log.insulin, log.alcohol, log.timestamp)
                )
        conn.commit()
        return {"status": "success", "inserted": len(logs)}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.get("/api/forecast")
def get_glucose_forecast():
    """
    Fetches recent logs from DB and runs SARIMA forecasting model to predict next 2 hours.
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Fetch last 24 hours of data for a robust forecast
            # Assuming single user for this foundation. In production, filter by user_id.
            cur.execute(
                """
                SELECT glucose, timestamp 
                FROM glucose_logs 
                WHERE glucose IS NOT NULL
                ORDER BY timestamp ASC
                LIMIT 500
                """
            )
            records = cur.fetchall()
            
        if not records:
            return {"forecast_value": "--", "trend": "STABLE", "msg": "No data"}
            
        forecast_result = generate_forecast(records)
        return forecast_result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

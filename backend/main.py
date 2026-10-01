from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict
from datetime import datetime
import os
import json
import uvicorn
from pywebpush import webpush, WebPushException

from database import get_db_connection, create_schema
from auth import get_password_hash, verify_password, create_access_token, get_current_user
from analytics import generate_forecast, calculate_iob

app = FastAPI(title="Glucose Management API V2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "dummy_private_key")
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "dummy_public_key")
VAPID_CLAIMS = {"sub": "mailto:admin@example.com"}

@app.on_event("startup")
def startup_event():
    create_schema()

# --- Auth Models & Endpoints ---
class UserCreate(BaseModel):
    email: str
    password: str

class UserLogin(BaseModel):
    email: str
    password: str

@app.post("/api/register")
def register_user(user: UserCreate):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE email = %s", (user.email,))
            if cur.fetchone():
                raise HTTPException(status_code=400, detail="Email already registered")
            
            hashed_pwd = get_password_hash(user.password)
            cur.execute(
                "INSERT INTO users (email, password_hash) VALUES (%s, %s) RETURNING id",
                (user.email, hashed_pwd)
            )
            user_id = cur.fetchone()['id']
        conn.commit()
        return {"status": "success", "user_id": user_id}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.post("/api/login")
def login_user(user: UserLogin):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, password_hash FROM users WHERE email = %s", (user.email,))
            db_user = cur.fetchone()
            
            if not db_user or not verify_password(user.password, db_user['password_hash']):
                raise HTTPException(status_code=401, detail="Invalid credentials")
                
            token = create_access_token(data={"sub": db_user['id']})
            return {"access_token": token, "token_type": "bearer"}
    finally:
        conn.close()

# --- Logging & Analytics Models & Endpoints ---
class LogEntry(BaseModel):
    glucose: Optional[float] = None
    carbs: Optional[float] = None
    insulin: Optional[float] = None
    alcohol: bool = False
    timestamp: datetime

def check_forecast_and_notify(user_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Fetch recent logs to forecast
            cur.execute(
                "SELECT glucose, timestamp FROM glucose_logs WHERE user_id = %s AND glucose IS NOT NULL ORDER BY timestamp ASC LIMIT 500",
                (user_id,)
            )
            records = cur.fetchall()
            
            if not records:
                return
            
            forecast = generate_forecast(records)
            if forecast["forecast_value"] == "--":
                return
                
            val = float(forecast["forecast_value"])
            title = ""
            body = ""
            if val < 70:
                title = "Hypoglycemia Alert"
                body = f"Forecasted drop to {val} mg/dL. Consider having a snack."
            elif val > 250:
                title = "Hyperglycemia Alert"
                body = f"Forecasted spike to {val} mg/dL. Consider monitoring."
                
            if title:
                # Fetch push subscriptions for user
                cur.execute("SELECT endpoint, p256dh, auth FROM push_subscriptions WHERE user_id = %s", (user_id,))
                subs = cur.fetchall()
                for sub in subs:
                    try:
                        subscription_info = {
                            "endpoint": sub["endpoint"],
                            "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}
                        }
                        webpush(
                            subscription_info=subscription_info,
                            data=json.dumps({"title": title, "body": body}),
                            vapid_private_key=VAPID_PRIVATE_KEY,
                            vapid_claims=VAPID_CLAIMS
                        )
                    except WebPushException as ex:
                        print("Web Push Error:", repr(ex))
    except Exception as e:
        print("Background task error:", e)
    finally:
        conn.close()

@app.post("/api/logs/bulk")
def bulk_insert_logs(logs: List[LogEntry], background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    user_id = current_user['id']
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            for log in logs:
                cur.execute(
                    """
                    INSERT INTO glucose_logs (user_id, glucose, carbs, insulin, alcohol, timestamp)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (user_id, log.glucose, log.carbs, log.insulin, log.alcohol, log.timestamp)
                )
        conn.commit()
        
        # Trigger background task for notifications
        background_tasks.add_task(check_forecast_and_notify, user_id)
        
        return {"status": "success", "inserted": len(logs)}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.get("/api/logs/recent")
def get_recent_logs(current_user: dict = Depends(get_current_user)):
    user_id = current_user['id']
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT glucose, carbs, insulin, timestamp 
                FROM glucose_logs 
                WHERE user_id = %s AND timestamp >= NOW() - INTERVAL '24 HOURS'
                ORDER BY timestamp ASC
                """,
                (user_id,)
            )
            records = cur.fetchall()
        return records
    finally:
        conn.close()

@app.get("/api/forecast")
def get_glucose_forecast(current_user: dict = Depends(get_current_user)):
    user_id = current_user['id']
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT glucose, timestamp 
                FROM glucose_logs 
                WHERE user_id = %s AND glucose IS NOT NULL
                ORDER BY timestamp ASC LIMIT 500
                """, (user_id,)
            )
            records = cur.fetchall()
            
        if not records:
            return {"forecast_value": "--", "trend": "STABLE", "msg": "No data"}
            
        return generate_forecast(records)
    finally:
        conn.close()

@app.get("/api/iob")
def get_iob(current_user: dict = Depends(get_current_user)):
    user_id = current_user['id']
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT insulin, timestamp 
                FROM glucose_logs 
                WHERE user_id = %s AND insulin IS NOT NULL AND timestamp >= NOW() - INTERVAL '4 HOURS'
                """, (user_id,)
            )
            records = cur.fetchall()
            
        iob = calculate_iob(records)
        return {"iob": iob}
    finally:
        conn.close()

# --- Web Push Subscription ---
class PushSubscriptionKeys(BaseModel):
    p256dh: str
    auth: str

class PushSubscription(BaseModel):
    endpoint: str
    keys: PushSubscriptionKeys

@app.post("/api/subscribe")
def subscribe_push(sub: PushSubscription, current_user: dict = Depends(get_current_user)):
    user_id = current_user['id']
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id, endpoint) DO NOTHING
                """,
                (user_id, sub.endpoint, sub.keys.p256dh, sub.keys.auth)
            )
        conn.commit()
        return {"status": "subscribed"}
    finally:
        conn.close()

@app.get("/api/vapid_public_key")
def get_vapid_key():
    return {"public_key": VAPID_PUBLIC_KEY}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

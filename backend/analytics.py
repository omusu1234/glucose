import pandas as pd
from statsmodels.tsa.statespace.sarimax import SARIMAX
import warnings

warnings.filterwarnings("ignore")

def generate_forecast(db_records):
    """
    Generates a 2-hour forecast based on historical glucose logs.
    
    Args:
        db_records (list of dicts): Must contain 'timestamp' and 'glucose' keys.
        
    Returns:
        dict: containing 'forecast_value' (float) and 'trend' (str: 'UP', 'DOWN', 'STABLE')
    """
    if not db_records or len(db_records) < 10:
        # Not enough data for a meaningful SARIMA model
        return {"forecast_value": "--", "trend": "STABLE", "msg": "Insufficient data"}

    # Convert to DataFrame
    df = pd.DataFrame(db_records)
    
    # Ensure datetime format and sort
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp')
    
    # Filter out records without glucose reading
    df = df.dropna(subset=['glucose'])
    
    if len(df) < 10:
        return {"forecast_value": "--", "trend": "STABLE", "msg": "Insufficient glucose data"}

    # Set timestamp as index
    df.set_index('timestamp', inplace=True)
    
    # SARIMA requires evenly spaced data (e.g., every 15 minutes)
    # We will resample and interpolate missing values
    df_resampled = df[['glucose']].resample('15T').mean()
    df_resampled['glucose'] = df_resampled['glucose'].interpolate(method='linear')
    
    # Drop any remaining NaNs after interpolation (usually at the start)
    df_resampled = df_resampled.dropna()
    
    if len(df_resampled) < 10:
         return {"forecast_value": "--", "trend": "STABLE", "msg": "Insufficient data after resampling"}

    series = df_resampled['glucose']
    
    try:
        # Fit a basic SARIMA model
        # Order (p,d,q) and Seasonal Order (P,D,Q,s)
        # Note: These are baseline parameters. Real-world data would require grid search optimization.
        model = SARIMAX(series, order=(1, 1, 1), seasonal_order=(0, 0, 0, 0))
        model_fit = model.fit(disp=False)
        
        # Forecast next 2 hours (8 steps of 15 mins)
        steps = 8
        forecast = model_fit.forecast(steps=steps)
        
        last_actual = series.iloc[-1]
        forecast_final = forecast.iloc[-1]
        
        # Determine trend
        diff = forecast_final - last_actual
        if diff > 5:
            trend = "UP"
        elif diff < -5:
            trend = "DOWN"
        else:
            trend = "STABLE"
            
        return {
            "forecast_value": round(forecast_final, 1),
            "trend": trend,
            "msg": "Success"
        }
        
    except Exception as e:
        print(f"Forecasting error: {e}")
        return {"forecast_value": "--", "trend": "STABLE", "msg": "Error fitting model"}

def calculate_iob(insulin_records):
    """
    Calculates active Insulin-On-Board (IOB).
    Assumes rapid-acting insulin (duration ~4 hours).
    Decay profile: roughly linear over 4 hours for simplicity.
    """
    if not insulin_records:
        return 0.0
    
    iob = 0.0
    now = pd.Timestamp.utcnow()
    
    for r in insulin_records:
        dose = r.get('insulin')
        if dose is None or dose <= 0:
            continue
            
        # Ensure timestamp is tz-aware UTC
        ts = pd.to_datetime(r['timestamp'])
        if ts.tzinfo is None:
            ts = ts.tz_localize('UTC')
            
        # Time since dose in hours
        hours_elapsed = (now - ts).total_seconds() / 3600
        
        if 0 <= hours_elapsed < 4:
            # Linear decay: 100% active at t=0, 0% at t=4
            remaining = dose * (1 - (hours_elapsed / 4))
            iob += remaining
            
    return round(iob, 2)


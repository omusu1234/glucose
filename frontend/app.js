const API_BASE_URL = 'https://glucose-jpxx.onrender.com/api';

// DOM Elements
const form = document.getElementById('log-form');
const glucoseInput = document.getElementById('glucose');
const carbsInput = document.getElementById('carbs');
const insulinInput = document.getElementById('insulin');
const alcoholInput = document.getElementById('alcohol');
const statusDot = document.getElementById('status-dot');
const statusText = document.getElementById('status-text');
const queueCount = document.getElementById('queue-count');
const forecastValue = document.getElementById('forecast-value');

// IndexedDB Setup
const DB_NAME = 'GlucoseAppDB';
const STORE_NAME = 'offline_logs';
let db;

function initDB() {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open(DB_NAME, 1);
        
        request.onerror = (event) => {
            console.error('IndexedDB error:', event.target.error);
            reject(event.target.error);
        };
        
        request.onsuccess = (event) => {
            db = event.target.result;
            updateQueueCount();
            resolve(db);
        };
        
        request.onupgradeneeded = (event) => {
            db = event.target.result;
            if (!db.objectStoreNames.contains(STORE_NAME)) {
                db.createObjectStore(STORE_NAME, { keyPath: 'id', autoIncrement: true });
            }
        };
    });
}

// Add a log to IndexedDB
function saveLogLocally(logData) {
    return new Promise((resolve, reject) => {
        const transaction = db.transaction([STORE_NAME], 'readwrite');
        const store = transaction.objectStore(STORE_NAME);
        const request = store.add(logData);
        
        request.onsuccess = () => {
            updateQueueCount();
            resolve();
        };
        request.onerror = (event) => reject(event.target.error);
    });
}

// Fetch all unsynced logs from IndexedDB
function getUnsyncedLogs() {
    return new Promise((resolve, reject) => {
        const transaction = db.transaction([STORE_NAME], 'readonly');
        const store = transaction.objectStore(STORE_NAME);
        const request = store.getAll();
        
        request.onsuccess = () => resolve(request.result);
        request.onerror = (event) => reject(event.target.error);
    });
}

// Clear a synced log from IndexedDB
function removeSyncedLog(id) {
    return new Promise((resolve, reject) => {
        const transaction = db.transaction([STORE_NAME], 'readwrite');
        const store = transaction.objectStore(STORE_NAME);
        const request = store.delete(id);
        
        request.onsuccess = () => {
            updateQueueCount();
            resolve();
        };
        request.onerror = (event) => reject(event.target.error);
    });
}

// Update the queue counter in the UI
async function updateQueueCount() {
    try {
        const logs = await getUnsyncedLogs();
        queueCount.textContent = `${logs.length} pending`;
    } catch (e) {
        console.error('Error counting logs', e);
    }
}

// Sync Logic: Attempt to send offline data to backend
async function syncData() {
    if (!navigator.onLine) return;
    
    try {
        const logs = await getUnsyncedLogs();
        if (logs.length === 0) return;
        
        statusText.textContent = 'Syncing...';
        
        // POST to backend (bulk insert or loop)
        const response = await fetch(`${API_BASE_URL}/logs/bulk`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(logs)
        });
        
        if (response.ok) {
            // Remove successful syncs from local storage
            for (const log of logs) {
                await removeSyncedLog(log.id);
            }
            console.log('Sync complete');
        }
    } catch (error) {
        console.error('Sync failed:', error);
    } finally {
        updateNetworkStatus();
        fetchForecast(); // Refresh forecast after sync
    }
}

// Fetch prediction from backend
async function fetchForecast() {
    if (!navigator.onLine) {
        forecastValue.innerHTML = '<span>Offline</span>';
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE_URL}/forecast`);
        if (response.ok) {
            const data = await response.json();
            // Assuming backend returns { trend: 'UP' | 'DOWN' | 'STABLE', value: float }
            let arrow = '➡️';
            let color = 'var(--text-main)';
            if (data.trend === 'UP') {
                arrow = '↗️';
                color = 'var(--danger-color)';
            } else if (data.trend === 'DOWN') {
                arrow = '↘️';
                color = 'var(--accent-color)';
            }
            
            forecastValue.innerHTML = `<span style="color: ${color}">${data.forecast_value} mg/dL ${arrow}</span>`;
        }
    } catch (error) {
        console.error('Error fetching forecast:', error);
        forecastValue.innerHTML = '<span>--</span>';
    }
}

// Form Submission
form.addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const logData = {
        glucose: glucoseInput.value ? parseFloat(glucoseInput.value) : null,
        carbs: carbsInput.value ? parseFloat(carbsInput.value) : null,
        insulin: insulinInput.value ? parseFloat(insulinInput.value) : null,
        alcohol: alcoholInput.checked,
        timestamp: new Date().toISOString()
    };
    
    try {
        await saveLogLocally(logData);
        // Clear form
        glucoseInput.value = '';
        carbsInput.value = '';
        insulinInput.value = '';
        alcoholInput.checked = false;
        
        // Attempt sync immediately
        syncData();
        
        alert('Log saved!');
    } catch (error) {
        console.error('Error saving log:', error);
        alert('Failed to save log locally.');
    }
});

// Network Status Handling
function updateNetworkStatus() {
    if (navigator.onLine) {
        statusDot.classList.add('online');
        statusText.textContent = 'Online';
        syncData();
    } else {
        statusDot.classList.remove('online');
        statusText.textContent = 'Offline';
    }
}

window.addEventListener('online', updateNetworkStatus);
window.addEventListener('offline', updateNetworkStatus);

// Service Worker Registration
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/sw.js')
            .then(reg => console.log('SW registered:', reg))
            .catch(err => console.error('SW reg failed:', err));
    });
}

// Initialize App
initDB().then(() => {
    updateNetworkStatus();
    fetchForecast();
});

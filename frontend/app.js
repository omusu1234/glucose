const API_BASE_URL = 'https://glucose-jpxx.onrender.com/api';

// DOM Elements
const authSection = document.getElementById('auth-section');
const dashboardSection = document.getElementById('dashboard-section');
const logoutBtn = document.getElementById('logout-btn');
const authForm = document.getElementById('auth-form');
const toggleAuthBtn = document.getElementById('toggle-auth');
const authTitle = document.getElementById('auth-title');

const form = document.getElementById('log-form');
const glucoseInput = document.getElementById('glucose');
const carbsInput = document.getElementById('carbs');
const insulinInput = document.getElementById('insulin');
const alcoholInput = document.getElementById('alcohol');
const statusDot = document.getElementById('status-dot');
const statusText = document.getElementById('status-text');
const queueCount = document.getElementById('queue-count');
const forecastValue = document.getElementById('forecast-value');
const iobValue = document.getElementById('iob-value');
let glucoseChartInstance = null;

let isLoginMode = true;
let authToken = localStorage.getItem('jwt_token') || null;

// IndexedDB Setup
const DB_NAME = 'GlucoseAppDB';
const STORE_NAME = 'offline_logs';
let db;

function initDB() {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open(DB_NAME, 2); // Version 2
        
        request.onerror = (event) => reject(event.target.error);
        
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

// --- Auth Logic ---
function checkAuth() {
    if (authToken) {
        authSection.style.display = 'none';
        dashboardSection.style.display = 'block';
        logoutBtn.style.display = 'block';
        initDashboard();
    } else {
        authSection.style.display = 'block';
        dashboardSection.style.display = 'none';
        logoutBtn.style.display = 'none';
    }
}

toggleAuthBtn.addEventListener('click', (e) => {
    e.preventDefault();
    isLoginMode = !isLoginMode;
    authTitle.textContent = isLoginMode ? 'Login' : 'Register';
    toggleAuthBtn.textContent = isLoginMode ? 'Need an account? Register' : 'Already have an account? Login';
});

authForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const email = document.getElementById('email').value;
    const password = document.getElementById('password').value;
    const endpoint = isLoginMode ? '/login' : '/register';
    
    try {
        const res = await fetch(API_BASE_URL + endpoint, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({email, password})
        });
        const data = await res.json();
        
        if (res.ok) {
            if (isLoginMode) {
                authToken = data.access_token;
                localStorage.setItem('jwt_token', authToken);
                checkAuth();
            } else {
                alert('Registration successful! Please login.');
                isLoginMode = true;
                toggleAuthBtn.click();
            }
        } else {
            alert(data.detail || 'Authentication failed');
        }
    } catch (err) {
        alert('Network error during authentication');
    }
});

logoutBtn.addEventListener('click', () => {
    authToken = null;
    localStorage.removeItem('jwt_token');
    checkAuth();
});

// --- API Helpers ---
async function fetchWithAuth(url, options = {}) {
    if (!options.headers) options.headers = {};
    options.headers['Authorization'] = `Bearer ${authToken}`;
    return fetch(url, options);
}

// --- Dashboard Logic ---
async function initDashboard() {
    updateNetworkStatus();
    if (navigator.onLine) {
        await syncData();
        await Promise.all([
            fetchForecast(),
            fetchIOB(),
            fetchAndRenderChart()
        ]);
        await setupWebPush();
    }
}

function saveLogLocally(logData) {
    return new Promise((resolve, reject) => {
        const transaction = db.transaction([STORE_NAME], 'readwrite');
        const store = transaction.objectStore(STORE_NAME);
        const request = store.add(logData);
        request.onsuccess = () => { updateQueueCount(); resolve(); };
        request.onerror = (event) => reject(event.target.error);
    });
}

function getUnsyncedLogs() {
    return new Promise((resolve, reject) => {
        const transaction = db.transaction([STORE_NAME], 'readonly');
        const store = transaction.objectStore(STORE_NAME);
        const request = store.getAll();
        request.onsuccess = () => resolve(request.result);
        request.onerror = (event) => reject(event.target.error);
    });
}

function removeSyncedLog(id) {
    return new Promise((resolve, reject) => {
        const transaction = db.transaction([STORE_NAME], 'readwrite');
        const store = transaction.objectStore(STORE_NAME);
        const request = store.delete(id);
        request.onsuccess = () => { updateQueueCount(); resolve(); };
        request.onerror = (event) => reject(event.target.error);
    });
}

async function updateQueueCount() {
    try {
        const logs = await getUnsyncedLogs();
        queueCount.textContent = `${logs.length} pending`;
    } catch (e) { }
}

async function syncData() {
    if (!navigator.onLine || !authToken) return;
    try {
        const logs = await getUnsyncedLogs();
        if (logs.length === 0) return;
        statusText.textContent = 'Syncing...';
        
        const response = await fetchWithAuth(`${API_BASE_URL}/logs/bulk`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(logs)
        });
        
        if (response.ok) {
            for (const log of logs) await removeSyncedLog(log.id);
            fetchForecast();
            fetchIOB();
            fetchAndRenderChart();
        } else if (response.status === 401) {
            logoutBtn.click();
        }
    } catch (error) {
        console.error('Sync failed:', error);
    } finally {
        updateNetworkStatus();
    }
}

async function fetchForecast() {
    if (!navigator.onLine) return;
    try {
        const res = await fetchWithAuth(`${API_BASE_URL}/forecast`);
        if (res.ok) {
            const data = await res.json();
            let arrow = '➡️', color = 'var(--text-main)';
            if (data.trend === 'UP') { arrow = '↗️'; color = 'var(--danger-color)'; }
            else if (data.trend === 'DOWN') { arrow = '↘️'; color = 'var(--accent-color)'; }
            forecastValue.innerHTML = `<span style="color: ${color}">${data.forecast_value} ${arrow}</span>`;
        }
    } catch (e) {}
}

async function fetchIOB() {
    if (!navigator.onLine) return;
    try {
        const res = await fetchWithAuth(`${API_BASE_URL}/iob`);
        if (res.ok) {
            const data = await res.json();
            iobValue.innerHTML = `<span>${data.iob} U</span>`;
        }
    } catch (e) {}
}

async function fetchAndRenderChart() {
    if (!navigator.onLine) return;
    try {
        const res = await fetchWithAuth(`${API_BASE_URL}/logs/recent`);
        if (res.ok) {
            const data = await res.json();
            
            const labels = data.map(d => {
                const date = new Date(d.timestamp);
                return `${date.getHours()}:${date.getMinutes().toString().padStart(2, '0')}`;
            });
            const glucoseData = data.map(d => d.glucose);
            
            if (glucoseChartInstance) glucoseChartInstance.destroy();
            
            const ctx = document.getElementById('glucoseChart').getContext('2d');
            glucoseChartInstance = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Glucose (mg/dL)',
                        data: glucoseData,
                        borderColor: '#3b82f6',
                        backgroundColor: 'rgba(59, 130, 246, 0.1)',
                        borderWidth: 2,
                        tension: 0.4,
                        fill: true
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        y: { 
                            beginAtZero: false,
                            grid: { color: '#334155' },
                            ticks: { color: '#94a3b8' }
                        },
                        x: { 
                            grid: { display: false },
                            ticks: { color: '#94a3b8', maxTicksLimit: 6 }
                        }
                    }
                }
            });
        }
    } catch (e) {}
}

form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const logData = {
        glucose: glucoseInput.value ? parseFloat(glucoseInput.value) : null,
        carbs: carbsInput.value ? parseFloat(carbsInput.value) : null,
        insulin: insulinInput.value ? parseFloat(insulinInput.value) : null,
        alcohol: alcoholInput.checked,
        timestamp: new Date().toISOString()
    };
    
    await saveLogLocally(logData);
    form.reset();
    syncData();
    alert('Log saved!');
});

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

// --- Web Push Setup ---
function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - base64String.length % 4) % 4);
  const base64 = (base64String + padding).replace(/\-/g, '+').replace(/_/g, '/');
  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

async function setupWebPush() {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) return;
    
    try {
        const reg = await navigator.serviceWorker.ready;
        let sub = await reg.pushManager.getSubscription();
        
        if (!sub) {
            // Get VAPID public key from backend
            const vapidRes = await fetchWithAuth(`${API_BASE_URL}/vapid_public_key`);
            if (!vapidRes.ok) return;
            const vapidData = await vapidRes.json();
            
            sub = await reg.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: urlBase64ToUint8Array(vapidData.public_key)
            });
        }
        
        // Send subscription to backend
        await fetchWithAuth(`${API_BASE_URL}/subscribe`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(sub)
        });
        
    } catch (e) {
        console.error('Web Push setup failed:', e);
    }
}

if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/sw.js');
    });
}

initDB().then(() => {
    checkAuth();
});

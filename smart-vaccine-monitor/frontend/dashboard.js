/**
 * Smart Vaccine Monitor — Dashboard JavaScript
 * Handles WebSocket connection, Chart.js rendering, and real-time UI updates.
 */

// ============================================================
// CONFIGURATION
// ============================================================
const WS_URL = `ws://${window.location.host}/ws`;
const API_BASE = window.location.origin;
const MAX_CHART_POINTS = 60;
const MAX_TABLE_ROWS = 10;

// ============================================================
// STATE
// ============================================================
let ws = null;
let reconnectDelay = 1000;
const maxReconnectDelay = 30000;
let chartInstance = null;
let chartLabels = [];
let chartTempData = [];
let chartSafeMaxData = [];
let chartSafeMinData = [];

// ============================================================
// INITIALIZATION
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
    initChart();
    fetchInitialData();
    fetchReport();
    fetchHealthStatus();
    connectWebSocket();

    // Refresh report button
    document.getElementById('refresh-report-btn').addEventListener('click', fetchReport);
});

// ============================================================
// WEBSOCKET CONNECTION
// ============================================================
function connectWebSocket() {
    try {
        ws = new WebSocket(WS_URL);

        ws.onopen = () => {
            console.log('WebSocket connected');
            reconnectDelay = 1000;
            updateConnectionStatus(true);

            // Send periodic pings
            setInterval(() => {
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send('ping');
                }
            }, 30000);
        };

        ws.onmessage = (event) => {
            try {
                if (event.data === 'pong') return;
                const data = JSON.parse(event.data);
                handleDataUpdate(data);
            } catch (e) {
                console.error('Failed to parse WebSocket message:', e);
            }
        };

        ws.onclose = () => {
            console.log('WebSocket disconnected');
            updateConnectionStatus(false);
            scheduleReconnect();
        };

        ws.onerror = (error) => {
            console.error('WebSocket error:', error);
            updateConnectionStatus(false);
        };
    } catch (e) {
        console.error('WebSocket connection failed:', e);
        updateConnectionStatus(false);
        scheduleReconnect();
    }
}

function scheduleReconnect() {
    console.log(`Reconnecting in ${reconnectDelay / 1000}s...`);
    setTimeout(() => {
        reconnectDelay = Math.min(reconnectDelay * 2, maxReconnectDelay);
        connectWebSocket();
    }, reconnectDelay);
}

function updateConnectionStatus(online) {
    const badge = document.getElementById('connection-status');
    const text = document.getElementById('connection-text');
    if (online) {
        badge.className = 'connection-badge online';
        text.textContent = 'LIVE';
    } else {
        badge.className = 'connection-badge offline';
        text.textContent = 'OFFLINE';
    }
}

// ============================================================
// DATA FETCHING
// ============================================================
async function fetchInitialData() {
    try {
        const response = await fetch(`${API_BASE}/api/readings?limit=${MAX_CHART_POINTS}`);
        if (!response.ok) return;
        const readings = await response.json();

        if (readings && readings.length > 0) {
            // Populate chart with history
            readings.forEach(r => {
                addChartPoint(r.timestamp, r.temp_internal);
            });
            chartInstance.update('none');

            // Update UI with latest data
            const latest = readings[readings.length - 1];
            handleDataUpdate(latest);

            // Populate table
            readings.slice(-MAX_TABLE_ROWS).forEach(r => {
                addTableRow(r);
            });
        }
    } catch (e) {
        console.error('Failed to fetch initial data:', e);
    }
}

async function fetchReport() {
    try {
        const response = await fetch(`${API_BASE}/api/report/latest`);
        if (!response.ok) return;
        const data = await response.json();

        const reportEl = document.getElementById('report-content');
        if (data.report) {
            reportEl.innerHTML = '';
            reportEl.textContent = data.report;
        }
    } catch (e) {
        console.error('Failed to fetch report:', e);
    }
}

async function fetchHealthStatus() {
    try {
        const response = await fetch(`${API_BASE}/health`);
        if (!response.ok) return;
        const data = await response.json();

        const modeText = document.getElementById('mode-text');
        modeText.textContent = data.mode === 'simulation' ? 'SIMULATION' : 'LIVE';
    } catch (e) {
        console.error('Failed to fetch health status:', e);
    }
}

// ============================================================
// DATA HANDLING
// ============================================================
function handleDataUpdate(data) {
    updateTemperature(data);
    updateRiskGauge(data);
    updateStatusBadge(data);
    updateVVM(data);
    updateETA(data);
    updateHumidity(data);
    addChartPoint(data.timestamp, data.temp_internal);
    addTableRow(data);

    // Fetch updated report on status change
    if (data.status === 'WARNING' || data.status === 'CRITICAL') {
        setTimeout(fetchReport, 2000);
    }
}

// ============================================================
// UI UPDATE FUNCTIONS
// ============================================================
function updateTemperature(data) {
    const tempValue = document.getElementById('temp-value');
    const tempExt = document.getElementById('temp-ext');
    const tempCard = document.getElementById('temp-card');
    const anomalyBadge = document.getElementById('anomaly-badge');

    tempValue.textContent = data.temp_internal.toFixed(1);
    tempExt.textContent = `Ext: ${data.temp_external.toFixed(1)}°C`;

    // Color based on status
    tempCard.classList.remove('warning', 'critical', 'anomaly');
    if (data.status === 'CRITICAL') {
        tempCard.classList.add('critical');
    } else if (data.status === 'WARNING') {
        tempCard.classList.add('warning');
    }

    // Anomaly indicator
    if (data.is_anomaly) {
        tempCard.classList.add('anomaly');
        anomalyBadge.style.display = 'block';
    } else {
        anomalyBadge.style.display = 'none';
    }
}

function updateRiskGauge(data) {
    const score = Math.min(100, Math.max(0, data.risk_score));
    const gaugeText = document.getElementById('risk-gauge-text');
    const gaugeFill = document.getElementById('gauge-fill');

    gaugeText.textContent = Math.round(score);

    // Arc length calculation: full arc ≈ 142
    const arcLength = (score / 100) * 142;
    gaugeFill.setAttribute('stroke-dasharray', `${arcLength} 142`);

    // Color the gauge text based on score
    if (score < 30) {
        gaugeText.style.fill = '#10b981';
    } else if (score < 70) {
        gaugeText.style.fill = '#f59e0b';
    } else {
        gaugeText.style.fill = '#ef4444';
    }
}

function updateStatusBadge(data) {
    const badge = document.getElementById('status-badge');
    const text = document.getElementById('status-text');

    text.textContent = data.status;
    badge.className = 'status-badge-large ' + data.status.toLowerCase();
}

function updateVVM(data) {
    const fill = document.getElementById('vvm-fill');
    const damageText = document.getElementById('vvm-damage-text');
    const potencyText = document.getElementById('potency-text');

    const damagePercent = Math.min(100, data.vvm_damage * 100);
    fill.style.width = `${damagePercent}%`;

    damageText.textContent = data.vvm_damage.toFixed(6);

    potencyText.textContent = `${data.potency_percent.toFixed(1)}% potency`;

    // Color potency based on value
    if (data.potency_percent > 80) {
        potencyText.style.color = '#10b981';
    } else if (data.potency_percent > 50) {
        potencyText.style.color = '#f59e0b';
    } else {
        potencyText.style.color = '#ef4444';
    }
}

function updateETA(data) {
    const etaValue = document.getElementById('eta-value');
    const etaUnit = document.getElementById('eta-unit');
    const etaSub = document.getElementById('eta-sub');
    const etaCard = document.getElementById('eta-card');
    const exposureDisplay = document.getElementById('exposure-display');

    etaCard.classList.remove('warning', 'critical');

    if (data.status === 'CRITICAL') {
        etaValue.textContent = '!!';
        etaUnit.textContent = '';
        etaSub.textContent = 'CRITICAL NOW';
        etaCard.classList.add('critical');
    } else if (data.eta_to_critical !== null && data.eta_to_critical !== undefined) {
        etaValue.textContent = data.eta_to_critical;
        etaUnit.textContent = 'min';
        etaSub.textContent = 'until CRITICAL status';
        etaCard.classList.add('warning');
    } else {
        etaValue.textContent = '--';
        etaUnit.textContent = 'min';
        etaSub.textContent = 'No risk detected';
    }

    exposureDisplay.textContent = `Exposure: ${data.exposure_minutes} min`;
}

function updateHumidity(data) {
    const humidityDisplay = document.getElementById('humidity-display');
    humidityDisplay.textContent = `Humidity: ${data.humidity.toFixed(1)}%`;
}

// ============================================================
// CHART.JS
// ============================================================
function initChart() {
    const ctx = document.getElementById('temp-chart').getContext('2d');

    chartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: chartLabels,
            datasets: [
                {
                    label: 'Internal Temp (°C)',
                    data: chartTempData,
                    borderColor: '#3b82f6',
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                    borderWidth: 2.5,
                    fill: false,
                    tension: 0.3,
                    pointRadius: 0,
                    pointHoverRadius: 5,
                    pointHoverBackgroundColor: '#3b82f6',
                },
                {
                    label: 'Safe Max (8°C)',
                    data: chartSafeMaxData,
                    borderColor: 'rgba(239, 68, 68, 0.4)',
                    borderWidth: 1,
                    borderDash: [6, 4],
                    fill: false,
                    pointRadius: 0,
                    pointHoverRadius: 0,
                },
                {
                    label: 'Safe Min (2°C)',
                    data: chartSafeMinData,
                    borderColor: 'rgba(59, 130, 246, 0.4)',
                    borderWidth: 1,
                    borderDash: [6, 4],
                    fill: '-1',
                    backgroundColor: 'rgba(16, 185, 129, 0.05)',
                    pointRadius: 0,
                    pointHoverRadius: 0,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: {
                duration: 300,
            },
            interaction: {
                mode: 'index',
                intersect: false,
            },
            scales: {
                x: {
                    display: true,
                    grid: {
                        color: 'rgba(31, 41, 55, 0.5)',
                    },
                    ticks: {
                        color: '#6b7280',
                        font: { family: 'Rajdhani', size: 11 },
                        maxRotation: 0,
                        maxTicksLimit: 10,
                    },
                },
                y: {
                    display: true,
                    grid: {
                        color: 'rgba(31, 41, 55, 0.5)',
                    },
                    ticks: {
                        color: '#6b7280',
                        font: { family: 'Rajdhani', size: 12 },
                        callback: (v) => v + '°C',
                    },
                    suggestedMin: 0,
                    suggestedMax: 20,
                },
            },
            plugins: {
                legend: {
                    display: true,
                    position: 'top',
                    labels: {
                        color: '#9ca3af',
                        font: { family: 'Inter', size: 11 },
                        usePointStyle: true,
                        pointStyle: 'line',
                        padding: 20,
                    },
                },
                tooltip: {
                    backgroundColor: '#1f2937',
                    titleColor: '#f9fafb',
                    bodyColor: '#d1d5db',
                    borderColor: '#374151',
                    borderWidth: 1,
                    titleFont: { family: 'Inter', weight: '600' },
                    bodyFont: { family: 'Rajdhani', size: 13 },
                    padding: 12,
                    displayColors: true,
                    callbacks: {
                        label: (ctx) => `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(1)}°C`,
                    },
                },
            },
        },
    });
}

function addChartPoint(timestamp, temp) {
    // Format timestamp for display
    const label = formatTime(timestamp);

    chartLabels.push(label);
    chartTempData.push(temp);
    chartSafeMaxData.push(8);
    chartSafeMinData.push(2);

    // Keep only last N points
    if (chartLabels.length > MAX_CHART_POINTS) {
        chartLabels.shift();
        chartTempData.shift();
        chartSafeMaxData.shift();
        chartSafeMinData.shift();
    }

    if (chartInstance) {
        chartInstance.update('none');
    }
}

function formatTime(timestamp) {
    try {
        const date = new Date(timestamp);
        return date.toLocaleTimeString('en-US', {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false,
        });
    } catch {
        return timestamp.substring(11, 19);
    }
}

// ============================================================
// TABLE
// ============================================================
function addTableRow(data) {
    const tbody = document.getElementById('readings-tbody');

    // Remove "Waiting for data" placeholder
    const emptyRow = tbody.querySelector('.empty-table');
    if (emptyRow) {
        emptyRow.parentElement.remove();
    }

    const row = document.createElement('tr');
    row.className = `row-${data.status.toLowerCase()}`;

    const statusClass = data.status.toLowerCase();
    const anomalyHtml = data.is_anomaly
        ? '<span class="anomaly-dot" title="Anomaly detected"></span>'
        : '<span class="anomaly-none">—</span>';

    row.innerHTML = `
        <td>${formatTime(data.timestamp)}</td>
        <td>${data.temp_internal.toFixed(1)}</td>
        <td>${data.temp_external.toFixed(1)}</td>
        <td>${data.humidity.toFixed(1)}</td>
        <td>${data.risk_score.toFixed(1)}</td>
        <td><span class="status-pill ${statusClass}">${data.status}</span></td>
        <td>${data.vvm_damage.toFixed(4)}</td>
        <td>${anomalyHtml}</td>
    `;

    // Insert at top (newest first)
    tbody.insertBefore(row, tbody.firstChild);

    // Keep only last N rows
    while (tbody.children.length > MAX_TABLE_ROWS) {
        tbody.removeChild(tbody.lastChild);
    }

    // Add entrance animation
    row.style.opacity = '0';
    row.style.transform = 'translateY(-10px)';
    requestAnimationFrame(() => {
        row.style.transition = 'all 0.3s ease';
        row.style.opacity = '1';
        row.style.transform = 'translateY(0)';
    });
}

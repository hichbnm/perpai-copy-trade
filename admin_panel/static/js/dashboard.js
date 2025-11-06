// Dashboard data loader
let refreshInterval;

console.log('🚀 Dashboard.js loaded - Version 2.0');
console.log('📊 New features: Analytics, System Health, Active Trades, Risk Overview');

window.addEventListener('DOMContentLoaded', () => {
    console.log('✅ DOM loaded, starting data load...');
    loadDashboardData();
    // Auto-refresh every 30 seconds
    refreshInterval = setInterval(loadDashboardData, 30000);
});

async function loadDashboardData() {
    try {
        // Load statistics
        await loadStatistics();
        
        // Load users
        await loadUsers();
        
        // Load channels
        await loadChannels();
        
        // Load subscriptions
        await loadSubscriptions();
        
        // Load recent trades
        await loadTrades();
        
        // Load active trades
        await loadActiveTrades();
        
        // Load risk overview
        await loadRiskOverview();
    } catch (error) {
        console.error('Error loading dashboard data:', error);
    }
}

async function loadStatistics() {
    try {
        const response = await fetch('/api/bot_status');
        const data = await response.json();
        
        document.getElementById('stat-users').textContent = data.total_users || 0;
        document.getElementById('stat-subscriptions').textContent = data.total_subscriptions || 0;
        document.getElementById('stat-channels').textContent = data.total_channels || 0;
        document.getElementById('stat-trades').textContent = data.active_trades || 0;
        
        // Load analytics
        await loadAnalytics();
        
        // Load system health
        await loadSystemHealth();
    } catch (error) {
        console.error('Error loading statistics:', error);
    }
}

async function loadAnalytics() {
    try {
        const response = await fetch('/api/analytics/overview');
        const data = await response.json();
        
        if (data.last_30_days) {
            const metrics = data.last_30_days;
            
            // Update analytics cards
            document.getElementById('analytics-winrate').textContent = 
                metrics.win_rate ? `${metrics.win_rate.toFixed(1)}%` : '-';
            document.getElementById('analytics-pnl').textContent = 
                metrics.net_pnl ? `$${metrics.net_pnl.toFixed(2)}` : '$0';
            document.getElementById('analytics-pf').textContent = 
                metrics.profit_factor ? metrics.profit_factor.toFixed(2) : '-';
            document.getElementById('analytics-total').textContent = 
                metrics.total_trades || 0;
            
            console.log('📊 30-Day Analytics loaded successfully');
        }
    } catch (error) {
        console.error('Error loading analytics:', error);
    }
}

async function loadSystemHealth() {
    try {
        const response = await fetch('/api/system/health');
        const data = await response.json();
        
        // Update health cards
        document.getElementById('health-cpu').textContent = `${data.cpu_usage}%`;
        document.getElementById('health-memory').textContent = `${data.memory_usage}%`;
        document.getElementById('health-disk').textContent = `${data.disk_usage}%`;
        document.getElementById('health-uptime').textContent = data.uptime || '-';
        
        console.log('🖥️ System Health loaded successfully');
    } catch (error) {
        console.error('Error loading system health:', error);
    }
}

async function loadActiveTrades() {
    try {
        const response = await fetch('/api/trades/active');
        const data = await response.json();
        
        const container = document.getElementById('active-trades-container');
        
        if (!data.trades || data.trades.length === 0) {
            container.innerHTML = '<p style="text-align: center; color: #888;">No active trades</p>';
            return;
        }
        
        container.innerHTML = `
            <table>
                <thead>
                    <tr>
                        <th>Symbol</th>
                        <th>Side</th>
                        <th>Entry Price</th>
                        <th>Position Size</th>
                        <th>Leverage</th>
                        <th>TP</th>
                        <th>SL</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
                    ${data.trades.map(trade => `
                        <tr>
                            <td><strong>${escapeHtml(trade.symbol)}</strong></td>
                            <td><span class="badge ${trade.side === 'long' ? 'badge-success' : 'badge-danger'}">${trade.side.toUpperCase()}</span></td>
                            <td>$${parseFloat(trade.entry_price).toFixed(2)}</td>
                            <td>${trade.position_size}</td>
                            <td>${trade.leverage}x</td>
                            <td class="profit">$${parseFloat(trade.take_profit).toFixed(2)}</td>
                            <td class="loss">$${parseFloat(trade.stop_loss).toFixed(2)}</td>
                            <td><span class="badge badge-info">ACTIVE</span></td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;
        
        console.log(`🔥 Loaded ${data.trades.length} active trades`);
    } catch (error) {
        console.error('Error loading active trades:', error);
    }
}

async function loadRiskOverview() {
    try {
        const response = await fetch('/api/risk/overview');
        const data = await response.json();
        
        // Update risk cards
        document.getElementById('risk-exposure').textContent = 
            `$${data.total_exposure ? data.total_exposure.toFixed(2) : '0'}`;
        document.getElementById('risk-users').textContent = 
            data.by_user ? Object.keys(data.by_user).length : 0;
        document.getElementById('risk-symbols').textContent = 
            data.by_symbol ? Object.keys(data.by_symbol).length : 0;
        
        // Calculate average leverage
        let totalLeverage = 0;
        let count = 0;
        if (data.by_user) {
            Object.values(data.by_user).forEach(user => {
                if (user.avg_leverage) {
                    totalLeverage += user.avg_leverage;
                    count++;
                }
            });
        }
        document.getElementById('risk-leverage').textContent = 
            count > 0 ? `${(totalLeverage / count).toFixed(1)}x` : '-';
        
        console.log('⚠️ Risk Overview loaded successfully');
    } catch (error) {
        console.error('Error loading risk overview:', error);
    }
}

async function loadUsers() {
    try {
        const response = await fetch('/api/users');
        const data = await response.json();
        
        const tbody = document.getElementById('users-tbody');
        if (!data.users || data.users.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5">No users found</td></tr>';
            return;
        }
        
        tbody.innerHTML = data.users.map(user => `
            <tr>
                <td>${escapeHtml(user.username)}</td>
                <td><code>${escapeHtml(user.user_id)}</code></td>
                <td>${user.api_keys}</td>
                <td>${user.subscriptions}</td>
                <td>${formatDate(user.created_at)}</td>
            </tr>
        `).join('');
    } catch (error) {
        console.error('Error loading users:', error);
        document.getElementById('users-tbody').innerHTML = '<tr><td colspan="5">Error loading users</td></tr>';
    }
}

async function loadChannels() {
    try {
        const response = await fetch('/api/channels');
        const data = await response.json();
        
        const tbody = document.getElementById('channels-tbody');
        if (!data.channels || data.channels.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5">No channels found</td></tr>';
            return;
        }
        
        tbody.innerHTML = data.channels.map(channel => `
            <tr>
                <td>${escapeHtml(channel.channel_name)}</td>
                <td><code>${escapeHtml(channel.channel_id)}</code></td>
                <td>${channel.subscribers}</td>
                <td>${channel.is_signal_channel ? '✅' : '❌'}</td>
                <td>${formatDate(channel.created_at)}</td>
            </tr>
        `).join('');
    } catch (error) {
        console.error('Error loading channels:', error);
        document.getElementById('channels-tbody').innerHTML = '<tr><td colspan="5">Error loading channels</td></tr>';
    }
}

async function loadSubscriptions() {
    try {
        const response = await fetch('/api/subscriptions');
        const data = await response.json();
        
        const tbody = document.getElementById('subscriptions-tbody');
        if (!data.subscriptions || data.subscriptions.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7">No subscriptions found</td></tr>';
            return;
        }
        
        tbody.innerHTML = data.subscriptions.map(sub => `
            <tr>
                <td>${escapeHtml(sub.username)}</td>
                <td>${escapeHtml(sub.channel_name)}</td>
                <td>${escapeHtml(sub.exchange)}</td>
                <td>${escapeHtml(sub.position_mode)}</td>
                <td>${sub.position_size}</td>
                <td>${sub.max_risk}%</td>
                <td>${formatDate(sub.created_at)}</td>
            </tr>
        `).join('');
    } catch (error) {
        console.error('Error loading subscriptions:', error);
        document.getElementById('subscriptions-tbody').innerHTML = '<tr><td colspan="7">Error loading subscriptions</td></tr>';
    }
}

async function loadTrades() {
    try {
        const response = await fetch('/api/trades?limit=50');
        const data = await response.json();
        
        const tbody = document.getElementById('trades-tbody');
        if (!data.trades || data.trades.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8">No trades found</td></tr>';
            return;
        }
        
        tbody.innerHTML = data.trades.map(trade => {
            const pnlClass = trade.pnl > 0 ? 'pnl-positive' : trade.pnl < 0 ? 'pnl-negative' : '';
            return `
                <tr>
                    <td>${escapeHtml(trade.username)}</td>
                    <td>${escapeHtml(trade.symbol)}</td>
                    <td class="side-${trade.side.toLowerCase()}">${escapeHtml(trade.side)}</td>
                    <td>${trade.entry_price ? trade.entry_price.toFixed(4) : '-'}</td>
                    <td>${trade.quantity ? trade.quantity.toFixed(4) : '-'}</td>
                    <td>${escapeHtml(trade.status)}</td>
                    <td class="${pnlClass}">${trade.pnl ? trade.pnl.toFixed(2) : '-'}</td>
                    <td>${formatDate(trade.created_at)}</td>
                </tr>
            `;
        }).join('');
    } catch (error) {
        console.error('Error loading trades:', error);
        document.getElementById('trades-tbody').innerHTML = '<tr><td colspan="8">Error loading trades</td></tr>';
    }
}

// Utility functions
function escapeHtml(text) {
    if (text === null || text === undefined) return '';
    const div = document.createElement('div');
    div.textContent = text.toString();
    return div.innerHTML;
}

function formatDate(dateString) {
    if (!dateString) return '-';
    const date = new Date(dateString);
    return date.toLocaleString();
}

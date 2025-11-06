// Trades Page JS
let tradesData = [];

async function loadTrades() {
    try {
        const response = await fetch('/api/trades?limit=100', {
            credentials: 'include', // Important for session cookies
            headers: {
                'Accept': 'application/json'
            }
        });
        
        if (!response.ok) {
            if (response.status === 401) {
                console.log('Not authenticated, redirecting to login');
                window.location.href = '/login';
                return;
            }
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const data = await response.json();
        
        console.log('Trades API response:', data);
        console.log('Response status:', response.status);
        
        tradesData = data.trades || [];
        
        // Show debug info if available
        if (data.total_count !== undefined) {
            console.log(`Total trades in database: ${data.total_count}`);
            console.log(`Returned trades: ${data.count}`);
        }
        
        if (data.error) {
            console.error('API Error:', data.error);
        }
        
        if (tradesData.length === 0) {
            console.warn('No trades returned. Checking authentication...');
        }
        
        renderTrades(tradesData);
    } catch (error) {
        console.error('Error loading trades:', error);
        document.getElementById('trades-tbody').innerHTML = 
            '<tr><td colspan="9" style="text-align:center; color: var(--danger);">Error loading trades: ' + error.message + '</td></tr>';
    }
}

function renderTrades(trades) {
    const tbody = document.getElementById('trades-tbody');
    
    console.log('renderTrades called with:', trades);
    
    if (!trades || trades.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;">No trades found</td></tr>';
        return;
    }
    
    tbody.innerHTML = trades.map(trade => {
        const pnlClass = trade.pnl > 0 ? 'pnl-positive' : trade.pnl < 0 ? 'pnl-negative' : '';
        const sideClass = (trade.side && trade.side.toLowerCase() === 'long') || trade.side === 'BUY' ? 'side-long' : 'side-short';
        
        // Use price if entry_price is null
        const displayPrice = trade.entry_price || trade.price || 0;
        
        return `
            <tr>
                <td><strong>${escapeHtml(trade.username || 'Unknown')}</strong></td>
                <td>${escapeHtml(trade.symbol || 'N/A')}</td>
                <td><span class="${sideClass}">${escapeHtml(trade.side || 'UNKNOWN')}</span></td>
                <td>${displayPrice ? displayPrice.toFixed(4) : '-'}</td>
                <td>${trade.quantity ? trade.quantity.toFixed(4) : '-'}</td>
                <td><span class="badge">${escapeHtml(trade.status || 'unknown')}</span></td>
                <td class="${pnlClass}"><strong>${trade.pnl !== null && trade.pnl !== undefined ? trade.pnl.toFixed(2) : '0.00'}</strong></td>
                <td>${formatDate(trade.created_at)}</td>
                <td>
                    <button class="btn-icon" title="View Details" onclick="viewTradeDetails(${trade.id})">👁️</button>
                </td>
            </tr>
        `;
    }).join('');
    
    console.log(`Rendered ${trades.length} trades successfully`);
}

// Filter functionality
document.addEventListener('DOMContentLoaded', () => {
    loadTrades();
    
    const statusFilter = document.getElementById('filter-status');
    const sideFilter = document.getElementById('filter-side');
    
    const applyFilters = () => {
        let filtered = tradesData;
        
        const statusValue = statusFilter?.value;
        if (statusValue && statusValue !== 'all') {
            filtered = filtered.filter(t => t.status.toLowerCase() === statusValue);
        }
        
        const sideValue = sideFilter?.value;
        if (sideValue && sideValue !== 'all') {
            filtered = filtered.filter(t => t.side.toLowerCase() === sideValue);
        }
        
        renderTrades(filtered);
    };
    
    statusFilter?.addEventListener('change', applyFilters);
    sideFilter?.addEventListener('change', applyFilters);
});

function exportTrades() {
    // Convert trades to CSV
    const headers = ['Username', 'Symbol', 'Side', 'Entry Price', 'Quantity', 'Status', 'PnL', 'Created'];
    const rows = tradesData.map(t => [
        t.username,
        t.symbol,
        t.side,
        t.entry_price || '',
        t.quantity || '',
        t.status,
        t.pnl || '',
        t.created_at
    ]);
    
    const csv = [headers, ...rows].map(row => row.join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `trades_${new Date().toISOString()}.csv`;
    a.click();
}

function viewTradeDetails(tradeId) {
    const trade = tradesData.find(t => t.id === tradeId);
    if (!trade) {
        console.error('Trade not found:', tradeId);
        showToast('Trade not found', 'error');
        return;
    }
    
    showTradeDetailsModal(trade);
}

function showTradeDetailsModal(trade) {
    const modal = document.getElementById('tradeDetailsModal');
    if (!modal) {
        console.error('Trade details modal not found');
        return;
    }
    
    // Populate modal content
    document.getElementById('detail-username').textContent = trade.username || 'Unknown';
    document.getElementById('detail-symbol').textContent = trade.symbol || 'N/A';
    document.getElementById('detail-side').textContent = trade.side || 'UNKNOWN';
    document.getElementById('detail-side').className = `badge ${(trade.side && trade.side.toLowerCase() === 'long') || trade.side === 'BUY' ? 'side-long' : 'side-short'}`;
    
    const displayPrice = trade.entry_price || trade.price || 0;
    document.getElementById('detail-entry-price').textContent = displayPrice ? displayPrice.toFixed(4) : '-';
    document.getElementById('detail-quantity').textContent = trade.quantity ? trade.quantity.toFixed(4) : '-';
    document.getElementById('detail-status').textContent = trade.status || 'unknown';
    document.getElementById('detail-status').className = `badge status-${trade.status || 'unknown'}`;
    
    const pnl = trade.pnl !== null && trade.pnl !== undefined ? trade.pnl.toFixed(2) : '0.00';
    document.getElementById('detail-pnl').textContent = pnl;
    document.getElementById('detail-pnl').className = `pnl ${trade.pnl > 0 ? 'pnl-positive' : trade.pnl < 0 ? 'pnl-negative' : ''}`;
    
    document.getElementById('detail-created').textContent = formatDate(trade.created_at);
    document.getElementById('detail-exchange').textContent = trade.exchange || 'N/A';
    document.getElementById('detail-stop-loss').textContent = trade.stop_loss ? trade.stop_loss.toFixed(4) : 'Not Set';
    document.getElementById('detail-take-profit').textContent = trade.take_profit || 'Not Set';
    document.getElementById('detail-message-id').textContent = trade.message_id || 'N/A';
    
    // Show modal
    modal.style.display = 'block';
}

function closeTradeDetailsModal() {
    const modal = document.getElementById('tradeDetailsModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

function escapeHtml(text) {
    if (text === null || text === undefined) return '';
    const div = document.createElement('div');
    div.textContent = text.toString();
    return div.innerHTML;
}

function formatDate(dateString) {
    if (!dateString) return '-';
    try {
        const date = new Date(dateString);
        return date.toLocaleString();
    } catch (e) {
        return dateString; // Return original if parsing fails
    }
}

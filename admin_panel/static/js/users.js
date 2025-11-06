// User management JavaScript - Updated API endpoints
let usersData = [];
let currentUser = null;
let currentApiKeys = [];
let deleteTarget = null;

function showToast(message, type = 'success') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    
    const icon = type === 'success' ? '✅' : type === 'error' ? '❌' : 'ℹ️';
    toast.innerHTML = `
        <span class="toast-icon">${icon}</span>
        <span class="toast-message">${message}</span>
        <button class="toast-close" onclick="this.parentElement.remove()">×</button>
    `;
    
    container.appendChild(toast);
    setTimeout(() => toast.classList.add('toast-show'), 10);
    
    setTimeout(() => {
        toast.classList.remove('toast-show');
        setTimeout(() => toast.remove(), 300);
    }, 5000);
}

async function loadUsers() {
    try {
        const response = await fetch('/api/users');
        const data = await response.json();
        usersData = data.users || [];
        renderUsers(usersData);
    } catch (error) {
        console.error('Error loading users:', error);
        document.getElementById('users-tbody').innerHTML =
            '<tr><td colspan="6" style="text-align:center; color: var(--danger);">❌ Error loading users</td></tr>';
    }
}

function renderUsers(users) {
    const tbody = document.getElementById('users-tbody');
    if (users.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;">No users found</td></tr>';
        return;
    }

    tbody.innerHTML = users.map(user => `
        <tr ${user.is_banned ? 'style="opacity: 0.6; background: rgba(255, 59, 92, 0.1);"' : ''}>
            <td>
                ${user.username}
                ${user.is_banned ? '<span class="badge" style="background: var(--danger); margin-left: 8px;">🚫 BANNED</span>' : ''}
            </td>
            <td><code>${user.user_id}</code></td>
            <td>
                <span class="badge" style="background: var(--success);">
                    ${user.api_keys || 0} keys
                </span>
            </td>
            <td>
                <span class="badge" style="background: var(--info);">
                    ${user.subscriptions || 0} subs
                </span>
            </td>
            <td>${new Date(user.created_at).toLocaleDateString()}</td>
            <td>
                <button class="btn-small btn-primary" onclick="showUserDetails('${user.user_id}')">
                    👁️ View
                </button>
                ${user.is_banned 
                    ? `<button class="btn-small btn-success" onclick="unbanUser('${user.user_id}', '${user.username}')" style="margin-left: 4px;">
                        ✅ Unban
                    </button>`
                    : `<button class="btn-small btn-danger" onclick="banUser('${user.user_id}', '${user.username}')" style="margin-left: 4px;">
                        🚫 Ban
                    </button>`
                }
            </td>
        </tr>
    `).join('');
}

async function showUserDetails(userId) {
    currentUser = usersData.find(u => u.user_id === userId);
    if (!currentUser) return;

    // Fill user details
    document.getElementById('detail-username').textContent = currentUser.username;
    document.getElementById('detail-userid').textContent = currentUser.user_id;
    document.getElementById('detail-joined').textContent = new Date(currentUser.created_at).toLocaleString();
    document.getElementById('detail-subs').textContent = currentUser.subscriptions || 0;

    // Load API keys
    await loadUserApiKeys(userId);

    // Show modal
    document.getElementById('userModal').style.display = 'block';
}

async function loadUserApiKeys(userId) {
    try {
        const response = await fetch(`/api/users/${userId}/api-keys`);
        const data = await response.json();
        currentApiKeys = data.api_keys || [];

        renderApiKeys(currentApiKeys);
    } catch (error) {
        console.error('Error loading API keys:', error);
        document.getElementById('apiKeysList').innerHTML =
            '<p style="color: var(--danger);">❌ Error loading API keys</p>';
    }
}

function renderApiKeys(apiKeys) {
    const container = document.getElementById('apiKeysList');

    if (apiKeys.length === 0) {
        container.innerHTML = '<p style="color: var(--text-secondary);">No API keys configured</p>';
        return;
    }

    container.innerHTML = `
        <div class="api-keys-grid">
            ${apiKeys.map(key => `
                <div class="api-key-card">
                    <div class="api-key-header">
                        <h4>${key.exchange.toUpperCase()}</h4>
                        <span class="badge ${key.testnet ? 'badge-warning' : 'badge-success'}">
                            ${key.testnet ? 'TESTNET' : 'MAINNET'}
                        </span>
                    </div>
                    <div class="api-key-details">
                        <div class="api-key-field">
                            <label>API Key:</label>
                            <code>${maskApiKey(key.api_key)}</code>
                        </div>
                        <div class="api-key-field">
                            <label>Added:</label>
                            <span>${new Date(key.created_at).toLocaleDateString()}</span>
                        </div>
                    </div>
                    <div class="api-key-actions">
                        <button class="btn-small btn-secondary" onclick="editApiKey('${key.exchange}')">
                            ✏️ Edit
                        </button>
                        <button class="btn-small btn-danger" onclick="deleteApiKey('${key.exchange}')">
                            🗑️ Delete
                        </button>
                    </div>
                </div>
            `).join('')}
        </div>
    `;
}

function maskApiKey(apiKey) {
    if (!apiKey || apiKey.length < 8) return apiKey;
    return apiKey.substring(0, 4) + '****' + apiKey.substring(apiKey.length - 4);
}

function editApiKey(exchange) {
    const apiKey = currentApiKeys.find(k => k.exchange === exchange);
    if (!apiKey) return;

    document.getElementById('edit-user-id').value = currentUser.user_id;
    document.getElementById('edit-exchange').value = exchange;
    document.getElementById('edit-exchange-display').value = exchange.toUpperCase();
    document.getElementById('edit-api-key').value = apiKey.api_key;
    document.getElementById('edit-api-secret').value = ''; // Don't pre-fill secret for security
    document.getElementById('edit-testnet').checked = apiKey.testnet;

    document.getElementById('editApiKeyModal').style.display = 'block';
}

async function saveApiKey() {
    const userId = document.getElementById('edit-user-id').value;
    const exchange = document.getElementById('edit-exchange').value;
    const apiKey = document.getElementById('edit-api-key').value.trim();
    const apiSecret = document.getElementById('edit-api-secret').value.trim();
    const testnet = document.getElementById('edit-testnet').checked;

    if (!apiKey) {
        alert('API Key is required');
        return;
    }

    try {
        const response = await fetch(`/api/users/${userId}/api-keys/${exchange}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                api_key: apiKey,
                api_secret: apiSecret,
                testnet: testnet
            })
        });

        if (response.ok) {
            alert('✅ API Key updated successfully');
            closeModal('editApiKeyModal');
            await loadUserApiKeys(userId);
            await loadUsers(); // Refresh user list
        } else {
            const error = await response.json();
            alert(`❌ Error: ${error.detail || 'Failed to update API key'}`);
        }
    } catch (error) {
        console.error('Error saving API key:', error);
        alert('❌ Error saving API key');
    }
}

function deleteApiKey(exchange) {
    const apiKey = currentApiKeys.find(k => k.exchange === exchange);
    if (!apiKey) return;

    deleteTarget = { userId: currentUser.user_id, exchange: exchange };
    document.getElementById('delete-confirm-text').textContent =
        `Delete ${exchange.toUpperCase()} API key for user ${currentUser.username}?`;

    document.getElementById('deleteModal').style.display = 'block';
}

async function confirmDelete() {
    if (!deleteTarget) return;

    try {
        const response = await fetch(`/api/users/${deleteTarget.userId}/api-keys/${deleteTarget.exchange}`, {
            method: 'DELETE'
        });

        if (response.ok) {
            alert('✅ API Key deleted successfully');
            closeModal('deleteModal');
            await loadUserApiKeys(deleteTarget.userId);
            await loadUsers(); // Refresh user list
            deleteTarget = null;
        } else {
            const error = await response.json();
            alert(`❌ Error: ${error.detail || 'Failed to delete API key'}`);
        }
    } catch (error) {
        console.error('Error deleting API key:', error);
        alert('❌ Error deleting API key');
    }
}

function showBanConfirmation(userId, username) {
    // Remove any existing ban modals first
    closeBanModal();
    
    // Create unique function names with timestamp to avoid conflicts
    const timestamp = Date.now();
    const closeFuncName = `closeBanModal_${timestamp}`;
    const confirmFuncName = `confirmBan_${timestamp}`;
    
    // Create direct global functions BEFORE creating the modal
    window[closeFuncName] = function() {
        console.log('Direct ban modal close called');
        const modal = document.getElementById('banConfirmModal');
        if (modal) modal.remove();
        // Clean up functions
        delete window[closeFuncName];
        delete window[confirmFuncName];
    };
    
    window[confirmFuncName] = function() {
        console.log('Direct ban confirm called for:', username);
        const modal = document.getElementById('banConfirmModal');
        if (modal) modal.remove();
        // Clean up functions
        delete window[closeFuncName];
        delete window[confirmFuncName];
        confirmBan(userId, username);
    };
    
    const modal = document.createElement('div');
    modal.className = 'modal';
    modal.style.display = 'block';
    modal.id = 'banConfirmModal';
    
    // Add click-outside-to-close functionality
    modal.addEventListener('click', function(e) {
        if (e.target === modal) {
            window[closeFuncName]();
        }
    });
    
    modal.innerHTML = `
        <div class="modal-content" style="max-width: 500px;">
            <div class="modal-header">
                <h2>⚠️ Confirm Ban Action</h2>
            </div>
            <div class="modal-body">
                <p><strong>Ban user "${username}"?</strong></p>
                <div style="background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 6px; margin: 15px 0;">
                    <p style="margin: 0; color: #856404;"><strong>This will:</strong></p>
                    <ul style="margin: 10px 0 0 20px; color: #856404;">
                        <li>Prevent them from using the bot</li>
                        <li>Block all trading commands</li>
                        <li>Skip them in trade execution</li>
                    </ul>
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn-secondary" onclick="window.${closeFuncName}(); return false;">Cancel</button>
                <button class="btn-danger" onclick="window.${confirmFuncName}(); return false;">🚫 Yes, Ban User</button>
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
}

async function confirmBan(userId, username) {
    // Close the confirmation modal first
    closeBanModal();
    
    try {
        const response = await fetch(`/api/users/${userId}/ban`, {
            method: 'POST'
        });

        const data = await response.json();

        if (data.success) {
            showToast(`✅ User "${username}" banned successfully`, 'success');
            await loadUsers(); // Reload to show updated status
        } else {
            showToast(`❌ ${data.error || 'Failed to ban user'}`, 'error');
        }
    } catch (error) {
        console.error('Error banning user:', error);
        showToast('❌ Error banning user', 'error');
    }
}

function closeBanModal() {
    console.log('closeBanModal called');
    
    // Remove by ID first - immediate removal
    const modal = document.getElementById('banConfirmModal');
    if (modal) {
        console.log('Found ban modal by ID, removing...');
        modal.remove();
        return;
    }
    
    // Fallback: remove any modal containing ban confirmation
    const allModals = document.querySelectorAll('.modal');
    allModals.forEach(m => {
        if (m.innerHTML && m.innerHTML.includes('Confirm Ban Action')) {
            console.log('Found ban modal by content, removing...');
            m.remove();
        }
    });
}

async function banUser(userId, username) {
    showBanConfirmation(userId, username);
}

function showUnbanConfirmation(userId, username) {
    // Remove any existing unban modals first
    closeUnbanModal();
    
    // Create unique function names with timestamp to avoid conflicts
    const timestamp = Date.now();
    const closeFuncName = `closeUnbanModal_${timestamp}`;
    const confirmFuncName = `confirmUnban_${timestamp}`;
    
    // Create direct global functions BEFORE creating the modal
    window[closeFuncName] = function() {
        console.log('Direct unban modal close called');
        const modal = document.getElementById('unbanConfirmModal');
        if (modal) modal.remove();
        // Clean up functions
        delete window[closeFuncName];
        delete window[confirmFuncName];
    };
    
    window[confirmFuncName] = function() {
        console.log('Direct unban confirm called for:', username);
        const modal = document.getElementById('unbanConfirmModal');
        if (modal) modal.remove();
        // Clean up functions
        delete window[closeFuncName];
        delete window[confirmFuncName];
        confirmUnban(userId, username);
    };
    
    const modal = document.createElement('div');
    modal.className = 'modal';
    modal.style.display = 'block';
    modal.id = 'unbanConfirmModal';
    
    // Add click-outside-to-close functionality
    modal.addEventListener('click', function(e) {
        if (e.target === modal) {
            window[closeFuncName]();
        }
    });
    
    modal.innerHTML = `
        <div class="modal-content" style="max-width: 500px;">
            <div class="modal-header">
                <h2>✅ Confirm Unban Action</h2>
            </div>
            <div class="modal-body">
                <p><strong>Unban user "${username}"?</strong></p>
                <div style="background: #d1ecf1; border: 1px solid #bee5eb; padding: 15px; border-radius: 6px; margin: 15px 0;">
                    <p style="margin: 0; color: #0c5460;"><strong>This will:</strong></p>
                    <ul style="margin: 10px 0 0 20px; color: #0c5460;">
                        <li>Allow them to use the bot again</li>
                        <li>Restore access to all commands</li>
                        <li>Include them in trade execution</li>
                    </ul>
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn-secondary" onclick="window.${closeFuncName}(); return false;">Cancel</button>
                <button class="btn-success" onclick="window.${confirmFuncName}(); return false;">✅ Yes, Unban User</button>
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
}

async function confirmUnban(userId, username) {
    // Close the confirmation modal first
    closeUnbanModal();
    
    try {
        const response = await fetch(`/api/users/${userId}/unban`, {
            method: 'POST'
        });

        const data = await response.json();

        if (data.success) {
            showToast(`✅ User "${username}" unbanned successfully`, 'success');
            await loadUsers(); // Reload to show updated status
        } else {
            showToast(`❌ ${data.error || 'Failed to unban user'}`, 'error');
        }
    } catch (error) {
        console.error('Error unbanning user:', error);
        showToast('❌ Error unbanned user', 'error');
    }
}

function closeUnbanModal() {
    console.log('closeUnbanModal called');
    
    // Remove by ID first - immediate removal
    const modal = document.getElementById('unbanConfirmModal');
    if (modal) {
        console.log('Found unban modal by ID, removing...');
        modal.remove();
        return;
    }
    
    // Fallback: remove any modal containing unban confirmation
    const allModals = document.querySelectorAll('.modal');
    allModals.forEach(m => {
        if (m.innerHTML && m.innerHTML.includes('Confirm Unban Action')) {
            console.log('Found unban modal by content, removing...');
            m.remove();
        }
    });
}

async function unbanUser(userId, username) {
    showUnbanConfirmation(userId, username);
}

function closeModal(modalId) {
    document.getElementById(modalId).style.display = 'none';
    if (modalId === 'userModal') {
        currentUser = null;
        currentApiKeys = [];
    }
}

// Search functionality
document.getElementById('search-users').addEventListener('input', function(e) {
    const searchTerm = e.target.value.toLowerCase();
    const filteredUsers = usersData.filter(user =>
        user.username.toLowerCase().includes(searchTerm) ||
        user.user_id.toLowerCase().includes(searchTerm)
    );
    renderUsers(filteredUsers);
});

// Add ESC key functionality to close modals
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        closeBanModal();
        closeUnbanModal();
    }
});

// Load users on page load
document.addEventListener('DOMContentLoaded', loadUsers);

// Ban/Unban all users
async function banAllUsers() {
    if (!confirm(`⚠️ Ban ALL ${usersData.length} users?\n\nThis will prevent all users from trading. Are you sure?`)) {
        return;
    }
    
    try {
        const response = await fetch('/api/users/ban-all', {
            method: 'POST'
        });
        const result = await response.json();
        
        if (result.success) {
            showToast(`✅ Successfully banned ${result.banned_count} users`, 'success');
            loadUsers(); // Refresh the list
        } else {
            showToast('❌ Error: ' + (result.error || 'Failed to ban users'), 'error');
        }
    } catch (error) {
        console.error('Error banning all users:', error);
        showToast('❌ Error banning users', 'error');
    }
}

async function unbanAllUsers() {
    if (!confirm(`✅ Unban ALL users?\n\nThis will allow all users to trade again. Are you sure?`)) {
        return;
    }
    
    try {
        const response = await fetch('/api/users/unban-all', {
            method: 'POST'
        });
        const result = await response.json();
        
        if (result.success) {
            showToast(`✅ Successfully unbanned ${result.unbanned_count} users`, 'success');
            loadUsers(); // Refresh the list
        } else {
            showToast('❌ Error: ' + (result.error || 'Failed to unban users'), 'error');
        }
    } catch (error) {
        console.error('Error unbanning all users:', error);
        showToast('❌ Error unbanning users', 'error');
    }
}

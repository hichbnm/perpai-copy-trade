// Channels Page JS
let channelsData = [];
let currentChannel = null;
let deleteTarget = null;

// Toast Notification System
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

async function loadChannels() {
    try {
        const response = await fetch('/api/channels');
        const data = await response.json();
        channelsData = data.channels || [];
        renderChannels(channelsData);
    } catch (error) {
        console.error('Error loading channels:', error);
        showToast('Failed to load channels', 'error');
        document.getElementById('channels-tbody').innerHTML = 
            '<tr><td colspan="6" style="text-align:center; color: var(--danger);">Error loading channels</td></tr>';
    }
}

function renderChannels(channels) {
    const tbody = document.getElementById('channels-tbody');
    if (!channels || channels.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;">No channels found</td></tr>';
        return;
    }
    
    tbody.innerHTML = channels.map(channel => `
        <tr>
            <td><strong>${escapeHtml(channel.channel_name)}</strong></td>
            <td><code>${escapeHtml(channel.channel_id)}</code></td>
            <td>
                <span class="badge" style="background: var(--info);">
                    ${channel.subscribers || 0} users
                </span>
            </td>
            <td>${channel.is_signal_channel ? '<span style="color: var(--green);">✅ Yes</span>' : '<span style="color: var(--text-secondary);">❌ No</span>'}</td>
            <td>${formatDate(channel.created_at)}</td>
            <td>
                <button class="btn-small btn-primary" onclick="showChannelDetails('${escapeHtml(channel.channel_id)}')">
                    👁️ View
                </button>
                <button class="btn-small btn-secondary" onclick="editChannel('${escapeHtml(channel.channel_id)}')">
                    ✏️ Edit
                </button>
                <button class="btn-small btn-danger" onclick="deleteChannel('${escapeHtml(channel.channel_id)}')">🗑️ Delete</button>
            </td>
        </tr>
    `).join('');
}

async function showChannelDetails(channelId) {
    currentChannel = channelsData.find(ch => ch.channel_id === channelId);
    if (!currentChannel) return;

    document.getElementById('detail-channel-name').textContent = currentChannel.channel_name;
    document.getElementById('detail-channel-id').textContent = currentChannel.channel_id;
    document.getElementById('detail-is-signal').innerHTML = currentChannel.is_signal_channel 
        ? '<span style="color: var(--success);">✅ Yes</span>' 
        : '<span style="color: var(--text-secondary);">❌ No</span>';
    document.getElementById('detail-subscribers').textContent = currentChannel.subscribers || 0;
    document.getElementById('detail-created').textContent = formatDate(currentChannel.created_at);

    await loadChannelSubscribers(channelId);
    document.getElementById('channelModal').style.display = 'block';
}

async function loadChannelSubscribers(channelId) {
    try {
        const response = await fetch(`/api/channels/${channelId}/subscribers`);
        const data = await response.json();
        const subscribers = data.subscribers || [];

        const container = document.getElementById('subscribersList');
        if (subscribers.length === 0) {
            container.innerHTML = '<p style="color: var(--text-secondary);">No subscribers</p>';
            return;
        }

        container.innerHTML = `
            <div class="subscribers-grid">
                ${subscribers.map(sub => `
                    <div class="subscriber-card">
                        <div class="subscriber-info">
                            <strong>${escapeHtml(sub.username)}</strong>
                            <code style="font-size: 0.85rem; color: var(--text-secondary);">${escapeHtml(sub.user_id)}</code>
                        </div>
                        <div class="subscriber-meta">
                            <span class="badge badge-success">${escapeHtml(sub.exchange).toUpperCase()}</span>
                            <span style="font-size: 0.85rem; color: var(--text-secondary);">
                                Joined: ${formatDate(sub.created_at)}
                            </span>
                        </div>
                    </div>
                `).join('')}
            </div>
        `;
    } catch (error) {
        console.error('Error loading subscribers:', error);
        showToast('Failed to load subscribers', 'error');
        document.getElementById('subscribersList').innerHTML = 
            '<p style="color: var(--danger);">Error loading subscribers</p>';
    }
}

function editChannel(channelId) {
    currentChannel = channelsData.find(ch => ch.channel_id === channelId);
    if (!currentChannel) return;

    document.getElementById('edit-channel-id').value = currentChannel.channel_id;
    document.getElementById('edit-channel-name').value = currentChannel.channel_name;
    document.getElementById('edit-is-signal').checked = currentChannel.is_signal_channel;

    document.getElementById('editChannelModal').style.display = 'block';
}

async function saveChannel() {
    const channelId = document.getElementById('edit-channel-id').value;
    const channelName = document.getElementById('edit-channel-name').value.trim();
    const isSignal = document.getElementById('edit-is-signal').checked;

    if (!channelName) {
        showToast('Channel name is required', 'error');
        return;
    }

    try {
        const response = await fetch(`/api/channels/${channelId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                channel_name: channelName,
                is_signal_channel: isSignal
            })
        });

        const result = await response.json();

        if (response.ok && result.success) {
            showToast('Channel updated successfully!', 'success');
            closeModal('editChannelModal');
            await loadChannels();
        } else {
            showToast('Error: ' + (result.error || 'Failed to update channel'), 'error');
        }
    } catch (error) {
        console.error('Error saving channel:', error);
        showToast('Error saving channel', 'error');
    }
}

function deleteChannel(channelId) {
    const channel = channelsData.find(ch => ch.channel_id === channelId);
    if (!channel) return;

    deleteTarget = channelId;
    document.getElementById('delete-confirm-text').textContent = 
        `Channel: ${channel.channel_name} (${channel.subscribers || 0} subscribers)`;

    document.getElementById('deleteModal').style.display = 'block';
}

async function confirmDelete() {
    if (!deleteTarget) return;

    try {
        const response = await fetch(`/api/channels/${deleteTarget}`, {
            method: 'DELETE'
        });

        const result = await response.json();

        if (response.ok && result.success) {
            showToast('Channel deleted successfully!', 'success');
            closeModal('deleteModal');
            await loadChannels();
            deleteTarget = null;
        } else {
            showToast('Error: ' + (result.error || 'Failed to delete channel'), 'error');
        }
    } catch (error) {
        console.error('Error deleting channel:', error);
        showToast('Error deleting channel', 'error');
    }
}

function closeModal(modalId) {
    document.getElementById(modalId).style.display = 'none';
    if (modalId === 'channelModal') {
        currentChannel = null;
    }
}

// Filter functionality
document.addEventListener('DOMContentLoaded', () => {
    loadChannels();
    
    const filterSelect = document.getElementById('filter-type');
    filterSelect?.addEventListener('change', (e) => {
        const filterValue = e.target.value;
        let filtered = channelsData;
        
        if (filterValue === 'signal') {
            filtered = channelsData.filter(ch => ch.is_signal_channel);
        } else if (filterValue === 'inactive') {
            filtered = channelsData.filter(ch => !ch.is_signal_channel);
        }
        
        renderChannels(filtered);
    });
});

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

// Ban/Unban all subscribers in current channel
async function banAllSubscribers() {
    if (!currentChannel) return;
    
    if (!confirm(`Ban all ${currentChannel.subscriber_count} subscribers from channel "${currentChannel.channel_name}"?`)) {
        return;
    }
    
    try {
        const response = await fetch(`/api/channels/${currentChannel.channel_id}/ban-all`, {
            method: 'POST'
        });
        const result = await response.json();
        
        if (result.success) {
            showToast(`Successfully banned ${result.banned_count} users`, 'success');
            viewChannelDetails(currentChannel.channel_id); // Refresh
        } else {
            showToast('Error: ' + (result.error || 'Failed to ban users'), 'error');
        }
    } catch (error) {
        console.error('Error banning subscribers:', error);
        showToast('Error banning subscribers', 'error');
    }
}

async function unbanAllSubscribers() {
    if (!currentChannel) return;
    
    if (!confirm(`Unban all subscribers from channel "${currentChannel.channel_name}"?`)) {
        return;
    }
    
    try {
        const response = await fetch(`/api/channels/${currentChannel.channel_id}/unban-all`, {
            method: 'POST'
        });
        const result = await response.json();
        
        if (result.success) {
            showToast(`Successfully unbanned ${result.unbanned_count} users`, 'success');
            viewChannelDetails(currentChannel.channel_id); // Refresh
        } else {
            showToast('Error: ' + (result.error || 'Failed to unban users'), 'error');
        }
    } catch (error) {
        console.error('Error unbanning subscribers:', error);
        showToast('Error unbanning subscribers', 'error');
    }
}

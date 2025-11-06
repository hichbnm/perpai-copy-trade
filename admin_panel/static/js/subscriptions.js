// Subscriptions Page JS
let subscriptionsData = [];
let currentSubscription = null;
let deleteTarget = null;
let currentSearch = '';
let currentExchange = 'all';

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
  setTimeout(()=>toast.classList.add('toast-show'),10);
  setTimeout(()=>{ toast.classList.remove('toast-show'); setTimeout(()=>toast.remove(),300); },5000);
}

function formatDate(dt){
  if(!dt) return '-';
  try { return new Date(dt).toLocaleString(); } catch { return dt; }
}

async function loadSubscriptions(){
  const tbody = document.getElementById('subscriptions-tbody');
  try {
    const res = await fetch('/api/subscriptions');
    const data = await res.json();
    subscriptionsData = data.subscriptions || [];
    renderSubscriptions(subscriptionsData);
  } catch (e){
    console.error('Error loading subscriptions', e);
    if(tbody) tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--danger);">Error loading subscriptions</td></tr>';
    showToast('Failed to load subscriptions','error');
  }
}

function escapeHtml(str){
  if(str===null||str===undefined) return '';
  return String(str)
    .replace(/&/g,'&amp;')
    .replace(/</g,'&lt;')
    .replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;')
    .replace(/'/g,'&#39;');
}

function getDisplayPositionSize(sub) {
  if (!sub.position_mode) return escapeHtml(sub.position_size || '-');
  
  if (sub.position_mode === 'fixed') {
    const amount = sub.fixed_amount || sub.position_size || 0;
    return `$${amount}`;
  } else {
    const percentage = sub.percentage_of_balance || sub.position_size || 0;
    return `${percentage}%`;
  }
}

function renderSubscriptions(list){
  const tbody = document.getElementById('subscriptions-tbody');
  if(!tbody) return;
  if(!list.length){
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;">No subscriptions found</td></tr>';
    return;
  }
  tbody.innerHTML = list.map(sub => `
    <tr>
      <td><strong>${escapeHtml(sub.username)}</strong></td>
      <td>${escapeHtml(sub.channel_name)}</td>
      <td><span class="badge" style="background: var(--info);">${escapeHtml(sub.exchange || '-') }</span></td>
      <td>${escapeHtml(sub.position_mode || '-')}</td>
      <td>${getDisplayPositionSize(sub)}</td>
      <td>${sub.max_risk !== null && sub.max_risk !== undefined ? escapeHtml(sub.max_risk) : '-'}</td>
      <td>${formatDate(sub.created_at)}</td>
      <td>
        <button class="btn-small btn-primary" onclick="viewSubscription(${sub.id})">👁️ View</button>
        <button class="btn-small btn-danger" onclick="promptDelete(${sub.id})">🗑️ Delete</button>
      </td>
    </tr>`).join('');
}

function viewSubscription(id){
  currentSubscription = subscriptionsData.find(s=>s.id===id);
  if(!currentSubscription) return;
  document.getElementById('detail-username').textContent = currentSubscription.username || '-';
  document.getElementById('detail-channel').textContent = currentSubscription.channel_name || '-';
  document.getElementById('detail-exchange').textContent = currentSubscription.exchange || '-';
  document.getElementById('detail-position-mode').textContent = currentSubscription.position_mode || '-';
  
  // Display position size based on mode
  let displaySize = '-';
  if (currentSubscription.position_mode === 'fixed') {
    const amount = currentSubscription.fixed_amount || currentSubscription.position_size || 0;
    displaySize = `$${amount}`;
  } else if (currentSubscription.position_mode === 'percentage') {
    const percentage = currentSubscription.percentage_of_balance || currentSubscription.position_size || 0;
    displaySize = `${percentage}%`;
  } else {
    displaySize = currentSubscription.position_size ?? '-';
  }
  document.getElementById('detail-position-size').textContent = displaySize;
  document.getElementById('detail-max-risk').textContent = currentSubscription.max_risk ?? '-';
  document.getElementById('detail-created').textContent = formatDate(currentSubscription.created_at);
  document.getElementById('subscriptionModal').style.display='block';
}

function openEditModal(){
  if(!currentSubscription) return;
  document.getElementById('edit-position-mode').value = currentSubscription.position_mode || 'percentage';
  
  // Load the correct position size value based on mode
  if (currentSubscription.position_mode === 'fixed') {
    document.getElementById('edit-position-size').value = currentSubscription.fixed_amount || currentSubscription.position_size || '';
  } else {
    document.getElementById('edit-position-size').value = currentSubscription.percentage_of_balance || currentSubscription.position_size || '';
  }
  document.getElementById('edit-max-risk').value = currentSubscription.max_risk || '';
  document.getElementById('subscriptionModal').style.display='none';
  document.getElementById('editSubscriptionModal').style.display='block';
}

async function saveSubscriptionEdit(){
  if(!currentSubscription) return;
  const positionMode = document.getElementById('edit-position-mode').value;
  const positionSize = parseFloat(document.getElementById('edit-position-size').value);
  const maxRisk = parseFloat(document.getElementById('edit-max-risk').value);
  
  if(isNaN(positionSize) || positionSize <= 0){
    showToast('Invalid position size','error');
    return;
  }
  if(isNaN(maxRisk) || maxRisk <= 0 || maxRisk > 100){
    showToast('Max risk must be between 0 and 100','error');
    return;
  }
  
  try {
    const res = await fetch(`/api/subscriptions/${currentSubscription.id}`, {
      method: 'PUT',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        position_mode: positionMode,
        position_size: positionSize,
        max_risk: maxRisk
      })
    });
    const data = await res.json();
    if(res.ok && data.success){
      showToast('Subscription updated successfully!','success');
      closeModal('editSubscriptionModal');
      await loadSubscriptions();
      currentSubscription = null;
    } else {
      showToast('Error: ' + (data.error || 'Failed to update'),'error');
    }
  } catch(e){
    console.error('Error updating subscription', e);
    showToast('Error updating subscription','error');
  }
}

function promptDelete(id){
  deleteTarget = id;
  const sub = subscriptionsData.find(s=>s.id===id);
  document.getElementById('delete-confirm-text').textContent = sub ? `${sub.username} → ${sub.channel_name}` : '';
  document.getElementById('deleteModal').style.display='block';
}

async function deleteSubscription(){
  if(!currentSubscription) return;
  deleteTarget = currentSubscription.id;
  document.getElementById('delete-confirm-text').textContent = `${currentSubscription.username} → ${currentSubscription.channel_name}`;
  document.getElementById('subscriptionModal').style.display='none';
  document.getElementById('deleteModal').style.display='block';
}

async function confirmDelete(){
  if(!deleteTarget) return;
  try {
    // Need user_id and channel_id for delete endpoint. Backend requires both.
    const sub = subscriptionsData.find(s=>s.id===deleteTarget);
    if(!sub){ showToast('Subscription missing','error'); return; }
    // We don't currently have user_id or channel_id in details; adjust backend or extend query.
    showToast('Delete endpoint needs user & channel IDs (not provided in current data)','error');
  } catch(e){
    console.error('Error deleting subscription', e);
    showToast('Error deleting subscription','error');
  }
}

function closeModal(id){
  const el = document.getElementById(id);
  if(el) el.style.display='none';
}

// Filter
function applyFilters(){
  const filtered = subscriptionsData.filter(s => {
    const matchesExchange = currentExchange==='all' || (s.exchange||'').toLowerCase()===currentExchange;
    if(!currentSearch) return matchesExchange;
    const hay = `${(s.username||'').toLowerCase()} ${(s.channel_name||'').toLowerCase()}`;
    return matchesExchange && hay.includes(currentSearch);
  });
  renderSubscriptions(filtered);
}

function handleExchangeChange(){
  const sel = document.getElementById('filter-exchange');
  currentExchange = sel ? sel.value.toLowerCase() : 'all';
  applyFilters();
}

function handleSearchInput(e){
  currentSearch = e.target.value.trim().toLowerCase();
  applyFilters();
}

document.addEventListener('DOMContentLoaded', ()=>{
  loadSubscriptions();
  const sel = document.getElementById('filter-exchange');
  sel && sel.addEventListener('change', handleExchangeChange);
  const search = document.getElementById('filter-search');
  search && search.addEventListener('input', handleSearchInput);
});

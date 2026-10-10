/**
 * Admin Dashboard JavaScript
 * Handles tab switching, order status updates, ticket management, and notifications
 */

// ============================================================================
// Tab Switching Functionality
// ============================================================================

/**
 * Initialize tab switching functionality
 * Handles switching between Orders and Tickets sections
 */
function initTabSwitching() {
  document.querySelectorAll('.admin-tabs .tab').forEach(tab => {
    tab.addEventListener('click', () => {
      const targetTab = tab.dataset.tab;
      switchTab(targetTab);
    });
  });

  // Restore active tab from localStorage on page load
  restoreActiveTab();
}

/**
 * Switch to a specific tab
 * @param {string} tabName - Name of the tab to switch to ('orders' or 'tickets')
 */
function switchTab(tabName) {
  // Update active tab button
  document.querySelectorAll('.admin-tabs .tab').forEach(t => t.classList.remove('active'));
  const targetTabButton = document.querySelector(`.admin-tabs .tab[data-tab="${tabName}"]`);
  if (targetTabButton) {
    targetTabButton.classList.add('active');
  }
  
  // Update active content section
  document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
  const targetSection = document.getElementById(`${tabName}-section`);
  if (targetSection) {
    targetSection.classList.add('active');
  }
  
  // Store active tab in localStorage for persistence
  localStorage.setItem('adminActiveTab', tabName);
}

/**
 * Restore the previously active tab from localStorage
 */
function restoreActiveTab() {
  const savedTab = localStorage.getItem('adminActiveTab');
  if (savedTab) {
    switchTab(savedTab);
  }
}

// ============================================================================
// Order Status Management
// ============================================================================

/**
 * Update order status via API
 * @param {number} ordId - Order ID to update
 * @param {string} newStatus - New status value
 */
async function updateOrderStatus(ordId, newStatus) {
  try {
    const response = await fetch('/admin/update_status', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        ord_id: ordId,
        new_status: newStatus
      })
    });

    const data = await response.json();

    if (response.ok && data.ok) {
      showNotification(`Order #${ordId} updated to ${newStatus}`, 'success');
      // Reload page after short delay to show updated status
      setTimeout(() => location.reload(), 1000);
    } else {
      showNotification(data.error || 'Failed to update order status', 'error');
    }
  } catch (error) {
    console.error('Error updating order status:', error);
    showNotification('Network error. Please try again.', 'error');
  }
}

/**
 * Initialize event listeners for order status update buttons
 */
function initOrderStatusButtons() {
  document.querySelectorAll('.order-card .btn-status').forEach(button => {
    button.addEventListener('click', () => {
      const card = button.closest('.order-card');
      const ordId = parseInt(card.dataset.ordId);
      const newStatus = button.dataset.nextStatus;
      
      if (confirm(`Update order #${ordId} to ${newStatus}?`)) {
        updateOrderStatus(ordId, newStatus);
      }
    });
  });
}

// ============================================================================
// Ticket Status Management
// ============================================================================

/**
 * Update ticket status via API
 * @param {number} ticketId - Ticket ID to update
 * @param {string} newStatus - New status value
 * @param {string} [response] - Optional response text to include
 */
async function updateTicketStatus(ticketId, newStatus, response = null) {
  try {
    const payload = {
      ticket_id: ticketId,
      new_status: newStatus
    };
    
    if (response) {
      payload.response = response;
    }

    const apiResponse = await fetch('/admin/update_ticket_status', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload)
    });

    const data = await apiResponse.json();

    if (apiResponse.ok && data.ok) {
      const message = response 
        ? 'Response sent successfully' 
        : `Ticket #${ticketId} updated to ${newStatus}`;
      showNotification(message, 'success');
      // Reload page after short delay to show updated status
      setTimeout(() => location.reload(), 1000);
    } else {
      console.error('API Error:', apiResponse.status, data);
      const errorMsg = data.error || 'Failed to update ticket status';
      showNotification(errorMsg, 'error');
    }
  } catch (error) {
    console.error('Error updating ticket status:', error);
    showNotification('Network error. Please try again.', 'error');
  }
}

/**
 * Submit a response to a ticket
 * Automatically updates ticket status to "In Progress" if currently "Open"
 * @param {number} ticketId - Ticket ID to respond to
 */
async function submitTicketResponse(ticketId) {
  const responseTextarea = document.getElementById(`response-${ticketId}`);
  
  if (!responseTextarea) {
    showNotification('Response field not found', 'error');
    return;
  }
  
  const responseText = responseTextarea.value.trim();
  
  if (!responseText) {
    showNotification('Please enter a response', 'error');
    return;
  }

  // Submit response with status update to "In Progress"
  await updateTicketStatus(ticketId, 'In Progress', responseText);
}

/**
 * Initialize event listeners for ticket action buttons
 */
function initTicketActionButtons() {
  // Handle "Send Response" buttons
  document.querySelectorAll('.btn-respond').forEach(button => {
    // Remove any existing listeners by cloning
    const newButton = button.cloneNode(true);
    button.parentNode.replaceChild(newButton, button);
    
    newButton.addEventListener('click', () => {
      const ticketId = parseInt(newButton.dataset.ticketId);
      if (isNaN(ticketId)) {
        console.error('Invalid ticket ID:', newButton.dataset.ticketId);
        showNotification('Invalid ticket ID', 'error');
        return;
      }
      submitTicketResponse(ticketId);
    });
  });
  
  // Handle status update buttons
  document.querySelectorAll('.ticket-actions .btn-status').forEach(button => {
    // Remove any existing listeners by cloning
    const newButton = button.cloneNode(true);
    button.parentNode.replaceChild(newButton, button);
    
    newButton.addEventListener('click', () => {
      if (newButton.disabled) return;
      
      const ticketId = parseInt(newButton.dataset.ticketId);
      const newStatus = newButton.dataset.status;
      
      if (isNaN(ticketId)) {
        console.error('Invalid ticket ID:', newButton.dataset.ticketId);
        showNotification('Invalid ticket ID', 'error');
        return;
      }
      
      if (!newStatus) {
        console.error('Missing status:', newButton.dataset);
        showNotification('Invalid status', 'error');
        return;
      }
      
      if (confirm(`Update ticket #${ticketId} to ${newStatus}?`)) {
        updateTicketStatus(ticketId, newStatus);
      }
    });
  });
}

// Make functions available globally for backwards compatibility
window.submitResponse = submitTicketResponse;
window.updateTicketStatus = updateTicketStatus;

// ============================================================================
// Notification System
// ============================================================================

/**
 * Display a notification toast message
 * @param {string} message - Message to display
 * @param {string} type - Notification type ('success' or 'error')
 */
function showNotification(message, type = 'success') {
  const notification = document.getElementById('notification');
  
  if (!notification) {
    console.error('Notification element not found');
    return;
  }
  
  notification.textContent = message;
  notification.className = `notification ${type} show`;
  
  // Auto-hide notification after 3 seconds
  setTimeout(() => {
    notification.classList.remove('show');
  }, 3000);
}

/**
 * Display success notification
 * @param {string} message - Success message to display
 */
function showSuccessNotification(message) {
  showNotification(message, 'success');
}

/**
 * Display error notification
 * @param {string} message - Error message to display
 */
function showErrorNotification(message) {
  showNotification(message, 'error');
}

// ============================================================================
// Order Count Updates
// ============================================================================

/**
 * Update the count badges for each order status column
 */
function updateOrderCounts() {
  const statuses = ['ordered', 'preparing', 'delivering', 'delivered'];
  
  statuses.forEach(status => {
    const cards = document.querySelectorAll(`#cards-${status} .order-card`);
    const countEl = document.getElementById(`count-${status}`);
    
    if (countEl) {
      countEl.textContent = cards.length;
    }
  });
}

// ============================================================================
// Auto-Refresh Functionality
// ============================================================================

/**
 * Initialize auto-refresh to reload the dashboard every 30 seconds
 */
function initAutoRefresh() {
  setInterval(() => {
    location.reload();
  }, 30000); // 30 seconds
}

// ============================================================================
// Initialization
// ============================================================================

/**
 * Initialize all dashboard functionality when DOM is ready
 */
function initAdminDashboard() {
  // Initialize tab switching
  initTabSwitching();
  
  // Initialize order status button handlers
  initOrderStatusButtons();
  
  // Initialize ticket action button handlers
  initTicketActionButtons();
  
  // Update order counts
  updateOrderCounts();
  
  // Start auto-refresh timer
  initAutoRefresh();
}

// Initialize when DOM is fully loaded
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initAdminDashboard);
} else {
  // DOM is already loaded
  initAdminDashboard();
}

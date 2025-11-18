/**
 * HLV Barcode Shipper JavaScript
 * Mobile-optimized barcode scanning interface
 */

class BarcodeShipper {
    constructor() {
        this.currentPickingId = null;
        this.currentItems = [];
        this.sessionId = this.generateSessionId();
        
        this.init();
    }
    
    init() {
        this.bindEvents();
        this.setupBarcodeInputs();
        this.showStep('step-scan-pick');
    }
    
    generateSessionId() {
        return 'session_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    }
    
    bindEvents() {
        // Scan PICK order
        document.getElementById('scan-pick-btn').addEventListener('click', () => {
            this.scanPickOrder();
        });
        
        // Scan item
        document.getElementById('scan-item-btn').addEventListener('click', () => {
            this.scanItem();
        });
        
        // Complete delivery
        document.getElementById('complete-delivery-btn').addEventListener('click', () => {
            this.completeDelivery();
        });
        
        // Reset scan
        document.getElementById('reset-scan-btn').addEventListener('click', () => {
            this.resetScan();
        });
        
        // New delivery
        document.getElementById('new-delivery-btn').addEventListener('click', () => {
            this.startNewDelivery();
        });
        
        // Show history
        document.getElementById('show-history-btn').addEventListener('click', () => {
            this.showHistory();
        });
        
        // Show help
        document.getElementById('help-btn').addEventListener('click', () => {
            this.showHelp();
        });
        
        // Modal close buttons
        document.querySelectorAll('.close').forEach(closeBtn => {
            closeBtn.addEventListener('click', (e) => {
                this.closeModal(e.target.closest('.modal'));
            });
        });
        
        // Close modal when clicking outside
        document.querySelectorAll('.modal').forEach(modal => {
            modal.addEventListener('click', (e) => {
                if (e.target === modal) {
                    this.closeModal(modal);
                }
            });
        });
    }
    
    setupBarcodeInputs() {
        // Auto-focus and enter key handling for barcode inputs
        const pickInput = document.getElementById('pick-barcode-input');
        const itemInput = document.getElementById('item-barcode-input');
        
        pickInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                this.scanPickOrder();
            }
        });
        
        itemInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                this.scanItem();
            }
        });
        
        // Auto-focus on visible input
        this.focusCurrentInput();
    }
    
    focusCurrentInput() {
        setTimeout(() => {
            const activeStep = document.querySelector('.scan-step.active');
            if (activeStep) {
                const input = activeStep.querySelector('.barcode-input');
                if (input) {
                    input.focus();
                }
            }
        }, 100);
    }
    
    showStep(stepId) {
        // Hide all steps
        document.querySelectorAll('.scan-step').forEach(step => {
            step.classList.remove('active');
        });
        
        // Show target step
        const targetStep = document.getElementById(stepId);
        if (targetStep) {
            targetStep.classList.add('active');
            this.focusCurrentInput();
        }
    }
    
    showMessage(elementId, message, type = 'success') {
        const element = document.getElementById(elementId);
        if (element) {
            element.textContent = message;
            element.className = `result-message show ${type}`;
            
            // Auto-hide after 5 seconds for success messages
            if (type === 'success') {
                setTimeout(() => {
                    element.classList.remove('show');
                }, 5000);
            }
        }
    }
    
    clearMessage(elementId) {
        const element = document.getElementById(elementId);
        if (element) {
            element.classList.remove('show');
        }
    }
    
    async scanPickOrder() {
        const input = document.getElementById('pick-barcode-input');
        const barcode = input.value.trim();
        
        if (!barcode) {
            this.showMessage('pick-result', 'Please enter a PICK barcode', 'error');
            return;
        }
        
        this.showMessage('pick-result', 'Scanning PICK order...', 'warning');
        
        try {
            const response = await this.apiCall('/api/barcode/scan_pick', {
                barcode: barcode
            });
            
            if (response.success) {
                this.currentPickingId = response.out_picking_id;
                this.showMessage('pick-result', response.message, 'success');
                
                // Load OUT order details
                await this.loadOutOrderDetails();
                
                // Move to next step
                setTimeout(() => {
                    this.showStep('step-scan-items');
                }, 1500);
                
            } else {
                this.showMessage('pick-result', response.error || 'Failed to scan PICK order', 'error');
            }
            
        } catch (error) {
            console.error('Error scanning PICK order:', error);
            this.showMessage('pick-result', 'Network error. Please try again.', 'error');
        }
    }
    
    async loadOutOrderDetails() {
        if (!this.currentPickingId) return;
        
        try {
            const response = await this.apiCall('/api/barcode/get_out', {
                picking_id: this.currentPickingId
            });
            
            if (response.success) {
                this.currentItems = response.items;
                this.updateOrderInfo(response.picking);
                this.updateItemsList(response.items);
                this.updateProgress(response.summary);
            } else {
                this.showMessage('item-result', response.error || 'Failed to load order details', 'error');
            }
            
        } catch (error) {
            console.error('Error loading order details:', error);
            this.showMessage('item-result', 'Network error loading order details', 'error');
        }
    }
    
    updateOrderInfo(picking) {
        const orderInfo = document.getElementById('order-info');
        orderInfo.innerHTML = `
            <h4>📦 ${picking.name}</h4>
            <p><strong>Customer:</strong> ${picking.partner_name}</p>
            <p><strong>Origin:</strong> ${picking.origin}</p>
            <p><strong>Status:</strong> ${picking.state}</p>
        `;
    }
    
    updateItemsList(items) {
        const itemsList = document.getElementById('items-list');
        itemsList.innerHTML = '';
        
        items.forEach(item => {
            const itemCard = document.createElement('div');
            itemCard.className = `item-card ${item.scanned ? 'scanned' : ''}`;
            itemCard.innerHTML = `
                <div class="item-info">
                    <div class="item-name">${item.name}</div>
                    <div class="item-barcode">${item.barcode || 'No barcode'}</div>
                    ${item.qty ? `<div class="item-qty">Qty: ${item.qty}</div>` : ''}
                </div>
                <div class="item-status">${item.scanned ? '✅' : '⏳'}</div>
            `;
            itemsList.appendChild(itemCard);
        });
    }
    
    updateProgress(summary) {
        const progressFill = document.getElementById('progress-fill');
        const progressText = document.getElementById('progress-text');
        const completeBtn = document.getElementById('complete-delivery-btn');
        
        const percentage = summary.total_items > 0 ? 
            (summary.scanned_items / summary.total_items) * 100 : 0;
        
        progressFill.style.width = `${percentage}%`;
        progressText.textContent = `${summary.scanned_items} / ${summary.total_items} items scanned`;
        
        // Show complete button if all items scanned
        if (summary.all_scanned && summary.total_items > 0) {
            completeBtn.style.display = 'block';
        } else {
            completeBtn.style.display = 'none';
        }
    }
    
    async scanItem() {
        const input = document.getElementById('item-barcode-input');
        const barcode = input.value.trim();
        
        if (!barcode) {
            this.showMessage('item-result', 'Please enter an item barcode', 'error');
            return;
        }
        
        if (!this.currentPickingId) {
            this.showMessage('item-result', 'No active order. Please scan PICK order first.', 'error');
            return;
        }
        
        // Check if this is a PICK barcode (alternative completion method)
        if (barcode.toUpperCase().startsWith('PICK')) {
            await this.completeDelivery();
            return;
        }
        
        this.showMessage('item-result', 'Scanning item...', 'warning');
        
        try {
            const response = await this.apiCall('/api/barcode/scan_package', {
                picking_id: this.currentPickingId,
                barcode: barcode
            });
            
            if (response.success) {
                this.showMessage('item-result', response.message, 'success');
                
                // Update progress
                if (response.summary) {
                    this.updateProgress(response.summary);
                }
                
                // Update items list
                await this.loadOutOrderDetails();
                
                // Clear input for next scan
                input.value = '';
                input.focus();
                
            } else {
                this.showMessage('item-result', response.error || 'Item not found', 'error');
            }
            
        } catch (error) {
            console.error('Error scanning item:', error);
            this.showMessage('item-result', 'Network error. Please try again.', 'error');
        }
    }
    
    async completeDelivery() {
        if (!this.currentPickingId) {
            this.showMessage('item-result', 'No active order to complete', 'error');
            return;
        }
        
        // Show confirmation
        if (!confirm('Complete this delivery? This action cannot be undone.')) {
            return;
        }
        
        this.showMessage('item-result', 'Completing delivery...', 'warning');
        
        try {
            const response = await this.apiCall('/api/barcode/complete_out', {
                picking_id: this.currentPickingId
            });
            
            if (response.success) {
                // Show completion step
                this.showStep('step-complete');
                this.showMessage('completion-result', response.message, 'success');
                
                // Reset state
                this.currentPickingId = null;
                this.currentItems = [];
                
            } else {
                this.showMessage('item-result', response.error || 'Failed to complete delivery', 'error');
            }
            
        } catch (error) {
            console.error('Error completing delivery:', error);
            this.showMessage('item-result', 'Network error. Please try again.', 'error');
        }
    }
    
    resetScan() {
        if (confirm('Start over? This will clear current progress.')) {
            this.startNewDelivery();
        }
    }
    
    startNewDelivery() {
        // Reset state
        this.currentPickingId = null;
        this.currentItems = [];
        this.sessionId = this.generateSessionId();
        
        // Clear inputs
        document.getElementById('pick-barcode-input').value = '';
        document.getElementById('item-barcode-input').value = '';
        
        // Clear messages
        this.clearMessage('pick-result');
        this.clearMessage('item-result');
        this.clearMessage('completion-result');
        
        // Reset UI
        document.getElementById('items-list').innerHTML = '';
        document.getElementById('order-info').innerHTML = '';
        document.getElementById('progress-fill').style.width = '0%';
        document.getElementById('progress-text').textContent = '0 / 0 items scanned';
        document.getElementById('complete-delivery-btn').style.display = 'none';
        
        // Go to first step
        this.showStep('step-scan-pick');
    }
    
    async showHistory() {
        const modal = document.getElementById('history-modal');
        const content = document.getElementById('history-content');
        
        content.innerHTML = '<div class="loading">Loading scan history...</div>';
        this.showModal(modal);
        
        try {
            const response = await this.apiCall('/api/barcode/scan_history', {
                picking_id: this.currentPickingId,
                limit: 50
            });
            
            if (response.success && response.history.length > 0) {
                content.innerHTML = response.history.map(log => `
                    <div class="history-item">
                        <div class="history-time">${log.scan_time}</div>
                        <div class="history-barcode">${log.barcode}</div>
                        <span class="history-type ${log.scan_type}">${log.scan_type}</span>
                        <span class="history-status ${log.status}">${log.status}</span>
                        ${log.message ? `<div class="history-message">${log.message}</div>` : ''}
                    </div>
                `).join('');
            } else {
                content.innerHTML = '<div class="loading">No scan history found</div>';
            }
            
        } catch (error) {
            console.error('Error loading history:', error);
            content.innerHTML = '<div class="loading">Error loading history</div>';
        }
    }
    
    showHelp() {
        const modal = document.getElementById('help-modal');
        this.showModal(modal);
    }
    
    showModal(modal) {
        modal.classList.add('show');
        document.body.style.overflow = 'hidden';
    }
    
    closeModal(modal) {
        modal.classList.remove('show');
        document.body.style.overflow = '';
    }
    
    async apiCall(endpoint, data) {
        const response = await fetch(endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify(data)
        });
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        return await response.json();
    }
}

// Auto-initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    // Only initialize if we're on the shipper page
    if (document.querySelector('.shipper-container')) {
        window.barcodeShipper = new BarcodeShipper();
    }
});

// Service Worker for offline support (optional)
if ('serviceWorker' in navigator) {
    window.addEventListener('load', function() {
        navigator.serviceWorker.register('/hlv_barcode_shipper/static/src/js/sw.js')
            .then(function(registration) {
                console.log('ServiceWorker registration successful');
            })
            .catch(function(err) {
                console.log('ServiceWorker registration failed: ', err);
            });
    });
}

// Barcode scanning using device camera (if supported)
class BarcodeCamera {
    constructor(callback) {
        this.callback = callback;
        this.stream = null;
        this.video = null;
        this.canvas = null;
        this.context = null;
    }
    
    async startCamera() {
        try {
            this.stream = await navigator.mediaDevices.getUserMedia({
                video: { 
                    facingMode: 'environment', // Use back camera
                    width: { ideal: 1280 },
                    height: { ideal: 720 }
                }
            });
            
            // Create video element
            this.video = document.createElement('video');
            this.video.srcObject = this.stream;
            this.video.play();
            
            // Create canvas for image processing
            this.canvas = document.createElement('canvas');
            this.context = this.canvas.getContext('2d');
            
            return true;
        } catch (error) {
            console.error('Error accessing camera:', error);
            return false;
        }
    }
    
    stopCamera() {
        if (this.stream) {
            this.stream.getTracks().forEach(track => track.stop());
            this.stream = null;
        }
    }
    
    // This would require a barcode detection library like QuaggaJS or ZXing
    // For now, this is a placeholder for future implementation
    detectBarcode() {
        // Implementation would go here
        // This would capture frames from video and detect barcodes
    }
}

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { BarcodeShipper, BarcodeCamera };
}
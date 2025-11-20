// hlv_barcode_shipper/static/src/js/barcode_scanner.js
/**
 * HLV Barcode Shipper JavaScript
 */

class BarcodeShipper {
    constructor() {
        this.currentPickingId = null;
        this.currentItems = [];
        this.scannedBarcodes = new Set();
        this.html5QrCode = null;
        this.isCameraRunning = false;

        this.sessionId = this.generateSessionId();
        this.init();
    }

    generateSessionId() {
        return 'session_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    }

    init() {
        this.bindEvents();
        this.setupBarcodeInputs();
        this.showStep('step-scan-pick');

        // Reload warning
        window.addEventListener('beforeunload', (e) => {
            if (this.currentPickingId && this.currentItems.length > 0) {
                e.preventDefault();
                e.returnValue = '';
            }
        });
    }

    bindEvents() {
        // Buttons
        document.getElementById('scan-pick-btn')?.addEventListener('click', () => this.scanPickOrder());
        document.getElementById('scan-item-btn')?.addEventListener('click', () => this.scanItem());
        document.getElementById('complete-delivery-btn')?.addEventListener('click', () => this.completeDelivery());
        document.getElementById('reset-scan-btn')?.addEventListener('click', () => this.resetScan());
        document.getElementById('new-delivery-btn')?.addEventListener('click', () => this.startNewDelivery());
        document.getElementById('show-history-btn')?.addEventListener('click', () => this.showHistory());
        document.getElementById('help-btn')?.addEventListener('click', () => this.showHelp());

        // Camera Buttons
        document.getElementById('btn-open-camera-pick')?.addEventListener('click', () => this.startCamera('camera-pick', 'reader-pick', 'pick'));
        document.getElementById('btn-open-camera-item')?.addEventListener('click', () => this.startCamera('camera-item', 'reader-item', 'item'));

        // Modals
        document.querySelectorAll('.modal-close').forEach(btn => {
            btn.addEventListener('click', e => this.closeModal(e.target.closest('.modal-overlay')));
        });

        document.querySelectorAll('.modal-overlay').forEach(modal => {
            modal.addEventListener('click', e => {
                if (e.target === modal) this.closeModal(modal);
            });
        });
    }

    setupBarcodeInputs() {
        const pickInput = document.getElementById('pick-barcode-input');
        const itemInput = document.getElementById('item-barcode-input');

        if (pickInput) {
            pickInput.addEventListener('keypress', e => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    this.scanPickOrder();
                }
            });
        }

        if (itemInput) {
            itemInput.addEventListener('keypress', e => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    this.scanItem();
                }
            });
        }

        this.focusCurrentInput();
    }

    focusCurrentInput() {
        setTimeout(() => {
            const step = document.querySelector('.scan-step.active');
            const input = step && step.querySelector('.form-control');
            if (input) input.focus();
        }, 100);
    }

    showStep(id) {
        document.querySelectorAll('.scan-step').forEach(s => s.classList.remove('active'));
        const step = document.getElementById(id);
        if (step) {
            step.classList.add('active');
            this.focusCurrentInput();
        }
        this.stopCamera(); // Stop camera when switching steps
    }

    showMessage(id, message, type = 'success') {
        const el = document.getElementById(id);
        if (!el) return;
        el.textContent = message;
        el.className = `alert show alert-${type}`; // Use Bootstrap-like classes
        if (type === 'success') {
            setTimeout(() => el.classList.remove('show'), 4000);
        }
    }

    clearMessage(id) {
        const el = document.getElementById(id);
        if (el) el.classList.remove('show');
    }

    // --- Camera Logic ---
    async startCamera(sectionId, readerId, mode) {
        if (this.isCameraRunning) {
            await this.stopCamera();
        }

        const section = document.getElementById(sectionId);
        if (section) section.classList.add('active');

        this.html5QrCode = new Html5Qrcode(readerId);
        const config = { fps: 10, qrbox: { width: 280, height: 150 } };

        // Support Code 128 and QR Code
        const formatsToSupport = [
            Html5QrcodeSupportedFormats.QR_CODE,
            Html5QrcodeSupportedFormats.CODE_128,
            Html5QrcodeSupportedFormats.CODE_39,
            Html5QrcodeSupportedFormats.EAN_13
        ];

        try {
            await this.html5QrCode.start(
                { facingMode: "environment" },
                config,
                (decodedText, decodedResult) => {
                    // Success callback
                    this.onScanSuccess(decodedText, mode);
                },
                (errorMessage) => {
                    // parse error, ignore
                }
            );
            this.isCameraRunning = true;
        } catch (err) {
            console.error("Error starting camera", err);
            alert("Không thể mở camera. Vui lòng kiểm tra quyền truy cập.");
            section.classList.remove('active');
        }
    }

    async stopCamera() {
        if (this.html5QrCode && this.isCameraRunning) {
            try {
                await this.html5QrCode.stop();
                this.html5QrCode.clear();
                this.isCameraRunning = false;
            } catch (e) {
                console.error("Failed to stop camera", e);
            }
        }
        document.querySelectorAll('.camera-section').forEach(el => el.classList.remove('active'));
    }

    onScanSuccess(decodedText, mode) {
        // Play beep sound
        // const audio = new Audio('/hlv_barcode_shipper/static/src/sounds/beep.mp3'); // If we had one
        // audio.play().catch(e => {});

        if (mode === 'pick') {
            const input = document.getElementById('pick-barcode-input');
            if (input) {
                input.value = decodedText;
                this.scanPickOrder();
                this.stopCamera();
            }
        } else if (mode === 'item') {
            const input = document.getElementById('item-barcode-input');
            if (input) {
                input.value = decodedText;
                this.scanItem();
                // Don't stop camera immediately for items to allow continuous scanning? 
                // User preference. Let's stop for now to avoid double scans, or add a delay.
                // For now, stop to be safe.
                // this.stopCamera(); 

                // Better UX: Pause scanning briefly
                this.html5QrCode.pause();
                setTimeout(() => this.html5QrCode.resume(), 1500);
            }
        }
    }

    // --- API Calls ---

    async scanPickOrder() {
        const input = document.getElementById('pick-barcode-input');
        const barcode = (input?.value || '').trim();
        if (!barcode) {
            this.showMessage('pick-result', 'Vui lòng nhập mã PICK', 'danger');
            return;
        }

        this.showMessage('pick-result', 'Đang tìm phiếu giao hàng...', 'warning');
        try {
            const res = await this.apiCall('/api/barcode/scan_pick', { barcode });
            if (res.success) {
                this.currentPickingId = res.out_picking_id;
                this.showMessage('pick-result', res.message, 'success');
                await this.loadOutOrderDetails();
                setTimeout(() => this.showStep('step-scan-items'), 1000);
            } else {
                this.showMessage('pick-result', res.error || 'Không tìm thấy', 'danger');
            }
        } catch (e) {
            console.error(e);
            this.showMessage('pick-result', 'Lỗi kết nối, vui lòng thử lại.', 'danger');
        }
    }

    async loadOutOrderDetails() {
        if (!this.currentPickingId) return;
        try {
            const res = await this.apiCall('/api/barcode/get_out', {
                picking_id: this.currentPickingId,
            });
            if (!res.success) {
                this.showMessage('item-result', res.error || 'Không tải được dữ liệu', 'danger');
                return;
            }

            // Gắn cờ scanned theo các barcode đã quét trước đó
            this.currentItems = (res.items || []).map(item => {
                const scanned = item.barcode && this.scannedBarcodes.has(item.barcode);
                return { ...item, scanned };
            });

            this.updateOrderInfo(res.picking);

            const total = this.currentItems.length;
            const scannedCount = this.currentItems.filter(i => i.scanned).length;
            this.updateItemsList(this.currentItems);
            this.updateProgress({
                total_items: total,
                scanned_items: scannedCount,
                all_scanned: total > 0 && scannedCount === total,
            });
        } catch (e) {
            console.error(e);
            this.showMessage('item-result', 'Lỗi kết nối, vui lòng thử lại.', 'danger');
        }
    }


    updateOrderInfo(p) {
        const el = document.getElementById('order-info');
        if (!el || !p) return;
        el.innerHTML = `
            <div class="order-details">
                <div class="detail-row">
                    <span class="detail-label">Mã đơn:</span>
                    <span class="detail-value">${p.name}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">Khách hàng:</span>
                    <span class="detail-value">${p.partner_name || 'N/A'}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">Nguồn:</span>
                    <span class="detail-value">${p.origin || 'N/A'}</span>
                </div>
            </div>
        `;
    }

    updateItemsList(items) {
        const list = document.getElementById('items-list');
        if (!list) return;
        list.innerHTML = '';
        (items || []).forEach(item => {
            const div = document.createElement('div');
            div.className = `item-card ${item.scanned ? 'scanned' : ''}`;
            div.innerHTML = `
                <div class="item-info">
                    <div class="item-name">${item.name || ''}</div>
                    <div class="item-barcode">${item.barcode || ''}</div>
                </div>
                <div class="item-status-icon">${item.scanned ? '✅' : '📦'}</div>
            `;
            list.appendChild(div);
        });
    }

    updateProgress(summary) {
        const fill = document.getElementById('progress-fill');
        const text = document.getElementById('progress-text');
        const btn = document.getElementById('complete-delivery-btn');
        const total = summary?.total_items || 0;
        const scanned = summary?.scanned_items || 0;
        const percent = total ? (scanned / total) * 100 : 0;
        if (fill) fill.style.width = `${percent}%`;
        if (text) text.textContent = `${scanned} / ${total} đã quét`;
        if (btn) btn.style.display = summary?.all_scanned && total ? 'block' : 'none';
    }

    async scanItem() {
        const input = document.getElementById('item-barcode-input');
        const barcode = (input?.value || '').trim();
        if (!barcode) {
            this.showMessage('item-result', 'Vui lòng nhập mã kiện / sản phẩm', 'danger');
            return;
        }
        if (!this.currentPickingId) {
            this.showMessage('item-result', 'Chưa có đơn hoạt động. Hãy quét PICK trước.', 'danger');
            return;
        }

        // nếu lỡ scan lại PICK -> coi như complete (nếu đủ điều kiện)
        if (barcode.toUpperCase().startsWith('PICK')) {
            // Check if all scanned first? Or just try to complete
            // Let's just try to complete, backend will validate or we validate frontend
            const allScanned = this.currentItems.every(i => i.scanned);
            if (allScanned) {
                await this.completeDelivery();
            } else {
                this.showMessage('item-result', 'Chưa quét đủ hàng hóa!', 'warning');
            }
            return;
        }

        this.showMessage('item-result', 'Đang kiểm tra...', 'warning');
        try {
            const res = await this.apiCall('/api/barcode/scan_package', {
                picking_id: this.currentPickingId,
                barcode,
            });

            console.log('scan_package result:', res);

            if (res.success) {
                this.showMessage('item-result', res.message, 'success');

                // Lưu barcode này vào danh sách đã quét
                if (barcode) this.scannedBarcodes.add(barcode);

                // Đánh dấu scanned cho item tương ứng trong currentItems
                // Logic: Find item with matching barcode. If found, mark scanned.
                let found = false;
                this.currentItems = (this.currentItems || []).map(item => {
                    if (!item.barcode) return item;
                    if (item.barcode === barcode) {
                        found = true;
                        return { ...item, scanned: true };
                    }
                    return item;
                });

                if (!found) {
                    // Warning if scanned something not in list?
                    // The backend said success, so it might be a product inside a package?
                    // For now, trust backend success but if not in list, maybe reload list?
                    // Or maybe the backend matched a product code that is different from display name?
                    // Let's reload details to be safe if we didn't find it in our simple list match
                    await this.loadOutOrderDetails();
                } else {
                    // Update UI locally
                    const total = this.currentItems.length;
                    const scannedCount = this.currentItems.filter(i => i.scanned).length;
                    this.updateItemsList(this.currentItems);
                    this.updateProgress({
                        total_items: total,
                        scanned_items: scannedCount,
                        all_scanned: total > 0 && scannedCount === total,
                    });
                }

                if (input) {
                    input.value = '';
                    input.focus();
                }
            } else {
                this.showMessage('item-result', res.error || 'Không tìm thấy mã này', 'danger');
            }
        } catch (e) {
            console.error(e);
            this.showMessage('item-result', 'Lỗi kết nối, vui lòng thử lại.', 'danger');
        }
    }


    async completeDelivery() {
        if (!this.currentPickingId) {
            this.showMessage('item-result', 'Không có đơn nào để hoàn tất.', 'danger');
            return;
        }
        if (!confirm('Xác nhận hoàn tất giao hàng?')) return;

        this.showMessage('item-result', 'Đang xử lý...', 'warning');
        try {
            const res = await this.apiCall('/api/barcode/complete_out', {
                picking_id: this.currentPickingId,
            });
            if (res.success) {
                this.showStep('step-complete');
                this.showMessage('completion-result', res.message, 'success');
                this.currentPickingId = null;
                this.currentItems = [];
                this.scannedBarcodes.clear();
            } else {
                this.showMessage('item-result', res.error || 'Không hoàn tất được', 'danger');
            }
        } catch (e) {
            console.error(e);
            this.showMessage('item-result', 'Lỗi kết nối, vui lòng thử lại.', 'danger');
        }
    }

    resetScan() {
        if (confirm('Bạn có chắc muốn làm lại từ đầu? Dữ liệu quét hiện tại sẽ mất.')) {
            this.startNewDelivery();
        }
    }

    startNewDelivery() {
        this.currentPickingId = null;
        this.currentItems = [];
        this.scannedBarcodes = new Set();

        this.sessionId = this.generateSessionId();

        const pickInput = document.getElementById('pick-barcode-input');
        const itemInput = document.getElementById('item-barcode-input');
        if (pickInput) pickInput.value = '';
        if (itemInput) itemInput.value = '';

        this.clearMessage('pick-result');
        this.clearMessage('item-result');
        this.clearMessage('completion-result');

        const list = document.getElementById('items-list');
        const info = document.getElementById('order-info');
        const fill = document.getElementById('progress-fill');
        const text = document.getElementById('progress-text');
        const btn = document.getElementById('complete-delivery-btn');

        if (list) list.innerHTML = '';
        if (info) info.innerHTML = '';
        if (fill) fill.style.width = '0%';
        if (text) text.textContent = '0 / 0 đã quét';
        if (btn) btn.style.display = 'none';

        this.showStep('step-scan-pick');
    }

    async showHistory() {
        const modal = document.getElementById('history-modal');
        const content = document.getElementById('history-content');
        if (!modal || !content) return;
        content.innerHTML = 'Đang tải...';
        this.showModal(modal);
        try {
            const res = await this.apiCall('/api/barcode/scan_history', {
                picking_id: this.currentPickingId,
                limit: 50,
            });
            if (res.success && res.history && res.history.length) {
                content.innerHTML = res.history
                    .map(
                        log => `
                    <div style="border-bottom: 1px solid #eee; padding: 8px 0;">
                        <div style="font-size: 12px; color: #888;">${log.scan_time}</div>
                        <div style="font-weight: 600;">${log.barcode}</div>
                        <div style="display: flex; justify-content: space-between; font-size: 13px;">
                            <span class="${log.scan_type}">${log.scan_type}</span>
                            <span class="${log.status}" style="color: ${log.status === 'success' ? 'green' : 'red'}">${log.status}</span>
                        </div>
                        ${log.message ? `<div style="font-size: 12px; color: #666;">${log.message}</div>` : ''}
                    </div>`
                    )
                    .join('');
            } else {
                content.innerHTML = 'Chưa có lịch sử quét.';
            }
        } catch (e) {
            console.error(e);
            content.innerHTML = 'Lỗi tải lịch sử.';
        }
    }

    showHelp() {
        const modal = document.getElementById('help-modal');
        if (modal) this.showModal(modal);
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
        const res = await fetch(endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
            },
            body: JSON.stringify(data),
        });

        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        const json = await res.json();

        // Odoo type="json" → { jsonrpc, id, result }
        if (json && typeof json === 'object') {
            if (Object.prototype.hasOwnProperty.call(json, 'result')) {
                return json.result;
            }
            if (Object.prototype.hasOwnProperty.call(json, 'error')) {
                throw new Error(json.error.message || 'JSON-RPC error');
            }
        }

        return json;
    }

}

// Auto-init
document.addEventListener('DOMContentLoaded', () => {
    if (document.querySelector('.shipper-container')) {
        window.barcodeShipper = new BarcodeShipper();
    }
});

// Service Worker (Optional)
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker
            .register('/hlv_barcode_shipper/static/src/js/sw.js')
            .catch(err => console.warn('SW failed:', err));
    });
}

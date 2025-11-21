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
        this.currentCameraSection = null;

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
            if (this.currentPickingId) {
                const msg = '⚠️ CẢNH BÁO: Bạn đang có đơn hàng chưa hoàn tất!\n\nNếu tải lại trang, tiến độ quét sẽ bị MẤT.\nBạn có chắc chắn muốn rời đi không?';
                e.preventDefault();
                e.returnValue = msg;
                return msg;
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

        // Camera Buttons (Manual)
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

            // Auto-start camera based on step
            if (id === 'step-scan-pick') {
                this.startCamera('camera-pick', 'reader-pick', 'pick');
            } else if (id === 'step-scan-items') {
                this.startCamera('camera-item', 'reader-item', 'item');
            } else {
                this.stopCamera();
            }
        } else {
            this.stopCamera();
        }
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
        // If already running for the same section, do nothing
        if (this.isCameraRunning && this.currentCameraSection === sectionId) {
            return;
        }

        if (this.isCameraRunning) {
            await this.stopCamera();
        }

        const section = document.getElementById(sectionId);
        if (section) section.classList.add('active');
        this.currentCameraSection = sectionId;

        // Hide manual button if auto-started
        if (mode === 'pick') {
            const btn = document.getElementById('btn-open-camera-pick');
            if (btn) btn.style.display = 'none';
        } else if (mode === 'item') {
            const btn = document.getElementById('btn-open-camera-item');
            if (btn) btn.style.display = 'none';
        }

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
            // Show manual button if camera fails
            if (mode === 'pick') {
                const btn = document.getElementById('btn-open-camera-pick');
                if (btn) btn.style.display = 'block';
            } else if (mode === 'item') {
                const btn = document.getElementById('btn-open-camera-item');
                if (btn) btn.style.display = 'block';
            }
            // alert("Không thể mở camera. Vui lòng kiểm tra quyền truy cập.");
            section.classList.remove('active');
        }
    }

    async stopCamera() {
        if (this.html5QrCode && this.isCameraRunning) {
            try {
                await this.html5QrCode.stop();
                this.html5QrCode.clear();
                this.isCameraRunning = false;
                this.currentCameraSection = null;
            } catch (e) {
                console.error("Failed to stop camera", e);
            }
        }
        document.querySelectorAll('.camera-section').forEach(el => el.classList.remove('active'));

        // Restore buttons
        const btnPick = document.getElementById('btn-open-camera-pick');
        const btnItem = document.getElementById('btn-open-camera-item');
        if (btnPick) btnPick.style.display = 'block';
        if (btnItem) btnItem.style.display = 'block';
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
                // For pick, we stop camera because we switch steps
                this.stopCamera();
            }
        } else if (mode === 'item') {
            const input = document.getElementById('item-barcode-input');
            if (input) {
                input.value = decodedText;
                this.scanItem();

                // Continuous scanning: DO NOT stop camera.
                // Just pause briefly to avoid double scans
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

            // Initialize items with scanned_qty = 0
            this.currentItems = (res.items || []).map(item => {
                return { ...item, scanned_qty: 0 };
            });

            this.updateOrderInfo(res.picking);

            const total = this.currentItems.length; // Total unique items
            // For progress, maybe we want total quantity?
            // Let's sum up quantities
            const totalQty = this.currentItems.reduce((sum, i) => sum + (i.qty || 0), 0);

            this.updateItemsList(this.currentItems);
            this.updateProgress({
                total_qty: totalQty,
                scanned_qty: 0,
                all_scanned: false,
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
            const isFullyScanned = (item.scanned_qty || 0) >= (item.qty || 0);
            div.className = `item-card ${isFullyScanned ? 'scanned' : ''}`;

            // Determine icon
            let icon = '';
            if (isFullyScanned) {
                icon = '<i class="fa fa-check-circle" style="color: var(--success-color);"></i>';
            } else {
                icon = item.type === 'package'
                    ? '<i class="fa fa-box" style="color: var(--secondary-color);"></i>'
                    : '<i class="fa fa-cube" style="color: var(--secondary-color);"></i>';
            }

            div.innerHTML = `
                <div class="item-info">
                    <div class="item-name">${item.name || ''}</div>
                    <div class="item-details" style="display: flex; gap: 15px; font-size: 0.85rem; color: #6c757d; margin-top: 4px;">
                        <span class="item-barcode"><i class="fa fa-barcode"></i> ${item.barcode || ''}</span>
                        <span class="item-qty"><i class="fa fa-layer-group"></i> SL: ${item.scanned_qty || 0} / ${item.qty || 0}</span>
                    </div>
                </div>
                <div class="item-status-icon" style="font-size: 1.5rem;">${icon}</div>
            `;
            list.appendChild(div);
        });
    }

    updateProgress(summary) {
        const fill = document.getElementById('progress-fill');
        const text = document.getElementById('progress-text');
        const btn = document.getElementById('complete-delivery-btn');

        const total = summary?.total_qty || 0;
        const scanned = summary?.scanned_qty || 0;

        const percent = total ? (scanned / total) * 100 : 0;
        if (fill) fill.style.width = `${percent}%`;
        if (text) text.textContent = `${scanned} / ${total} sản phẩm`;
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
            const allScanned = this.currentItems.every(i => (i.scanned_qty || 0) >= (i.qty || 0));
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

                // Find item in local list
                let found = false;
                this.currentItems = (this.currentItems || []).map(item => {
                    if (!item.barcode) return item;
                    if (item.barcode === barcode) {
                        found = true;
                        let newQty = (item.scanned_qty || 0);

                        // Logic: Package -> Mark full. Product -> Increment.
                        if (item.type === 'package') {
                            newQty = item.qty; // Scan package once = full
                        } else {
                            newQty += 1;
                        }

                        // Optional: Cap at max qty?
                        if (newQty > item.qty) {
                            // Warn user? Or just allow overscan?
                            // For now, allow but maybe show warning?
                            // Or cap it? Let's cap it for visual, but maybe warn.
                            // this.showMessage('item-result', 'Đã quét đủ số lượng!', 'warning');
                            // newQty = item.qty; 
                            // User requirement: "quét nhiều lần tương đương số lượng".
                            // If I have 2 items, I scan twice.
                        }

                        return { ...item, scanned_qty: newQty };
                    }
                    return item;
                });

                if (!found) {
                    // Item not in list (maybe extra item?)
                    this.showMessage('item-result', 'Mã này không có trong danh sách đơn hàng!', 'warning');
                } else {
                    // Update UI locally
                    const totalQty = this.currentItems.reduce((sum, i) => sum + (i.qty || 0), 0);
                    const scannedQty = this.currentItems.reduce((sum, i) => sum + (i.scanned_qty || 0), 0);
                    const allScanned = this.currentItems.every(i => (i.scanned_qty || 0) >= (i.qty || 0));

                    this.updateItemsList(this.currentItems);
                    this.updateProgress({
                        total_qty: totalQty,
                        scanned_qty: scannedQty,
                        all_scanned: allScanned,
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
        // REMOVED CONFIRMATION
        // if (!confirm('Xác nhận hoàn tất giao hàng?')) return;

        this.showMessage('item-result', 'Đang xử lý...', 'warning');
        try {
            const res = await this.apiCall('/api/barcode/complete_out', {
                picking_id: this.currentPickingId,
            });
            if (res.success) {
                // Show success briefly then reset
                this.showMessage('pick-result', '✅ Giao hàng thành công! Đã sẵn sàng cho đơn tiếp theo.', 'success');

                // Reset immediately to Step 1
                this.startNewDelivery();
            } else {
                this.showMessage('item-result', res.error || 'Không hoàn tất được', 'danger');
            }
        } catch (e) {
            console.error(e);
            this.showMessage('item-result', 'Lỗi kết nối, vui lòng thử lại.', 'danger');
        }
    }

    resetScan() {
        if (confirm('⚠️ CẢNH BÁO: Dữ liệu quét hiện tại sẽ bị MẤT.\nBạn có chắc chắn muốn làm lại từ đầu không?')) {
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
        if (text) text.textContent = '0 / 0 sản phẩm';
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

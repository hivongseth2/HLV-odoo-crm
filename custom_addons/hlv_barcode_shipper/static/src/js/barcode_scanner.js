// hlv_barcode_shipper/static/src/js/barcode_scanner.js
/**
 * HLV Barcode Shipper JavaScript
 */

class BarcodeShipper {
    constructor() {
        this.currentPickingId = null;
        this.currentItems = [];
        this.scannedBarcodes = new Set();   // <-- THÊM

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
    }

    bindEvents() {
        document.getElementById('scan-pick-btn')?.addEventListener('click', () => this.scanPickOrder());
        document.getElementById('scan-item-btn')?.addEventListener('click', () => this.scanItem());
        document.getElementById('complete-delivery-btn')?.addEventListener('click', () => this.completeDelivery());
        document.getElementById('reset-scan-btn')?.addEventListener('click', () => this.resetScan());
        document.getElementById('new-delivery-btn')?.addEventListener('click', () => this.startNewDelivery());
        document.getElementById('show-history-btn')?.addEventListener('click', () => this.showHistory());
        document.getElementById('help-btn')?.addEventListener('click', () => this.showHelp());

        document.querySelectorAll('.modal .close').forEach(btn => {
            btn.addEventListener('click', e => this.closeModal(e.target.closest('.modal')));
        });

        document.querySelectorAll('.modal').forEach(modal => {
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
            const input = step && step.querySelector('.barcode-input');
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
    }

    showMessage(id, message, type = 'success') {
        const el = document.getElementById(id);
        if (!el) return;
        el.textContent = message;
        el.className = `result-message show ${type}`;
        if (type === 'success') {
            setTimeout(() => el.classList.remove('show'), 4000);
        }
    }

    clearMessage(id) {
        const el = document.getElementById(id);
        if (el) el.classList.remove('show');
    }

    async scanPickOrder() {
        const input = document.getElementById('pick-barcode-input');
        const barcode = (input?.value || '').trim();
        if (!barcode) {
            this.showMessage('pick-result', 'Vui lòng nhập barcode PICK', 'error');
            return;
        }

        this.showMessage('pick-result', 'Đang tìm phiếu OUT...', 'warning');
        try {
            const res = await this.apiCall('/api/barcode/scan_pick', { barcode });
            if (res.success) {
                this.currentPickingId = res.out_picking_id;
                this.showMessage('pick-result', res.message, 'success');
                await this.loadOutOrderDetails();
                setTimeout(() => this.showStep('step-scan-items'), 1000);
            } else {
                this.showMessage('pick-result', res.error || 'Không tìm thấy', 'error');
            }
        } catch (e) {
            console.error(e);
            this.showMessage('pick-result', 'Lỗi mạng, thử lại.', 'error');
        }
    }

    async loadOutOrderDetails() {
        if (!this.currentPickingId) return;
        try {
            const res = await this.apiCall('/api/barcode/get_out', {
                picking_id: this.currentPickingId,
            });
            if (!res.success) {
                this.showMessage('item-result', res.error || 'Không tải được dữ liệu', 'error');
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
            this.showMessage('item-result', 'Lỗi mạng, thử lại.', 'error');
        }
    }


    updateOrderInfo(p) {
        const el = document.getElementById('order-info');
        if (!el || !p) return;
        el.innerHTML = `
            <h4>📦 ${p.name}</h4>
            <p><strong>Customer:</strong> ${p.partner_name || ''}</p>
            <p><strong>Origin:</strong> ${p.origin || ''}</p>
            <p><strong>Status:</strong> ${p.state}</p>
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
                    ${item.qty ? `<div class="item-qty">Qty: ${item.qty}</div>` : ''}
                </div>
                <div class="item-status">${item.scanned ? '✅' : '⏳'}</div>
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
        if (text) text.textContent = `${scanned} / ${total} items scanned`;
        if (btn) btn.style.display = summary?.all_scanned && total ? 'block' : 'none';
    }
    // async scanItem() {
    //     const input = document.getElementById('item-barcode-input');
    //     const barcode = (input?.value || '').trim();
    //     if (!barcode) {
    //         this.showMessage('item-result', 'Vui lòng nhập barcode kiện / sản phẩm', 'error');
    //         return;
    //     }
    //     if (!this.currentPickingId) {
    //         this.showMessage('item-result', 'Chưa có đơn hoạt động. Hãy scan PICK trước.', 'error');
    //         return;
    //     }

    //     // nếu lỡ scan lại PICK -> coi như complete
    //     if (barcode.toUpperCase().startsWith('PICK')) {
    //         await this.completeDelivery();
    //         return;
    //     }

    //     this.showMessage('item-result', 'Đang kiểm tra barcode...', 'warning');
    //     try {
    //         const res = await this.apiCall('/api/barcode/scan_package', {
    //             picking_id: this.currentPickingId,
    //             barcode,
    //         });

    //         // THÊM DÒNG LOG NÀY ĐỂ DỄ DEBUG
    //         console.log('scan_package result:', res);

    //         if (res.success) {
    //             this.showMessage('item-result', res.message, 'success');
    //             if (res.summary) this.updateProgress(res.summary);
    //             await this.loadOutOrderDetails();
    //             if (input) {
    //                 input.value = '';
    //                 input.focus();
    //             }
    //         } else {
    //             this.showMessage('item-result', res.error || 'Không tìm thấy', 'error');
    //         }
    //     } catch (e) {
    //         console.error(e);
    //         this.showMessage('item-result', 'Lỗi mạng, thử lại.', 'error');
    //     }
    // }
    async scanItem() {
        const input = document.getElementById('item-barcode-input');
        const barcode = (input?.value || '').trim();
        if (!barcode) {
            this.showMessage('item-result', 'Vui lòng nhập barcode kiện / sản phẩm', 'error');
            return;
        }
        if (!this.currentPickingId) {
            this.showMessage('item-result', 'Chưa có đơn hoạt động. Hãy scan PICK trước.', 'error');
            return;
        }

        // nếu lỡ scan lại PICK -> coi như complete
        if (barcode.toUpperCase().startsWith('PICK')) {
            await this.completeDelivery();
            return;
        }

        this.showMessage('item-result', 'Đang kiểm tra barcode...', 'warning');
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
                this.currentItems = (this.currentItems || []).map(item => {
                    if (!item.barcode) return item;
                    if (item.barcode === barcode) {
                        return { ...item, scanned: true };
                    }
                    return item;
                });

                // Tính lại progress
                const total = this.currentItems.length;
                const scannedCount = this.currentItems.filter(i => i.scanned).length;
                this.updateItemsList(this.currentItems);
                this.updateProgress({
                    total_items: total,
                    scanned_items: scannedCount,
                    all_scanned: total > 0 && scannedCount === total,
                });

                if (input) {
                    input.value = '';
                    input.focus();
                }
            } else {
                this.showMessage('item-result', res.error || 'Không tìm thấy', 'error');
            }
        } catch (e) {
            console.error(e);
            this.showMessage('item-result', 'Lỗi mạng, thử lại.', 'error');
        }
    }


    async completeDelivery() {
        if (!this.currentPickingId) {
            this.showMessage('item-result', 'Không có đơn nào để hoàn tất.', 'error');
            return;
        }
        if (!confirm('Hoàn tất giao hàng cho phiếu OUT này?')) return;

        this.showMessage('item-result', 'Đang hoàn tất...', 'warning');
        try {
            const res = await this.apiCall('/api/barcode/complete_out', {
                picking_id: this.currentPickingId,
            });
            if (res.success) {
                this.showStep('step-complete');
                this.showMessage('completion-result', res.message, 'success');
                this.currentPickingId = null;
                this.currentItems = [];
            } else {
                this.showMessage('item-result', res.error || 'Không hoàn tất được', 'error');
            }
        } catch (e) {
            console.error(e);
            this.showMessage('item-result', 'Lỗi mạng, thử lại.', 'error');
        }
    }

    resetScan() {
        if (confirm('Bắt đầu lại? Tiến trình quét hiện tại sẽ mất.')) {
            this.startNewDelivery();
        }
    }

    startNewDelivery() {
        this.currentPickingId = null;
        this.currentItems = [];
        this.scannedBarcodes = new Set();   // <-- THÊM

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
        if (text) text.textContent = '0 / 0 items scanned';
        if (btn) btn.style.display = 'none';

        this.showStep('step-scan-pick');
    }

    async showHistory() {
        const modal = document.getElementById('history-modal');
        const content = document.getElementById('history-content');
        if (!modal || !content) return;
        content.innerHTML = 'Loading...';
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
                    <div class="history-item">
                        <div class="history-time">${log.scan_time}</div>
                        <div class="history-barcode">${log.barcode}</div>
                        <span class="history-type ${log.scan_type}">${log.scan_type}</span>
                        <span class="history-status ${log.status}">${log.status}</span>
                        ${log.message ? `<div class="history-message">${log.message}</div>` : ''}
                    </div>`
                    )
                    .join('');
            } else {
                content.innerHTML = 'No scan history found';
            }
        } catch (e) {
            console.error(e);
            content.innerHTML = 'Error loading history';
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
                return json.result; // <-- từ giờ phía trên xài res.success, res.message bình thường
            }
            if (Object.prototype.hasOwnProperty.call(json, 'error')) {
                throw new Error(json.error.message || 'JSON-RPC error');
            }
        }

        // fallback nếu sau này đổi sang type="http" trả JSON thuần
        return json;
    }

}

// Auto-init
document.addEventListener('DOMContentLoaded', () => {
    if (document.querySelector('.shipper-container')) {
        window.barcodeShipper = new BarcodeShipper();
    }
});

// Đăng ký service worker (optional)
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker
            .register('/hlv_barcode_shipper/static/src/js/sw.js')
            .catch(err => console.warn('SW failed:', err));
    });
}

/** @odoo-module */

import { Component, useState, onWillStart, onMounted } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class InventoryCheckScanner extends Component {
    static template = "hlv_barcode_realtime_inventory.inventory_check";
    static components = {};

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");

        this.state = useState({
            // Session
            check_id: null,
            location_id: null,
            location_name: '',

            // UI State
            view: 'location_select',
            is_loading: false,
            error_message: '',
            warning_message: '',

            // Data
            check_data: null,
            lines: [],
            discrepancies: [],

            // Input
            location_barcode: '',
            product_barcode: '',

            // Inline discrepancy dialog state
            discrepancy_dialog: null,

            // Active sessions for explicit resume (cross-device)
            active_sessions: [],

            // Device
            device_id: this._generateDeviceId(),
        });

        onWillStart(async () => {
            await this._restoreSession();
        });

        onMounted(() => {
            this._focusOnBarcodeInput();
        });
    }

    // ========== Device Management ==========
    _generateDeviceId() {
        let deviceId = localStorage.getItem('hlv_device_id');
        if (!deviceId) {
            deviceId = 'device_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
            localStorage.setItem('hlv_device_id', deviceId);
        }
        return deviceId;
    }

    // ========== Session Management ==========
    async _restoreSession() {
        this.state.is_loading = true;
        try {
            const [result, sessions] = await Promise.all([
                this.orm.call('inventory.check', 'get_or_create_active_check', [this.state.device_id], {}),
                this.orm.call('inventory.check', 'get_active_sessions', [], {}),
            ]);

            if (result.success) {
                this.state.check_id = result.check_id;
                this.state.location_id = result.location_id;
                this.state.location_name = result.location_name;
                this.state.check_data = result;
                this.state.lines = result.lines || [];
                this.state.discrepancies = result.discrepancies || [];

                // Resume directly to scanning view if location already set
                if (result.location_id) {
                    this.state.view = 'scanning';
                    this.state.active_sessions = [];
                } else {
                    // Show other active sessions so user can pick one to resume
                    this.state.active_sessions = sessions.filter(s => s.check_id !== result.check_id);
                }
            }
        } catch (error) {
            this._showError('Lỗi khôi phục phiên: ' + error.message);
        } finally {
            this.state.is_loading = false;
        }
    }

    async resumeCheck(check_id) {
        this.state.is_loading = true;
        try {
            const result = await this.orm.call('inventory.check', 'resume_check', [check_id], {});
            if (result.success) {
                this.state.check_id = result.check_id;
                this.state.location_id = result.location_id;
                this.state.location_name = result.location_name;
                this.state.check_data = result;
                this.state.lines = result.lines || [];
                this.state.discrepancies = result.discrepancies || [];
                this.state.active_sessions = [];
                if (result.location_id) {
                    this.state.view = 'scanning';
                    this._focusOnBarcodeInput();
                }
            } else {
                this._showError(result.error);
            }
        } catch (error) {
            this._showError('Lỗi tiếp tục phiên: ' + error.message);
        } finally {
            this.state.is_loading = false;
        }
    }

    // ========== Location Selection ==========
    async onLocationBarcodeInput(event) {
        if (event.key === 'Enter') {
            event.preventDefault();
            await this.selectLocationByBarcode();
        }
    }

    async selectLocationByBarcode() {
        const barcode = this.state.location_barcode.trim();
        if (!barcode) {
            this._showError('Vui lòng nhập mã vị trí');
            return;
        }

        this.state.is_loading = true;
        try {
            const result = await this.orm.call(
                'inventory.check',
                'search_location',
                [barcode],
                {}
            );

            if (result.success) {
                await this._setLocation(result.location_id, result.location_name);
                this.state.location_barcode = '';
            } else {
                this._showError(result.error || 'Không tìm thấy vị trí');
            }
        } catch (error) {
            this._showError('Lỗi: ' + error.message);
        } finally {
            this.state.is_loading = false;
        }
    }

    async _setLocation(location_id, location_name) {
        this.state.location_id = location_id;
        this.state.location_name = location_name;
        this.state.is_loading = true;

        try {
            // set_location now: populates lines + auto-starts the check (state → in_progress)
            const result = await this.orm.call(
                'inventory.check',
                'set_location',
                [this.state.check_id, location_id],
                {}
            );

            if (result && result.success) {
                this.state.check_data = result;
                this.state.lines = result.lines || [];
                this.state.discrepancies = result.discrepancies || [];
            }
        } catch (error) {
            this._showError('Lỗi tải dữ liệu vị trí: ' + error.message);
        } finally {
            this.state.is_loading = false;
        }

        this.state.view = 'scanning';
        this._showNotification(`Đã chọn vị trí: ${location_name}`, 'success');
        this._focusOnBarcodeInput();
    }

    // ========== Barcode Scanning ==========
    async onProductBarcodeInput(event) {
        if (event.key === 'Enter') {
            event.preventDefault();
            await this.scanProduct();
        }
    }

    async scanProduct() {
        const barcode = this.state.product_barcode.trim();
        if (!barcode) return;

        this.state.is_loading = true;
        try {
            const product_result = await this.orm.call(
                'inventory.check',
                'search_product',
                [barcode],
                {}
            );

            if (!product_result.success) {
                this._showError(product_result.error);
                this.state.product_barcode = '';
                return;
            }

            const scan_result = await this.orm.call(
                'inventory.check',
                'register_scan',
                [this.state.check_id, product_result.product_id, this.state.location_id, 1],
                {}
            );

            if (scan_result.success) {
                if (scan_result.warning) {
                    this.state.warning_message = scan_result.error;
                }
                await this._refreshCheckData();
                this._showNotification(
                    `✓ ${product_result.product_name} (SL: ${scan_result.scanned_qty})`,
                    'success'
                );
                this.state.product_barcode = '';
                this._focusOnBarcodeInput();
            } else {
                this._showError(scan_result.error);
            }
        } catch (error) {
            this._showError('Lỗi quét: ' + error.message);
        } finally {
            this.state.is_loading = false;
        }
    }

    // ========== Data Refresh ==========
    async _refreshCheckData() {
        try {
            const result = await this.orm.call(
                'inventory.check',
                'get_or_create_active_check',
                [this.state.device_id, this.state.location_id],
                {}
            );
            if (result.success) {
                this.state.check_data = result;
                this.state.discrepancies = result.discrepancies || [];

                // Preserve qty for line currently being manually edited
                const activeEl = document.activeElement;
                const editingId = (activeEl && activeEl.classList.contains('hlv-qty-input'))
                    ? parseInt(activeEl.dataset.lineId) : null;

                const newLines = result.lines || [];
                if (editingId) {
                    const cur = this.state.lines.find(l => l.id === editingId);
                    this.state.lines = newLines.map(nl => {
                        if (nl.id === editingId && cur) {
                            return Object.assign({}, nl, { scanned_qty: cur.scanned_qty });
                        }
                        return nl;
                    });
                } else {
                    this.state.lines = newLines;
                }
            }
        } catch (error) {
            console.error('Lỗi cập nhật dữ liệu:', error);
        }
    }

    // ========== Line Management ==========
    removeLineHandler(event) {
        const lineId = parseInt(event.target.closest('button').dataset.lineId);
        this.removeLine(lineId);
    }

    async removeLine(line_id) {
        if (!confirm('Bạn chắc chắn muốn xóa dòng này?')) return;

        this.state.is_loading = true;
        try {
            const result = await this.orm.call(
                'inventory.check',
                'remove_line',
                [this.state.check_id, line_id],
                {}
            );
            if (result.success) {
                await this._refreshCheckData();
                this._showNotification('Đã xóa dòng', 'success');
                this._focusOnBarcodeInput();
            }
        } catch (error) {
            this._showError('Lỗi xóa: ' + error.message);
        } finally {
            this.state.is_loading = false;
        }
    }

    // ========== Manual Qty Input ==========
    async onQtyChange(event) {
        const lineId = parseInt(event.target.dataset.lineId);
        const newQty = parseFloat(event.target.value);
        if (isNaN(newQty) || newQty < 0) return;

        // Update local state immediately for reactive difference display
        const line = this.state.lines.find(l => l.id === lineId);
        if (line) {
            line.scanned_qty = newQty;
            line.difference = newQty - line.theoretical_qty;
        }

        try {
            const result = await this.orm.call(
                'inventory.check',
                'update_line_qty',
                [this.state.check_id, lineId, newQty],
                {}
            );
            if (result.success) {
                // Sync authoritative difference from backend
                if (line) line.difference = result.difference;
                // Refresh summary totals without overwriting active input
                await this._refreshCheckData();
            } else {
                this._showError(result.error || 'Lỗi cập nhật số lượng');
            }
        } catch (error) {
            this._showError('Lỗi cập nhật số lượng: ' + error.message);
        }
    }

    // ========== Inline Discrepancy Dialog ==========
    addDiscrepancyHandler(event) {
        const button = event.target.closest('button');
        this.openDiscrepancyDialog(
            parseInt(button.dataset.lineId),
            button.dataset.productName,
            parseFloat(button.dataset.difference)
        );
    }

    openDiscrepancyDialog(line_id, product_name, difference) {
        this.state.discrepancy_dialog = {
            line_id,
            product_name,
            difference,
            reason: '',
            notes: '',
        };
    }

    closeDiscrepancyDialog() {
        this.state.discrepancy_dialog = null;
        this._focusOnBarcodeInput();
    }

    async saveDiscrepancy() {
        const dialog = this.state.discrepancy_dialog;
        if (!dialog.reason) {
            this._showError('Vui lòng chọn lý do chênh lệch');
            return;
        }
        this.state.is_loading = true;
        try {
            const result = await this.orm.call(
                'inventory.check',
                'save_discrepancy',
                [dialog.line_id, dialog.reason, dialog.notes],
                {}
            );
            if (result.success) {
                this._showNotification('Đã ghi nhận lý do chênh lệch', 'success');
                this.state.discrepancy_dialog = null;
                await this._refreshCheckData();
                this._focusOnBarcodeInput();
            } else {
                this._showError(result.error || 'Lỗi lưu chênh lệch');
            }
        } catch (error) {
            this._showError('Lỗi: ' + error.message);
        } finally {
            this.state.is_loading = false;
        }
    }

    // ========== Check Actions ==========
    async confirmCheck() {
        const pending = this.state.lines.filter(
            l => l.difference !== 0 && !l.discrepancy_id
        );
        if (pending.length > 0) {
            this._showError(`Cần ghi nhận lý do chênh lệch cho ${pending.length} sản phẩm`);
            return;
        }
        if (!confirm('Bạn chắc chắn muốn xác nhận kiểm kê?')) return;

        this.state.is_loading = true;
        try {
            await this.orm.call(
                'inventory.check',
                'action_confirm_check',
                [this.state.check_id],
                {}
            );
            this._showNotification('Đã xác nhận kiểm kê', 'success');
            this.state.view = 'summary';
        } catch (error) {
            this._showError('Lỗi xác nhận: ' + error.message);
        } finally {
            this.state.is_loading = false;
        }
    }

    async cancelCheck() {
        if (!confirm('Bạn chắc chắn muốn hủy kiểm kê?')) return;

        this.state.is_loading = true;
        try {
            await this.orm.call(
                'inventory.check',
                'action_cancel',
                [this.state.check_id],
                {}
            );
            this._showNotification('Đã hủy kiểm kê', 'success');
            await this._resetSession();
        } catch (error) {
            this._showError('Lỗi: ' + error.message);
        } finally {
            this.state.is_loading = false;
        }
    }

    async viewCheckForm() {
        try {
            await this.action.doAction({
                type: 'ir.actions.act_window',
                res_model: 'inventory.check',
                res_id: this.state.check_id,
                views: [[false, 'form']],
                view_mode: 'form',
                target: 'current',
            });
        } catch (error) {
            this._showError('Không thể mở form: ' + error.message);
        }
    }

    // ========== Session Reset ==========
    async _resetSession() {
        this.state.check_id = null;
        this.state.location_id = null;
        this.state.location_name = '';
        this.state.check_data = null;
        this.state.view = 'location_select';
        this.state.lines = [];
        this.state.discrepancies = [];
        this.state.discrepancy_dialog = null;
        this.state.active_sessions = [];
        // Create fresh check ready for next location
        await this._restoreSession();
    }

    // ========== Alert Helpers ==========
    clearWarning() { this.state.warning_message = ''; }
    clearError() { this.state.error_message = ''; }

    // ========== Smart Focus ==========
    /**
     * Refocuses the barcode input but respects:
     * - User actively typing in a qty input (.hlv-qty-input)
     * - User in the discrepancy dialog (.hlv-discrepancy-dialog)
     */
    _focusOnBarcodeInput() {
        setTimeout(() => {
            const active = document.activeElement;
            if (active) {
                if (active.classList.contains('hlv-qty-input')) return;
                if (active.closest && active.closest('.hlv-discrepancy-dialog')) return;
            }
            const selector = this.state.view === 'location_select'
                ? '.hlv-input--lg'
                : '.hlv-input--scan';
            const input = document.querySelector(selector);
            if (input) input.focus();
        }, 150);
    }

    // ========== Notification Helpers ==========
    _showError(message) {
        this.state.error_message = message;
        this.notification.add(message, { type: 'danger' });
        setTimeout(() => { this.state.error_message = ''; }, 5000);
    }

    _showNotification(message, type = 'info') {
        this.notification.add(message, { type });
    }
}

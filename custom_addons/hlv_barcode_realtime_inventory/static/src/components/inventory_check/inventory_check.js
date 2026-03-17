/** @odoo-module */

import { Component, useState, onWillStart, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class InventoryCheckScanner extends Component {
    static template = "hlv_barcode_realtime_inventory.inventory_check";
    static components = {};

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");

        this.cameraVideo = useRef("cameraVideo");
        this._cameraStream = null;
        this._cameraAnimFrame = null;
        this._barcodeDetector = null;
        this._zxingReader = null;
        this._lastScannedCode = '';
        this._lastScanTime = 0;

        this.state = useState({
            // Session
            check_id: null,
            location_id: null,
            location_name: '',

            // Views: home | scanning | daily_stats | settings | approvals | summary | check_detail
            view: 'home',
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

            // Inline discrepancy dialog
            discrepancy_dialog: null,

            // Active sessions
            active_sessions: [],

            // Daily stats
            daily_stats: null,
            stats_date: new Date().toISOString().slice(0, 10),  // YYYY-MM-DD local today

            // Check detail
            check_detail: null,

            // Settings
            settings: null,

            // Approvals list (manager)
            pending_approvals: [],

            // Confirm dialog
            confirm_dialog: false,

            // Pause dialog (back button from scanning)
            pause_dialog: false,

            // Last scanned line (flash highlight)
            last_scanned_line_id: null,

            // Location Viewer
            location_viewer: null,  // { location_name, items: [] }
            location_viewer_barcode: '',

            // Camera
            camera_active: false,
            camera_status: '',
            camera_status_type: 'info',
            camera_mode: 'product',  // 'product' | 'location' | 'location_viewer'

            // Device
            device_id: this._generateDeviceId(),
        });

        onWillStart(async () => {
            await this._loadHome();
        });

        onMounted(() => {
            this._focusOnBarcodeInput();
            // Whenever focus leaves any element, restore it to the right input
            // This keeps the hidden location input always ready for hardware scanners
            this._globalFocusOut = () => {
                // Small delay so the newly-focused element has time to receive focus
                setTimeout(() => {
                    if (this.state.camera_active) return;              // camera modal handles its own focus
                    if (this.state.is_loading) return;
                    const active = document.activeElement;
                    if (!active || active.tagName === 'BODY' || active.tagName === 'HTML') {
                        this._focusOnBarcodeInput();
                        return;
                    }
                    // If focus went to a known interactive element, leave it alone
                    // but still refocus hidden input after button actions on home/no-location screens
                    const needsHidden = !this.state.location_id &&
                        (this.state.view === 'home' || this.state.view === 'scanning');
                    if (needsHidden && !active.classList.contains('hlv-location-hidden-input')) {
                        const isInteractive = active.tagName === 'INPUT' ||
                            active.tagName === 'TEXTAREA' ||
                            active.tagName === 'SELECT';
                        // Only refocus if focus went to a button and has already settled
                        if (!isInteractive) {
                            this._focusOnBarcodeInput();
                        }
                    }
                }, 200);
            };
            document.addEventListener('focusout', this._globalFocusOut);
        });

        onWillUnmount(() => {
            this._stopCameraStream();
            if (this._globalFocusOut) {
                document.removeEventListener('focusout', this._globalFocusOut);
            }
        });
    }

    // ========== Device ==========
    _generateDeviceId() {
        let id = localStorage.getItem('hlv_device_id');
        if (!id) {
            id = 'dev_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
            localStorage.setItem('hlv_device_id', id);
        }
        return id;
    }

    // ========== Home / Init ==========
    async _loadHome() {
        this.state.is_loading = true;
        try {
            const [sessions, settings, stats] = await Promise.all([
                this.orm.call('inventory.check', 'get_active_sessions', [], {}),
                this.orm.call('inventory.check', 'get_scanner_settings', [], {}),
                this.orm.call('inventory.check', 'get_daily_stats', [], {}),
            ]);
            this.state.active_sessions = sessions || [];
            this.state.settings = settings || {};
            this.state.daily_stats = stats || null;
        } catch (error) {
            this._showError('Lỗi tải dữ liệu: ' + error.message);
        } finally {
            this.state.is_loading = false;
        }
    }

    // ========== Navigation ==========
    requestGoHome() {
        // If there's an active check in progress, show pause confirmation
        if (this.state.check_id) {
            this.state.pause_dialog = true;
        } else {
            this.goHome();
        }
    }

    closePauseDialog() {
        this.state.pause_dialog = false;
    }

    goHome() {
        this.state.pause_dialog = false;
        this.state.view = 'home';
        this.state.check_id = null;
        this.state.location_id = null;
        this.state.location_name = '';
        this.state.check_data = null;
        this.state.lines = [];
        this.state.discrepancies = [];
        this.state.confirm_dialog = false;
        this._loadHome();
    }

    goToScanning() {
        this.state.view = 'scanning';
        this._focusOnBarcodeInput();
    }

    goToDailyStats() {
        this.state.stats_date = new Date().toISOString().slice(0, 10);
        this.state.view = 'daily_stats';
        this._loadDailyStats();
    }

    goToSettings() {
        if (!this.state.settings || !this.state.settings.is_manager) {
            this._showError('Chỉ quản lý kho mới có quyền truy cập');
            return;
        }
        this.state.view = 'settings';
    }

    goToApprovals() {
        if (!this.state.settings || !this.state.settings.is_manager) {
            this._showError('Chỉ quản lý kho mới có quyền truy cập');
            return;
        }
        this.state.view = 'approvals';
        this._loadApprovals();
    }

    goToLocationViewer() {
        this.state.location_viewer = null;
        this.state.location_viewer_barcode = '';
        this.state.view = 'location_viewer';
        setTimeout(() => {
            const inp = document.querySelector('.hlv-lv-input');
            if (inp) inp.focus();
        }, 300);
    }

    async onLocationViewerInput(event) {
        if (event.key !== 'Enter') return;
        const barcode = this.state.location_viewer_barcode.trim();
        if (!barcode) return;
        await this._loadLocationStock(barcode);
    }

    async onLocationViewerCameraResult(barcode) {
        this.state.location_viewer_barcode = barcode;
        await this._loadLocationStock(barcode);
    }

    async _loadLocationStock(barcode) {
        this.state.is_loading = true;
        try {
            const r = await this.orm.call('inventory.check', 'get_location_stock', [barcode], {});
            if (r.success) {
                this.state.location_viewer = r;
                this.state.location_viewer_barcode = '';
            } else {
                this._showError(r.error);
                this.state.location_viewer = null;
            }
        } catch (error) {
            this._showError('Lỗi: ' + error.message);
        } finally {
            this.state.is_loading = false;
        }
    }

    openCameraForLocationViewer() {
        this.state.camera_mode = 'location_viewer';
        this.openCamera('location_viewer');
    }

    // ========== Session Resume ==========
    async resumeCheck(check_id) {
        this.state.is_loading = true;
        try {
            const result = await this.orm.call('inventory.check', 'resume_check', [check_id], {});
            if (result.success) {
                this._applyCheckData(result);
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

    // ========== New Check ==========
    startNewCheck() {
        // Reset hoàn toàn — phiên mới sẽ được tạo khi user chọn vị trí
        this.state.check_id = null;
        this.state.location_id = null;
        this.state.location_name = '';
        this.state.check_data = null;
        this.state.lines = [];
        this.state.discrepancies = [];
        this.state.location_barcode = '';
        this.state.product_barcode = '';
        this.state.confirm_dialog = false;
        this.state.view = 'scanning';
        this._focusOnBarcodeInput();
    }

    _applyCheckData(result) {
        this.state.check_id = result.check_id;
        this.state.location_id = result.location_id;
        this.state.location_name = result.location_name;
        this.state.check_data = result;
        this.state.lines = result.lines || [];
        this.state.discrepancies = result.discrepancies || [];
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
            this._showError('Vui lòng quét mã vị trí');
            return;
        }
        this.state.location_barcode = '';  // always clear immediately
        this.state.is_loading = true;
        try {
            const result = await this.orm.call(
                'inventory.check', 'search_location', [barcode], {}
            );
            if (result.success) {
                const checkResult = await this.orm.call(
                    'inventory.check', 'create_new_check',
                    [this.state.device_id], {}
                );
                if (checkResult.success) {
                    this.state.check_id = checkResult.check_id;
                    this.state.check_data = checkResult;
                } else {
                    this._showError('Lỗi tạo phiên kiểm kê');
                    return;
                }
                await this._setLocation(result.location_id, result.location_name);
                this._beepSuccess();
            } else {
                this._beepError();
                this._showError(result.error || 'Không tìm thấy vị trí');
            }
        } catch (error) {
            this._beepError();
            this._showError('Lỗi: ' + error.message);
        } finally {
            this.state.is_loading = false;
        }
    }

    async _setLocation(location_id, location_name) {
        this.state.is_loading = true;
        try {
            const result = await this.orm.call(
                'inventory.check', 'set_location',
                [this.state.check_id, location_id], {}
            );
            if (result && result.success) {
                this._applyCheckData(result);
                this.state.view = 'scanning';
                this._showNotification(`Đã chọn: ${location_name}`, 'success');
                this._focusOnBarcodeInput();
            } else {
                this._showError(result.error || 'Lỗi thiết lập vị trí');
            }
        } catch (error) {
            this._showError('Lỗi tải dữ liệu vị trí: ' + error.message);
        } finally {
            this.state.is_loading = false;
        }
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
        // Small delay for UI to settle (camera continuous mode)
        await new Promise(r => setTimeout(r, 100));
        // Don't block UI with loading overlay for scans
        try {
            const pr = await this.orm.call(
                'inventory.check', 'search_product', [barcode], {}
            );
            if (!pr.success) {
                this._showError(pr.error);
                this.state.product_barcode = '';
                return;
            }
            const sr = await this.orm.call(
                'inventory.check', 'register_scan',
                [this.state.check_id, pr.product_id, this.state.location_id, 1], {}
            );
            if (sr.success) {
                if (sr.warning) this.state.warning_message = sr.error;
                this._refreshCheckData();
                this._beepSuccess();
                this._showNotification(`✓ ${pr.product_name} (SL: ${sr.scanned_qty})`, 'success');
                this.state.last_scanned_line_id = sr.line_id;
                setTimeout(() => { this.state.last_scanned_line_id = null; }, 1200);
                setTimeout(() => {
                    const el = document.querySelector(`.hlv-product-row[data-line-id="${sr.line_id}"]`);
                    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }, 50);
                this.state.product_barcode = '';
                this._focusOnBarcodeInput();
            } else {
                this._showError(sr.error);
            }
        } catch (error) {
            this._showError('Lỗi quét: ' + error.message);
        }
    }

    // ========== Data Refresh ==========
    async _refreshCheckData() {
        if (!this.state.check_id) return;
        try {
            const result = await this.orm.call(
                'inventory.check', 'get_check_data',
                [this.state.check_id], {}
            );
            if (result.success) {
                this.state.check_data = result;
                this.state.discrepancies = result.discrepancies || [];
                const activeEl = document.activeElement;
                const editingId = (activeEl && activeEl.classList.contains('hlv-qty-input'))
                    ? parseInt(activeEl.dataset.lineId) : null;
                const newLines = result.lines || [];
                if (editingId) {
                    const cur = this.state.lines.find(l => l.id === editingId);
                    this.state.lines = newLines.map(nl =>
                        (nl.id === editingId && cur)
                            ? Object.assign({}, nl, { scanned_qty: cur.scanned_qty })
                            : nl
                    );
                } else {
                    this.state.lines = newLines;
                }
            }
        } catch (error) {
            console.error('Lỗi cập nhật:', error);
        }
    }

    // ========== Line Management ==========
    removeLineHandler(event) {
        const lineId = parseInt(event.target.closest('button').dataset.lineId);
        this.removeLine(lineId);
    }

    async removeLine(line_id) {
        if (!confirm('Xóa dòng này?')) return;
        this.state.is_loading = true;
        try {
            const r = await this.orm.call(
                'inventory.check', 'remove_line', [this.state.check_id, line_id], {}
            );
            if (r.success) {
                await this._refreshCheckData();
                this._showNotification('Đã xóa', 'success');
                this._focusOnBarcodeInput();
            }
        } catch (error) {
            this._showError('Lỗi xóa: ' + error.message);
        } finally {
            this.state.is_loading = false;
        }
    }

    // ========== Manual Qty ==========
    async onQtyChange(event) {
        const lineId = parseInt(event.target.dataset.lineId);
        const newQty = parseFloat(event.target.value);
        if (isNaN(newQty) || newQty < 0) return;
        const line = this.state.lines.find(l => l.id === lineId);
        if (line) {
            line.scanned_qty = newQty;
            line.difference = newQty - line.theoretical_qty;
        }
        try {
            const r = await this.orm.call(
                'inventory.check', 'update_line_qty',
                [this.state.check_id, lineId, newQty], {}
            );
            if (r.success) {
                if (line) line.difference = r.difference;
                await this._refreshCheckData();
            } else {
                this._showError(r.error || 'Lỗi cập nhật số lượng');
            }
        } catch (error) {
            this._showError('Lỗi: ' + error.message);
        }
    }

    // ========== Discrepancy Dialog ==========
    addDiscrepancyHandler(event) {
        const btn = event.target.closest('button');
        const line_id = parseInt(btn.dataset.lineId);
        const product_name = btn.dataset.productName;
        const difference = parseFloat(btn.dataset.difference);
        if (this.state.settings && this.state.settings.skip_discrepancy_reason) {
            this._autoSaveDiscrepancy(line_id);
        } else {
            this.openDiscrepancyDialog(line_id, product_name, difference);
        }
    }

    async _autoSaveDiscrepancy(line_id) {
        try {
            const r = await this.orm.call('inventory.check', 'save_discrepancy', [line_id, 'kiem_ton', ''], {});
            if (r.success) {
                this._showNotification('Đã ghi nhận: Kiểm tồn', 'success');
                await this._refreshCheckData();
                this._focusOnBarcodeInput();
            } else {
                this._showError(r.error || 'Lỗi');
            }
        } catch (error) {
            this._showError('Lỗi: ' + error.message);
        }
    }

    openDiscrepancyDialog(line_id, product_name, difference) {
        this.state.discrepancy_dialog = { line_id, product_name, difference, reason: '', notes: '' };
    }

    closeDiscrepancyDialog() {
        this.state.discrepancy_dialog = null;
        this._focusOnBarcodeInput();
    }

    async saveDiscrepancy() {
        const d = this.state.discrepancy_dialog;
        if (!d.reason) { this._showError('Vui lòng chọn lý do'); return; }
        this.state.is_loading = true;
        try {
            const r = await this.orm.call(
                'inventory.check', 'save_discrepancy', [d.line_id, d.reason, d.notes], {}
            );
            if (r.success) {
                this._showNotification('Đã ghi nhận lý do', 'success');
                this.state.discrepancy_dialog = null;
                await this._refreshCheckData();
                this._focusOnBarcodeInput();
            } else {
                this._showError(r.error || 'Lỗi');
            }
        } catch (error) {
            this._showError('Lỗi: ' + error.message);
        } finally {
            this.state.is_loading = false;
        }
    }

    // ========== Confirm Check (inline) ==========
    async openConfirmDialog() {
        const pending = this.state.lines.filter(l => l.difference !== 0 && !l.discrepancy_id);
        if (pending.length > 0) {
            if (this.state.settings && this.state.settings.skip_discrepancy_reason) {
                this.state.is_loading = true;
                try {
                    for (const l of pending) {
                        await this.orm.call('inventory.check', 'save_discrepancy', [l.id, 'kiem_ton', ''], {});
                    }
                    await this._refreshCheckData();
                } catch (error) {
                    this._showError('Lỗi tự động ghi nhận: ' + error.message);
                    this.state.is_loading = false;
                    return;
                } finally {
                    this.state.is_loading = false;
                }
            } else {
                this._showError(`Cần ghi nhận lý do chênh lệch cho ${pending.length} sản phẩm`);
                return;
            }
        }
        this.state.confirm_dialog = true;
    }

    closeConfirmDialog() {
        this.state.confirm_dialog = false;
    }

    async confirmCheck() {
        this.state.is_loading = true;
        this.state.confirm_dialog = false;
        try {
            await this.orm.call(
                'inventory.check', 'action_confirm_check', [this.state.check_id], {}
            );
            const approvalRequired = this.state.settings && this.state.settings.approval_required;
            if (approvalRequired) {
                this._showNotification('Đã gửi phiên kiểm kê chờ duyệt', 'success');
            } else {
                this._showNotification('Đã xác nhận kiểm kê', 'success');
            }
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
                'inventory.check', 'action_cancel', [this.state.check_id], {}
            );
            this._showNotification('Đã hủy', 'success');
            this.goHome();
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
            this._showError('Lỗi mở form: ' + error.message);
        }
    }

    // ========== Daily Stats ==========
    async _loadDailyStats() {
        this.state.is_loading = true;
        try {
            const r = await this.orm.call('inventory.check', 'get_daily_stats', [], { date_str: this.state.stats_date });
            if (r.success) this.state.daily_stats = r;
        } catch (error) {
            this._showError('Lỗi tải thống kê: ' + error.message);
        } finally {
            this.state.is_loading = false;
        }
    }

    _statsDateLabel() {
        const today = new Date().toISOString().slice(0, 10);
        if (this.state.stats_date === today) return 'Hôm Nay';
        const [y, m, d] = this.state.stats_date.split('-');
        return `${d}/${m}/${y}`;
    }

    statsPrevDay() {
        const d = new Date(this.state.stats_date);
        d.setDate(d.getDate() - 1);
        this.state.stats_date = d.toISOString().slice(0, 10);
        this._loadDailyStats();
    }

    statsNextDay() {
        const today = new Date().toISOString().slice(0, 10);
        const d = new Date(this.state.stats_date);
        d.setDate(d.getDate() + 1);
        const next = d.toISOString().slice(0, 10);
        if (next > today) return;
        this.state.stats_date = next;
        this._loadDailyStats();
    }

    async openCheckDetail(ev) {
        const checkId = parseInt(ev.currentTarget.dataset.id, 10);
        if (!checkId) return;
        this.state.is_loading = true;
        try {
            const r = await this.orm.call('inventory.check', 'get_check_detail', [checkId], {});
            if (r.success) {
                this.state.check_detail = r;
                this.state.view = 'check_detail';
            } else {
                this._showError(r.error || 'Lỗi tải chi tiết phiên');
            }
        } catch (error) {
            this._showError('Lỗi: ' + error.message);
        } finally {
            this.state.is_loading = false;
        }
    }

    goBackToStats() {
        this.state.view = 'daily_stats';
        this.state.check_detail = null;
    }

    // ========== Settings ==========
    async toggleApprovalRequired() {
        const s = this.state.settings;
        s.approval_required = !s.approval_required;
        await this._saveSettings();
    }

    async toggleAutoConfirm() {
        const s = this.state.settings;
        s.auto_confirm = !s.auto_confirm;
        await this._saveSettings();
    }

    async toggleSkipDiscrepancyReason() {
        const s = this.state.settings;
        s.skip_discrepancy_reason = !s.skip_discrepancy_reason;
        await this._saveSettings();
    }

    async _saveSettings() {
        const s = this.state.settings;
        try {
            const r = await this.orm.call(
                'inventory.check', 'save_scanner_settings',
                [s.approval_required, s.auto_confirm, s.skip_discrepancy_reason], {}
            );
            if (r.success) {
                this._showNotification('Đã lưu cài đặt', 'success');
            } else {
                this._showError(r.error);
            }
        } catch (error) {
            this._showError('Lỗi: ' + error.message);
        }
    }

    // ========== Approvals ==========
    async _loadApprovals() {
        this.state.is_loading = true;
        try {
            const r = await this.orm.call('inventory.check', 'get_pending_approvals', [], {});
            this.state.pending_approvals = r || [];
        } catch (error) {
            this._showError('Lỗi tải: ' + error.message);
        } finally {
            this.state.is_loading = false;
        }
    }

    async approveCheck(check_id) {
        this.state.is_loading = true;
        try {
            const r = await this.orm.call('inventory.check', 'approve_check', [check_id], {});
            if (r.success) {
                this._showNotification('Đã duyệt', 'success');
                await this._loadApprovals();
            } else {
                this._showError(r.error);
            }
        } catch (error) {
            this._showError('Lỗi: ' + error.message);
        } finally {
            this.state.is_loading = false;
        }
    }

    async rejectCheck(check_id) {
        if (!confirm('Từ chối phiên này?')) return;
        this.state.is_loading = true;
        try {
            const r = await this.orm.call('inventory.check', 'reject_check', [check_id], {});
            if (r.success) {
                this._showNotification('Đã từ chối', 'info');
                await this._loadApprovals();
            } else {
                this._showError(r.error);
            }
        } catch (error) {
            this._showError('Lỗi: ' + error.message);
        } finally {
            this.state.is_loading = false;
        }
    }

    // ========== Helpers ==========
    clearWarning() { this.state.warning_message = ''; }
    clearError() { this.state.error_message = ''; }

    _focusOnBarcodeInput() {
        setTimeout(() => {
            const active = document.activeElement;
            if (active) {
                const tag = active.tagName;
                if (active.classList.contains('hlv-qty-input')) return;
                if (active.classList.contains('hlv-lv-input')) return;
                if (active.closest && active.closest('.hlv-discrepancy-dialog')) return;
                if (active.closest && active.closest('.hlv-confirm-dialog')) return;
                // Don't steal from non-scan inputs (qty, search, settings, etc.)
                if ((tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') &&
                    !active.classList.contains('hlv-input--scan') &&
                    !active.classList.contains('hlv-input--lg') &&
                    !active.classList.contains('hlv-location-hidden-input')) return;
            }
            if (this.state.view === 'location_viewer') {
                const lvInput = document.querySelector('.hlv-lv-input');
                if (lvInput && document.activeElement !== lvInput) lvInput.focus();
                return;
            }
            const selector = !this.state.location_id
                ? '.hlv-location-hidden-input'
                : '.hlv-input--scan';
            const input = document.querySelector(selector);
            if (input && document.activeElement !== input) input.focus();
        }, 80);
    }

    focusLocationInput() {
        const input = document.querySelector('.hlv-location-hidden-input');
        if (input) input.focus();
    }

    onScanAreaClick(ev) {
        // Re-focus the barcode input whenever the user taps empty space or a product row
        // so scanning always works without needing to manually click the input
        const tag = ev.target.tagName;
        // Let buttons/inputs/selects handle their own focus
        if (tag === 'BUTTON' || tag === 'A' || tag === 'INPUT' ||
            tag === 'TEXTAREA' || tag === 'SELECT') return;
        if (ev.target.closest && ev.target.closest('button, a')) return;
        this._focusOnBarcodeInput();
    }

    // ========== Camera Scanning ==========
    openCameraForLocation() {
        this.openCamera('location');
    }

    async openCamera(mode = 'product') {
        this.state.camera_mode = mode;
        this._lastScannedCode = '';
        this._lastScanTime = 0;
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            this._showError('Trình duyệt không hỗ trợ camera. Vui lòng dùng Chrome (Android) hoặc Safari 14.3+ (iPhone).');
            return;
        }

        this.state.camera_active = true;
        this.state.camera_status = 'Đang khởi động camera...';
        this.state.camera_status_type = 'info';

        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                video: {
                    facingMode: { ideal: 'environment' },
                    width: { ideal: 1280 },
                    height: { ideal: 720 },
                }
            });
            this._cameraStream = stream;

            // Wait for OWL to render the <video> element
            await new Promise(r => setTimeout(r, 150));
            const video = this.cameraVideo.el;
            if (!video) { this._stopCameraStream(); return; }

            // iOS requires muted + playsinline for autoplay
            video.muted = true;
            video.srcObject = stream;
            try { await video.play(); } catch(e) { /* autoplay attribute handles it */ }

            this.state.camera_status = '';

            if (window.BarcodeDetector) {
                // Native API: Chrome/Android
                const supported = await window.BarcodeDetector.getSupportedFormats();
                this._barcodeDetector = new window.BarcodeDetector({ formats: supported });
                this._scanLoop();
            } else {
                // Fallback: ZXing (iOS Safari, Firefox)
                this.state.camera_status = 'Đang tải thư viện quét...';
                const loaded = await this._ensureZXing();
                if (!loaded) {
                    this.state.camera_status = 'Không thể tải thư viện quét. Kiểm tra kết nối mạng.';
                    this.state.camera_status_type = 'error';
                    return;
                }
                this.state.camera_status = '';
                this._startZXingScan(stream, video);
            }
        } catch (err) {
            this.state.camera_status = 'Không thể mở camera: ' + (err.message || err);
            this.state.camera_status_type = 'error';
        }
    }

    async _ensureZXing() {
        if (window.ZXing) return true;
        return new Promise((resolve) => {
            const s = document.createElement('script');
            s.src = '/hlv_barcode_realtime_inventory/static/lib/zxing/zxing.min.js';
            s.onload = () => resolve(true);
            s.onerror = () => resolve(false);
            document.head.appendChild(s);
        });
    }

    _startZXingScan(stream, video) {
        if (!this.state.camera_active || !window.ZXing) return;
        const reader = new window.ZXing.BrowserMultiFormatReader();
        this._zxingReader = reader;
        // decodeFromStream does continuous scanning from a live MediaStream
        reader.decodeFromStream(stream, video, (result, err) => {
            if (!this.state.camera_active) return;
            if (result) {
                const code = result.getText();
                const now = Date.now();
                if (code !== this._lastScannedCode || now - this._lastScanTime > 1500) {
                    this._lastScannedCode = code;
                    this._lastScanTime = now;
                    this._processCameraBarcode(code);
                }
            }
        });
    }

    _scanLoop() {
        if (!this.state.camera_active) return;
        const video = this.cameraVideo.el;
        if (!video || video.readyState < 2) {
            this._cameraAnimFrame = requestAnimationFrame(() => this._scanLoop());
            return;
        }

        this._barcodeDetector.detect(video).then(barcodes => {
            if (!this.state.camera_active) return;
            if (barcodes.length > 0) {
                const code = barcodes[0].rawValue;
                const now = Date.now();
                // Debounce: skip same code within 1.5 s to avoid double-fire
                if (code !== this._lastScannedCode || now - this._lastScanTime > 1500) {
                    this._lastScannedCode = code;
                    this._lastScanTime = now;
                    this._processCameraBarcode(code);
                }
            }
            // Always continue scanning (continuous mode)
            this._cameraAnimFrame = requestAnimationFrame(() => this._scanLoop());
        }).catch(() => {
            if (this.state.camera_active) {
                this._cameraAnimFrame = requestAnimationFrame(() => this._scanLoop());
            }
        });
    }

    _processCameraBarcode(code) {
        if (this.state.camera_mode === 'location_viewer') {
            this.state.camera_active = false;
            this.state.camera_status = '';
            this._stopCameraStream();
            this.onLocationViewerCameraResult(code);
        } else if (this.state.camera_mode === 'location') {
            // Close camera first, then navigate to location
            this.state.camera_active = false;
            this.state.camera_status = '';
            this._stopCameraStream();
            this.state.location_barcode = code;
            this.selectLocationByBarcode();
        } else {
            // Product mode: keep camera open, show brief flash
            this.state.camera_status = '\u2713 ' + code;
            this.state.camera_status_type = 'info';
            setTimeout(() => {
                if (this.state.camera_active) this.state.camera_status = '';
            }, 900);
            this.state.product_barcode = code;
            this.scanProduct();
        }
    }

    closeCamera() {
        this.state.camera_active = false;
        this.state.camera_status = '';
        this._stopCameraStream();
        this._focusOnBarcodeInput();
    }

    _stopCameraStream() {
        if (this._cameraAnimFrame) {
            cancelAnimationFrame(this._cameraAnimFrame);
            this._cameraAnimFrame = null;
        }
        if (this._zxingReader) {
            try { this._zxingReader.reset(); } catch(e) {}
            this._zxingReader = null;
        }
        if (this._cameraStream) {
            this._cameraStream.getTracks().forEach(t => t.stop());
            this._cameraStream = null;
        }
        this._barcodeDetector = null;
    }

    _showError(message) {
        this.state.error_message = message;
        this.notification.add(message, { type: 'danger' });
        setTimeout(() => { this.state.error_message = ''; }, 5000);
    }

    // ========== Audio Feedback ==========
    _beepSuccess() {
        try {
            if (!this._successAudio) {
                this._successAudio = new Audio('/custom_barcode_scan_redirect/static/src/sound/success.mp3');
            }
            this._successAudio.currentTime = 0;
            this._successAudio.play().catch(() => {});
        } catch(e) {}
    }

    _beepError() {
        try {
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.type = 'square';
            osc.frequency.setValueAtTime(220, ctx.currentTime);    // A3
            gain.gain.setValueAtTime(0.2, ctx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.25);
            osc.start(ctx.currentTime);
            osc.stop(ctx.currentTime + 0.25);
            osc.onended = () => ctx.close();
        } catch(e) {}
    }

    _showNotification(message, type = 'info') {
        this.notification.add(message, { type });
    }
}

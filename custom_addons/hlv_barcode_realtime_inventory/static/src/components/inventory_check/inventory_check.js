/** @odoo-module */

import { Component, useState, onWillStart, onMounted } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { BlockUI } from "@web/core/ui/block_ui";

export class InventoryCheckScanner extends Component {
    static template = "hlv_barcode_realtime_inventory.inventory_check";
    static components = { BlockUI };

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
            view: 'location_select', // location_select, scanning, summary
            is_loading: false,
            error_message: '',
            warning_message: '',
            
            // Data
            check_data: null,
            lines: [],
            discrepancies: [],
            pending_moves: [],
            
            // Input
            location_barcode: '',
            product_barcode: '',
            manual_qty: '',
            
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
            const result = await this.orm.call(
                'inventory.check',
                'get_or_create_active_check',
                [this.state.device_id],
                {}
            );
            
            if (result.success) {
                this.state.check_id = result.check_id;
                this.state.location_id = result.location_id;
                this.state.location_name = result.location_name;
                this.state.check_data = result;
                this.state.lines = result.lines;
                this.state.discrepancies = result.discrepancies;
                
                if (this.state.location_id) {
                    this.state.view = 'scanning';
                    this._focusOnBarcodeInput();
                }
            }
        } catch (error) {
            this._showError('Lỗi khôi phục session: ' + error.message);
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
                this._showError(result.error);
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
        
        await this.orm.call(
            'inventory.check',
            'set_location',
            [this.state.check_id, location_id],
            {}
        );
        
        this.state.view = 'scanning';
        this._focusOnBarcodeInput();
        
        this._showNotification(`Đã chọn vị trí: ${location_name}`, 'success');
    }

    // ========== Barcode Input ==========
    async onProductBarcodeInput(event) {
        if (event.key === 'Enter') {
            event.preventDefault();
            await this.scanProduct();
        }
    }

    async scanProduct() {
        const barcode = this.state.product_barcode.trim();
        if (!barcode) {
            this._showError('Vui lòng quét hoặc nhập mã sản phẩm');
            return;
        }

        this.state.is_loading = true;
        try {
            // Tìm sản phẩm
            const product_result = await this.orm.call(
                'inventory.check',
                'search_product',
                [barcode],
                {}
            );
            
            if (!product_result.success) {
                this._showError(product_result.error);
                this.state.product_barcode = '';
                this.state.is_loading = false;
                return;
            }

            const product_id = product_result.product_id;

            // Đăng ký quét
            const scan_result = await this.orm.call(
                'inventory.check',
                'register_scan',
                [this.state.check_id, product_id, this.state.location_id, 1],
                {}
            );
            
            if (scan_result.success) {
                // Cảnh báo nếu có outbound pending
                if (scan_result.warning) {
                    this.state.warning_message = scan_result.error;
                }
                
                // Cập nhật dữ liệu
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
                this.state.lines = result.lines;
                this.state.discrepancies = result.discrepancies;
            }
        } catch (error) {
            console.error('Lỗi cập nhật dữ liệu:', error);
        }
    }

    // ========== Line Management ==========
    removeLineHandler(event) {
        const lineId = event.target.closest('button').dataset.lineId;
        this.removeLine(parseInt(lineId));
    }

    addDiscrepancyHandler(event) {
        const button = event.target.closest('button');
        const lineId = parseInt(button.dataset.lineId);
        const productName = button.dataset.productName;
        const difference = parseFloat(button.dataset.difference);
        this.addDiscrepancy(lineId, productName, difference);
    }

    clearWarning() {
        this.state.warning_message = '';
    }

    clearError() {
        this.state.error_message = '';
    }

    async updateLineQty(line_id, new_qty) {
        this.state.is_loading = true;
        try {
            const result = await this.orm.call(
                'inventory.check',
                'update_line_qty',
                [this.state.check_id, line_id, parseFloat(new_qty)],
                {}
            );
            
            if (result.success) {
                await this._refreshCheckData();
                this._showNotification('Cập nhật số lượng thành công', 'success');
            }
        } catch (error) {
            this._showError('Lỗi cập nhật: ' + error.message);
        } finally {
            this.state.is_loading = false;
        }
    }

    async removeLine(line_id) {
        if (!confirm('Bạn chắc chắn muốn xóa dòng này?')) {
            return;
        }

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
            }
        } catch (error) {
            this._showError('Lỗi xóa: ' + error.message);
        } finally {
            this.state.is_loading = false;
        }
    }

    // ========== Discrepancy Management ==========
    async addDiscrepancy(line_id, product_name, difference) {
        // Mở dialog để ghi nhận chênh lệch
        const action = await this.orm.call(
            'inventory.check.line',
            'action_open_discrepancy',
            [line_id],
            {}
        );
        
        if (action) {
            await this.action.doAction(action);
            // Reload sau khi đóng dialog
            setTimeout(() => this._refreshCheckData(), 1000);
        }
    }

    async removeLine(line_id) {
        if (!confirm('Bạn chắc chắn muốn xóa dòng này?')) {
            return;
        }

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
            }
        } catch (error) {
            this._showError('Lỗi xóa: ' + error.message);
        } finally {
            this.state.is_loading = false;
        }
    }

    // ========== Discrepancy Management ==========
    async addDiscrepancy(line_id, product_name, difference) {
        // Mở dialog để ghi nhận chênh lệch
        const action = await this.orm.call(
            'inventory.check.line',
            'action_open_discrepancy',
            [line_id],
            {}
        );
        
        if (action) {
            await this.action.doAction(action);
            // Reload sau khi đóng dialog
            setTimeout(() => this._refreshCheckData(), 1000);
        }
    }

    // ========== Actions ==========
    async startCheck() {
        this.state.is_loading = true;
        try {
            await this.orm.call(
                'inventory.check',
                'action_start_check',
                [this.state.check_id],
                {}
            );
            
            this._showNotification('Đã bắt đầu kiểm kê', 'success');
        } catch (error) {
            this._showError('Lỗi: ' + error.message);
        } finally {
            this.state.is_loading = false;
        }
    }

    async confirmCheck() {
        // Kiểm tra xem có chênh lệch chưa được ghi nhận
        const pending_discrepancies = this.state.lines.filter(
            line => line.difference !== 0 && !line.discrepancy_id
        );
        
        if (pending_discrepancies.length > 0) {
            this._showError(
                `Cần ghi nhận lý do chênh lệch cho ${pending_discrepancies.length} sản phẩm`
            );
            return;
        }

        if (!confirm('Bạn chắc chắn muốn xác nhận kiểm kê?')) {
            return;
        }

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
            this._showError('Lỗi: ' + error.message);
        } finally {
            this.state.is_loading = false;
        }
    }

    async cancelCheck() {
        if (!confirm('Bạn chắc chắn muốn hủy kiểm kê?')) {
            return;
        }

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
        await this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: 'inventory.check',
            res_id: this.state.check_id,
            view_mode: 'form',
            target: 'current',
        });
    }

    // ========== Session Management ==========
    async _resetSession() {
        localStorage.removeItem('hlv_check_session');
        this.state.check_id = null;
        this.state.location_id = null;
        this.state.view = 'location_select';
        this.state.lines = [];
        this.state.discrepancies = [];
    }

    // ========== Helper Methods ==========
    _focusOnBarcodeInput() {
        setTimeout(() => {
            const input = document.querySelector(
                this.state.view === 'location_select' 
                    ? 'input.location-barcode' 
                    : 'input.product-barcode'
            );
            if (input) input.focus();
        }, 100);
    }

    _showError(message) {
        this.state.error_message = message;
        this.notification.add(message, { type: 'danger' });
        setTimeout(() => { this.state.error_message = ''; }, 5000);
    }

    _showWarning(message) {
        this.state.warning_message = message;
        this.notification.add(message, { type: 'warning' });
    }

    _showNotification(message, type = 'info') {
        this.notification.add(message, { type });
    }

    // ========== Computed Properties ==========
    get hasDifferences() {
        return this.state.lines.some(line => line.difference !== 0);
    }

    get pendingDiscrepancies() {
        return this.state.lines.filter(line => line.difference !== 0 && !line.discrepancy_id);
    }

    get checkSummary() {
        if (!this.state.check_data) return null;
        return {
            product_count: this.state.check_data.product_count,
            scan_count: this.state.check_data.scan_count,
            total_theoretical_qty: this.state.check_data.total_theoretical_qty,
            total_scanned_qty: this.state.check_data.total_scanned_qty,
            total_difference: this.state.check_data.total_difference,
        };
    }
}

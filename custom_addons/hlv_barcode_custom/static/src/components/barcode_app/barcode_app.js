/** @odoo-module */

import { Component, useState, onWillStart, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";

export class HlvBarcodeApp extends Component {
    static template = "hlv_barcode_custom.barcode_app";
    static components = {};

    setup() {
        this.notification = useService("notification");
        this.action = useService("action");

        this.barcodeInput = useRef("barcodeInput");
        this.cameraVideo = useRef("cameraVideo");
        this._cameraStream = null;
        this._cameraAnimFrame = null;
        this._barcodeDetector = null;
        this._zxingReader = null;
        this._lastScannedCode = '';
        this._lastScanTime = 0;
        this._audioCtx = null;

        this.state = useState({
            // View: home | picking_list | scanning
            view: 'home',
            is_loading: false,

            // Operation types grouped by warehouse
            warehouses: [],
            // Flat picking types for backward compat
            picking_types: [],
            // Selected warehouse
            selected_warehouse: null,

            // Picking list
            picking_type_filter: null, // { id, name, code }
            pickings: [],

            // Current picking
            picking: null,
            lines: [],

            // Scanning
            barcode_value: '',

            // Product search popup
            search_popup: null, // { product: {...}, locations: [...] }

            // Feedback
            feedback_type: '', // 'success' | 'error' | ''
            feedback_message: '',
            feedback_visible: false,

            // Error popup
            error_popup: null, // { title, message }

            // Numpad popup
            numpad_popup: null, // { move_id, current_qty, demand, product_name }
            numpad_value: '',

            // Camera
            camera_active: false,
            camera_status: '',

            // Config
            config: {
                auto_focus: true,
                sound_success: true,
                sound_error: true,
                strict_delivery: true,
                decimal_step: 0.1,
                camera_enabled: true,
            },

            // Last scanned move_id for highlight
            last_scanned_move_id: null,

            // Location scanning
            scan_config: null, // { scan_source, scan_dest, require_product_scan }
            location_scan_pending: false, // true when waiting for a location scan
            location_scan_type: null, // 'source' | 'dest'
            scanned_location: null, // {id, name, barcode} of active source location
        });

        onWillStart(async () => {
            await this._loadConfig();
        });

        onMounted(() => {
            this._setupAutoFocus();
        });

        onWillUnmount(() => {
            this._stopCamera();
            this._removeAutoFocus();
        });
    }

    // =============== CONFIG ===============
    async _loadConfig() {
        try {
            const [config, pickingTypes] = await Promise.all([
                rpc('/hlv_barcode_custom/get_config', {}),
                rpc('/hlv_barcode_custom/get_picking_types', {}),
            ]);
            if (config) {
                Object.assign(this.state.config, config);
            }
            if (pickingTypes) {
                this.state.warehouses = pickingTypes;
                // Build flat list for backward compat
                const flat = [];
                for (const wh of pickingTypes) {
                    for (const pt of wh.picking_types) {
                        flat.push(pt);
                    }
                }
                this.state.picking_types = flat;
            }
        } catch (e) {
            console.warn('Failed to load barcode config:', e);
        }
    }

    // =============== AUTO FOCUS ===============
    _setupAutoFocus() {
        this._focusInterval = setInterval(() => {
            if (!this.state.config.auto_focus) return;
            if (this.state.camera_active) return;
            if (this.state.numpad_popup) return;
            if (this.state.error_popup) return;
            if (this.state.search_popup) return;
            this._focusBarcodeInput();
        }, 500);

        this._onGlobalFocusOut = () => {
            setTimeout(() => {
                if (this.state.camera_active || this.state.numpad_popup || this.state.error_popup || this.state.search_popup) return;
                const active = document.activeElement;
                if (!active || active.tagName === 'BODY' || active.tagName === 'HTML') {
                    this._focusBarcodeInput();
                }
            }, 200);
        };
        document.addEventListener('focusout', this._onGlobalFocusOut);
    }

    _removeAutoFocus() {
        if (this._focusInterval) clearInterval(this._focusInterval);
        if (this._onGlobalFocusOut) document.removeEventListener('focusout', this._onGlobalFocusOut);
    }

    _focusBarcodeInput() {
        const el = this.barcodeInput.el;
        if (el) {
            el.focus();
        }
    }

    // =============== NAVIGATION ===============
    goHome() {
        this.state.view = 'home';
        this.state.picking = null;
        this.state.lines = [];
        this.state.pickings = [];
        this.state.picking_type_filter = null;
        this.state.selected_warehouse = null;
        this.state.scan_config = null;
        this.state.location_scan_pending = false;
        this.state.location_scan_type = null;
        this.state.scanned_location = null;
        this._stopCamera();
        this._clearFeedback();
        // Reload picking types to get fresh counts
        rpc('/hlv_barcode_custom/get_picking_types', {}).then(types => {
            if (types) {
                this.state.warehouses = types;
                const flat = [];
                for (const wh of types) {
                    for (const pt of wh.picking_types) {
                        flat.push(pt);
                    }
                }
                this.state.picking_types = flat;
            }
        }).catch(() => {});
    }

    async openPickingTypeList(pickingType) {
        this.state.picking_type_filter = pickingType;
        this.state.is_loading = true;
        this.state.view = 'picking_list';
        try {
            const pickings = await rpc('/hlv_barcode_custom/get_pickings', {
                picking_type_id: pickingType.id,
            });
            this.state.pickings = pickings || [];
        } catch (e) {
            this.state.pickings = [];
            this._showError('Lỗi tải danh sách phiếu', e.message || String(e));
        }
        this.state.is_loading = false;
    }

    async openPicking(pickingId) {
        this.state.is_loading = true;
        try {
            const data = await rpc('/hlv_barcode_custom/get_picking_detail', {
                picking_id: pickingId,
            });
            if (data.status === 'error') {
                this._showError(_t('Lỗi'), data.message);
                return;
            }
            this.state.picking = data;
            this.state.lines = data.lines || [];
            this.state.view = 'scanning';
            this.state.config = { ...this.state.config, ...data.config };
            this.state.scan_config = data.scan_config || null;
            this.state.scanned_location = null;
            setTimeout(() => this._focusBarcodeInput(), 100);
        } catch (e) {
            this._showError(_t('Lỗi tải phiếu'), e.message || String(e));
        }
        this.state.is_loading = false;
    }

    goBackFromScan() {
        this._stopCamera();
        if (this.state.picking_type_filter) {
            this.openPickingTypeList(this.state.picking_type_filter);
        } else {
            this.goHome();
        }
    }

    // =============== BARCODE SCANNING ===============
    onBarcodeKeydown(ev) {
        if (ev.key === 'Enter') {
            ev.preventDefault();
            const barcode = this.state.barcode_value.trim();
            if (barcode) {
                this._processScan(barcode);
                this.state.barcode_value = '';
            }
        }
    }

    onBarcodeInput(ev) {
        this.state.barcode_value = ev.target.value;
    }

    async _processScan(barcode) {
        // Debounce: ignore duplicate scans within 1.5s
        const now = Date.now();
        if (barcode === this._lastScannedCode && now - this._lastScanTime < 1500) {
            return;
        }
        this._lastScannedCode = barcode;
        this._lastScanTime = now;

        if (this.state.view === 'scanning' && this.state.picking) {
            // Inside a picking → scan products
            await this._scanOnPicking(barcode);
        } else {
            // Home or picking list → try to find a picking first, then product
            await this._scanGlobal(barcode);
        }
    }

    async _scanGlobal(barcode) {
        this.state.is_loading = true;
        try {
            const result = await rpc('/hlv_barcode_custom/scan_global', { barcode });

            if (result.status === 'found' && result.scan_type === 'picking') {
                // Found a picking → open it directly
                this._playSound('success');
                await this.openPicking(result.picking_id);
            } else if (result.status === 'found' && result.scan_type === 'product') {
                // Found a product → show stock info popup
                await this._searchProduct(barcode);
            } else {
                this._showErrorPopup(result.message || `Không tìm thấy phiếu hoặc sản phẩm: ${barcode}`);
                this._playSound('error');
            }
        } catch (e) {
            this._showErrorPopup(e.message || String(e));
            this._playSound('error');
        }
        this.state.is_loading = false;
    }

    async _scanOnPicking(barcode) {
        this.state.is_loading = true;
        this._clearFeedback();

        try {
            // First: check if this is a location barcode (always allow location scan)
            const result = await rpc('/hlv_barcode_custom/scan', {
                picking_id: this.state.picking.id,
                barcode: barcode,
                location_barcode: this.state.scanned_location ? this.state.scanned_location.barcode : null,
            });

            if (result.status === 'location') {
                // Location scanned — set as active source location
                this.state.scanned_location = {
                    id: result.location_id,
                    name: result.location_name,
                    barcode: result.location_barcode,
                };
                this._showFeedback('success', `📍 Vị trí lấy hàng: ${result.location_name}`);
                this._playSound('success');
            } else if (result.status === 'success' || result.status === 'package_success') {
                // Product/package scan — require location first
                if (!this.state.scanned_location) {
                    this._showErrorPopup('Vui lòng quét vị trí nguồn trước khi quét sản phẩm.');
                    this._playSound('error');
                    this.state.is_loading = false;
                    setTimeout(() => this._focusBarcodeInput(), 100);
                    return;
                }
                const locId = this.state.scanned_location.id;
                const locName = this.state.scanned_location.name;

                if (result.status === 'package_success' && result.products) {
                    for (const p of result.products) {
                        if (p.move_id) {
                            this._incrementLineAtLocation(p.move_id, locId, locName, p.quantity_added || 1);
                        }
                    }
                } else if (result.move_id) {
                    const ok = this._incrementLineAtLocation(result.move_id, locId, locName, 1);
                    if (!ok) {
                        this.state.is_loading = false;
                        setTimeout(() => this._focusBarcodeInput(), 100);
                        return;
                    }
                }
                this._showFeedback('success', result.message);
                this._playSound('success');
                this.state.last_scanned_move_id = result.move_id || null;
                if (result.move_id) {
                    setTimeout(() => { this.state.last_scanned_move_id = null; }, 1500);
                }
            } else if (result.status === 'not_found') {
                // Check if user hasn't scanned location yet
                if (!this.state.scanned_location) {
                    this._showErrorPopup('Vui lòng quét vị trí nguồn trước khi quét sản phẩm.');
                    this._playSound('error');
                    this.state.is_loading = false;
                    setTimeout(() => this._focusBarcodeInput(), 100);
                    return;
                }
                await this._searchProduct(barcode);
            } else if (result.status === 'warning') {
                this._showFeedback('error', result.message);
                this._playSound('error');
            } else if (result.status === 'error') {
                this._showErrorPopup(result.message);
                this._playSound('error');
            }
        } catch (e) {
            this._showErrorPopup(e.message || String(e));
            this._playSound('error');
        }

        this.state.is_loading = false;
        setTimeout(() => this._focusBarcodeInput(), 100);
    }

    async _searchProduct(barcode) {
        this.state.is_loading = true;
        try {
            const result = await rpc('/hlv_barcode_custom/search_product', {
                barcode: barcode,
            });
            if (result.status === 'found') {
                this.state.search_popup = result;
                this._playSound('success');
            } else {
                this._showErrorPopup(result.message || `Không tìm thấy: ${barcode}`);
                this._playSound('error');
            }
        } catch (e) {
            this._showErrorPopup(e.message || String(e));
            this._playSound('error');
        }
        this.state.is_loading = false;
    }

    closeSearchPopup() {
        this.state.search_popup = null;
        setTimeout(() => this._focusBarcodeInput(), 100);
    }

    async _refreshPicking() {
        if (!this.state.picking) return;
        try {
            const data = await rpc('/hlv_barcode_custom/get_picking_detail', {
                picking_id: this.state.picking.id,
            });
            if (data && data.lines) {
                // Preserve local quantity_done (scanned in this session), don't reset from server
                const localQtyMap = {};
                for (const line of this.state.lines) {
                    localQtyMap[line.move_id] = line.quantity_done || 0;
                }
                for (const line of data.lines) {
                    if (localQtyMap[line.move_id] !== undefined) {
                        line.quantity_done = localQtyMap[line.move_id];
                    }
                }
                this.state.picking = { ...this.state.picking, ...data };
                this.state.lines = data.lines;
            }
        } catch (e) {
            console.warn('Refresh picking failed:', e);
        }
    }

    // =============== QUANTITY CONTROLS (LOCAL ONLY) ===============
    incrementQty(moveId, step = 1.0) {
        const idx = this.state.lines.findIndex(l => l.move_id === moveId);
        if (idx < 0) return;
        const line = this.state.lines[idx];
        const newQty = Math.min((line.quantity_done || 0) + step, line.demand);
        if (newQty === (line.quantity_done || 0)) {
            this._showFeedback('error', `Đã đạt số lượng yêu cầu: ${line.demand} ${line.uom_name}`);
            this._playSound('error');
            return;
        }
        this.state.lines[idx] = { ...line, quantity_done: newQty };
        this._showFeedback('success', `✓ ${line.product_name}: ${newQty}/${line.demand} ${line.uom_name}`);
        this._playSound('success');
        this.state.last_scanned_move_id = moveId;
        setTimeout(() => { this.state.last_scanned_move_id = null; }, 1200);
    }

    decrementQty(moveId, step = 1.0) {
        const idx = this.state.lines.findIndex(l => l.move_id === moveId);
        if (idx < 0) return;
        const line = this.state.lines[idx];
        const newQty = Math.max(0, (line.quantity_done || 0) - step);
        this.state.lines[idx] = { ...line, quantity_done: newQty };
        this._showFeedback('success', `${line.product_name}: ${newQty}/${line.demand} ${line.uom_name}`);
        this._playSound('success');
        this.state.last_scanned_move_id = moveId;
        setTimeout(() => { this.state.last_scanned_move_id = null; }, 1200);
    }

    incrementDecimal(moveId) {
        const step = this.state.config.decimal_step || 0.1;
        this.incrementQty(moveId, step);
    }

    decrementDecimal(moveId) {
        const step = this.state.config.decimal_step || 0.1;
        this.decrementQty(moveId, step);
    }

    openNumpad(moveId) {
        const line = this.state.lines.find(l => l.move_id === moveId);
        if (!line) return;
        this.state.numpad_popup = {
            move_id: moveId,
            current_qty: line.quantity_done || 0,
            demand: line.demand,
            product_name: line.product_name,
            uom_name: line.uom_name,
        };
        this.state.numpad_value = String(line.quantity_done || 0);
    }

    onNumpadKey(key) {
        if (key === 'C') {
            this.state.numpad_value = '0';
        } else if (key === '⌫') {
            this.state.numpad_value = this.state.numpad_value.slice(0, -1) || '0';
        } else if (key === '.') {
            if (!this.state.numpad_value.includes('.')) {
                this.state.numpad_value += '.';
            }
        } else {
            if (this.state.numpad_value === '0') {
                this.state.numpad_value = key;
            } else {
                this.state.numpad_value += key;
            }
        }
    }

    async confirmNumpad() {
        if (!this.state.numpad_popup) return;
        const qty = parseFloat(this.state.numpad_value) || 0;
        const moveId = this.state.numpad_popup.move_id;
        const idx = this.state.lines.findIndex(l => l.move_id === moveId);
        if (idx >= 0) {
            const line = this.state.lines[idx];
            const clampedQty = Math.min(Math.max(0, qty), line.demand);
            this.state.lines[idx] = { ...line, quantity_done: clampedQty };
            if (clampedQty !== qty) {
                this._showFeedback('error', `Giới hạn: ${clampedQty}/${line.demand} ${line.uom_name}`);
            } else {
                this._showFeedback('success', `✓ ${line.product_name}: ${clampedQty}/${line.demand} ${line.uom_name}`);
            }
            this._playSound('success');
        }
        this.state.numpad_popup = null;
        this.state.numpad_value = '';
        setTimeout(() => this._focusBarcodeInput(), 100);
    }

    closeNumpad() {
        this.state.numpad_popup = null;
        this.state.numpad_value = '';
        setTimeout(() => this._focusBarcodeInput(), 100);
    }

    async _updateQuantity(moveId, newQty) {
        // Local update only — no backend call during scanning session
        const idx = this.state.lines.findIndex(l => l.move_id === moveId);
        if (idx >= 0) {
            const line = this.state.lines[idx];
            const clampedQty = Math.min(Math.max(0, newQty), line.demand);
            this.state.lines[idx] = { ...line, quantity_done: clampedQty };
            this._showFeedback('success', `✓ ${line.product_name}: ${clampedQty}/${line.demand} ${line.uom_name}`);
            this._playSound('success');
        }
    }

    // =============== VALIDATE PICKING ===============
    async validatePicking() {
        if (!this.state.picking) return;

        // Check if all lines have quantity > 0
        const noQty = this.state.lines.filter(l => (l.quantity_done || 0) === 0);
        if (noQty.length > 0) {
            this._showErrorPopup(
                `Còn ${noQty.length} dòng chưa quét số lượng. Vui lòng hoàn tất quét trước khi xác nhận.`
            );
            return;
        }

        // Build move_quantities from local tracking
        const moveQuantities = this.state.lines.map(l => ({
            move_id: l.move_id,
            quantity: l.quantity_done || 0,
        }));

        this.state.is_loading = true;
        try {
            const result = await rpc('/hlv_barcode_custom/validate_picking', {
                picking_id: this.state.picking.id,
                move_quantities: moveQuantities,
            });
            if (result.status === 'success') {
                this._showFeedback('success', result.message);
                this._playSound('success');
                // Go back to picking list after 2s
                setTimeout(() => {
                    if (this.state.picking_type_filter) {
                        this.openPickingTypeList(this.state.picking_type_filter);
                    } else {
                        this.goHome();
                    }
                }, 2000);
            } else {
                this._showErrorPopup(result.message);
                this._playSound('error');
            }
        } catch (e) {
            this._showErrorPopup(e.message || String(e));
            this._playSound('error');
        }
        this.state.is_loading = false;
    }

    // =============== CAMERA SCANNER ===============
    async toggleCamera() {
        if (this.state.camera_active) {
            this._stopCamera();
        } else {
            await this._startCamera();
        }
    }

    async _startCamera() {
        if (!this.state.config.camera_enabled) return;

        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                video: { facingMode: 'environment', width: { ideal: 1280 }, height: { ideal: 720 } },
            });
            this._cameraStream = stream;
            this.state.camera_active = true;
            this.state.camera_status = 'Đang quét...';

            // Wait for video element to mount
            setTimeout(() => {
                const video = this.cameraVideo.el;
                if (video) {
                    video.srcObject = stream;
                    video.play();
                    this._startCameraDetection(video);
                }
            }, 100);
        } catch (e) {
            console.error('Camera error:', e);
            this.state.camera_status = 'Không thể mở camera: ' + e.message;
        }
    }

    _startCameraDetection(video) {
        // Use native BarcodeDetector if available
        if (typeof BarcodeDetector !== 'undefined') {
            this._barcodeDetector = new BarcodeDetector({
                formats: ['ean_13', 'ean_8', 'code_128', 'code_39', 'qr_code', 'upc_a', 'upc_e'],
            });
            this._detectLoop(video);
        } else {
            this.state.camera_status = 'BarcodeDetector không khả dụng trên trình duyệt này.';
        }
    }

    async _detectLoop(video) {
        if (!this.state.camera_active || !this._barcodeDetector) return;

        try {
            const barcodes = await this._barcodeDetector.detect(video);
            if (barcodes.length > 0) {
                const code = barcodes[0].rawValue;
                if (code) {
                    // Don't stop camera - keep it embedded, just process the scan
                    this.state.barcode_value = code;
                    await this._processScan(code);
                    this.state.barcode_value = '';
                    // Pause briefly then resume detection
                    setTimeout(() => {
                        if (this.state.camera_active) {
                            this._cameraAnimFrame = requestAnimationFrame(() => this._detectLoop(video));
                        }
                    }, 2000);
                    return;
                }
            }
        } catch (e) {
            // Silently retry
        }
        this._cameraAnimFrame = requestAnimationFrame(() => this._detectLoop(video));
    }

    _stopCamera() {
        this.state.camera_active = false;
        this.state.camera_status = '';
        if (this._cameraAnimFrame) {
            cancelAnimationFrame(this._cameraAnimFrame);
            this._cameraAnimFrame = null;
        }
        if (this._cameraStream) {
            this._cameraStream.getTracks().forEach(t => t.stop());
            this._cameraStream = null;
        }
        this._barcodeDetector = null;
    }

    // =============== AUDIO FEEDBACK ===============
    _getAudioCtx() {
        if (!this._audioCtx) {
            this._audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        }
        return this._audioCtx;
    }

    _playSound(type) {
        try {
            if (type === 'success' && this.state.config.sound_success) {
                this._beepSuccess();
            } else if (type === 'error' && this.state.config.sound_error) {
                this._beepError();
            }
            // Haptic feedback on mobile
            if (navigator.vibrate) {
                navigator.vibrate(type === 'success' ? 100 : [100, 50, 100]);
            }
        } catch (e) {
            // Audio not critical
        }
    }

    _beepSuccess() {
        const ctx = this._getAudioCtx();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.frequency.value = 880;
        osc.type = 'sine';
        gain.gain.value = 0.3;
        osc.start();
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.15);
        osc.stop(ctx.currentTime + 0.15);
    }

    _beepError() {
        const ctx = this._getAudioCtx();
        // Double beep for error
        for (let i = 0; i < 2; i++) {
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.frequency.value = 300;
            osc.type = 'square';
            gain.gain.value = 0.4;
            const start = ctx.currentTime + i * 0.2;
            osc.start(start);
            gain.gain.exponentialRampToValueAtTime(0.001, start + 0.15);
            osc.stop(start + 0.15);
        }
    }

    // =============== FEEDBACK UI ===============
    _showFeedback(type, message) {
        this.state.feedback_type = type;
        this.state.feedback_message = message;
        this.state.feedback_visible = true;
        setTimeout(() => {
            this.state.feedback_visible = false;
        }, 3000);
    }

    _clearFeedback() {
        this.state.feedback_visible = false;
        this.state.feedback_message = '';
        this.state.feedback_type = '';
    }

    _showErrorPopup(message) {
        this.state.error_popup = { message };
    }

    _showError(title, message) {
        this.state.error_popup = { title, message };
    }

    closeErrorPopup() {
        this.state.error_popup = null;
        setTimeout(() => this._focusBarcodeInput(), 100);
    }

    // =============== HELPERS ===============
    getPickingTypeIcon(code) {
        const icons = {
            incoming: '📥',
            outgoing: '📤',
            internal: '🔄',
        };
        return icons[code] || '📋';
    }

    getPickingTypeCodeLabel(code) {
        const labels = {
            incoming: 'NHẬN HÀNG',
            outgoing: 'GIAO HÀNG',
            internal: 'NỘI BỘ',
        };
        return labels[code] || code;
    }

    getScanPlaceholder() {
        return 'Quét mã sản phẩm, vị trí, hoặc kiện hàng...';
    }

    isAllDone() {
        if (!this.state.lines.length) return false;
        return this.state.lines.every(l => (l.quantity_done || 0) >= l.demand && l.demand > 0);
    }

    // Warehouse navigation
    selectWarehouse(wh) {
        this.state.selected_warehouse = wh;
    }

    goBackFromWarehouse() {
        this.state.selected_warehouse = null;
    }

    getWarehouseCount(wh) {
        return wh.picking_types.reduce((sum, pt) => sum + (pt.count || 0), 0);
    }

    getLineStatus(line) {
        if ((line.quantity_done || 0) >= line.demand && line.demand > 0) return 'done';
        if ((line.quantity_done || 0) > 0) return 'partial';
        return 'pending';
    }

    getLineProgress(line) {
        if (!line.demand) return 0;
        return Math.min(100, ((line.quantity_done || 0) / line.demand) * 100);
    }

    getProductImageUrl(productId) {
        return `/hlv_barcode_custom/get_product_image?product_id=${productId}`;
    }

    getTotalScanned() {
        return this.state.lines.reduce((sum, l) => sum + (l.quantity_done || 0), 0);
    }

    getTotalDemand() {
        return this.state.lines.reduce((sum, l) => sum + (l.demand || 0), 0);
    }

    getDoneLines() {
        return this.state.lines.filter(l => (l.quantity_done || 0) >= l.demand && l.demand > 0).length;
    }

    goToInventoryCheck() {
        window.location.href = '/odoo/action-1678';
    }
}

function _t(s) { return s; }

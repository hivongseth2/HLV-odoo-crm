/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

/**
 * Generate device fingerprint
 */
function getDeviceId() {
    let id = localStorage.getItem('hlv_device_id');
    if (!id) {
        id = 'dev_' + crypto.randomUUID();
        localStorage.setItem('hlv_device_id', id);
    }
    return id;
}

/**
 * Inventory Scanner - Mobile App với Camera Support
 */
export class InventoryScanner extends Component {
    static template = "hlv_barcode_realtime_inventory.InventoryScanner";
    static props = {};

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");

        this.videoRef = useRef("cameraVideo");

        this.state = useState({
            sessionId: null,
            deviceId: getDeviceId(),
            locationId: null,
            locationName: '',
            lines: [],
            productCount: 0,
            totalScans: 0,
            loading: true,
            syncing: false,

            // Scanner modes
            scannerMode: 'camera', // 'camera' or 'keyboard'
            cameraActive: false,
            cameraError: null,
            barcodeInput: '',

            // Modals
            showLocationSelector: false,
            locationResults: [],
            showAddProductDialog: false,
        });

        this.cameraStream = null;
        this.detectionInterval = null;
        this.barcodeBuffer = '';

        onMounted(() => {
            this.initSession();
            this.tryStartCamera();
        });

        onWillUnmount(() => {
            this.stopCamera();
        });
    }

    // ==========================================================================
    // Camera Scanning
    // ==========================================================================

    async tryStartCamera() {
        if (!('BarcodeDetector' in window)) {
            console.warn('BarcodeDetector not supported, falling back to keyboard');
            this.state.scannerMode = 'keyboard';
            this.state.cameraError = 'Camera scanning không được hỗ trợ trên thiết bị này';
            return;
        }

        try {
            await this.startCamera();
        } catch (error) {
            console.error('Camera error:', error);
            this.state.scannerMode = 'keyboard';
            this.state.cameraError = 'Không thể truy cập camera';
        }
    }

    async startCamera() {
        try {
            this.state.cameraActive = false;

            const stream = await navigator.mediaDevices.getUserMedia({
                video: { facingMode: 'environment', width: { ideal: 1280 }, height: { ideal: 720 } }
            });

            if (this.videoRef.el) {
                this.videoRef.el.srcObject = stream;
                this.cameraStream = stream;
                this.state.cameraActive = true;
                this.state.cameraError = null;

                // Start barcode detection
                this.startBarcodeDetection();
            }
        } catch (error) {
            throw error;
        }
    }

    stopCamera() {
        if (this.detectionInterval) {
            clearInterval(this.detectionInterval);
            this.detectionInterval = null;
        }

        if (this.cameraStream) {
            this.cameraStream.getTracks().forEach(track => track.stop());
            this.cameraStream = null;
        }

        this.state.cameraActive = false;
    }

    async startBarcodeDetection() {
        if (!('BarcodeDetector' in window)) return;

        const barcodeDetector = new BarcodeDetector({
            formats: ['code_128', 'code_39', 'ean_13', 'ean_8', 'qr_code']
        });

        this.detectionInterval = setInterval(async () => {
            if (!this.videoRef.el || !this.state.cameraActive || this.state.syncing) return;

            try {
                const barcodes = await barcodeDetector.detect(this.videoRef.el);
                if (barcodes.length > 0) {
                    const barcode = barcodes[0].rawValue;
                    await this.processBarcode(barcode);
                }
            } catch (error) {
                console.error('Detection error:', error);
            }
        }, 300); // Check every 300ms
    }

    toggleScannerMode(mode) {
        this.state.scannerMode = mode;

        if (mode === 'camera') {
            this.tryStartCamera();
        } else {
            this.stopCamera();
        }
    }

    // ==========================================================================
    // Keyboard Scanning
    // ==========================================================================

    onBarcodeInputChange(event) {
        this.state.barcodeInput = event.target.value;
    }

    async onBarcodeInputKeydown(event) {
        if (event.key === 'Enter' && this.state.barcodeInput.trim()) {
            await this.processBarcode(this.state.barcodeInput.trim());
            this.state.barcodeInput = '';
        }
    }

    // ==========================================================================
    // Session Management
    // ==========================================================================

    async initSession() {
        try {
            this.state.loading = true;

            const result = await this.orm.call(
                "inventory.scan.session",
                "get_or_create_active_session",
                [this.state.deviceId, this.state.locationId]
            );

            if (result.success) {
                this.state.sessionId = result.session_id;
                this.state.locationId = result.location_id;
                this.state.locationName = result.location_name;
                this.state.lines = result.lines || [];
                this.state.productCount = result.product_count || 0;
                this.state.totalScans = result.scan_count || 0;

                if (result.lines && result.lines.length > 0) {
                    this.notification.add(
                        `Khôi phục ${result.lines.length} sản phẩm`,
                        { type: "success" }
                    );
                }
            }
        } catch (error) {
            console.error("Init error:", error);
            this.notification.add("Lỗi kết nối", { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    // ==========================================================================
    // Barcode Processing
    // ==========================================================================

    async processBarcode(barcode) {
        if (!barcode || this.state.syncing) return;

        // Nếu chưa có location, thử set location
        if (!this.state.locationId) {
            await this.trySetLocation(barcode);
            return;
        }

        // Scan product
        await this.scanProduct(barcode);
    }

    async trySetLocation(barcode) {
        try {
            this.state.syncing = true;
            const result = await this.orm.call(
                "inventory.scan.session",
                "search_location",
                [barcode]
            );

            if (result.success) {
                this.state.locationId = result.location_id;
                this.state.locationName = result.location_name;

                await this.orm.call(
                    "inventory.scan.session",
                    "set_location",
                    [[this.state.sessionId], result.location_id]
                );

                this.notification.add(`📍 ${result.location_name}`, { type: "success" });
            } else {
                this.notification.add("Vui lòng quét vị trí kho", { type: "warning" });
                this.openLocationSelector();
            }
        } finally {
            this.state.syncing = false;
        }
    }

    async scanProduct(barcode) {
        try {
            this.state.syncing = true;

            const productResult = await this.orm.call(
                "inventory.scan.session",
                "search_product",
                [barcode]
            );

            if (!productResult.success) {
                this.notification.add(productResult.error, { type: "warning" });
                return;
            }

            const scanResult = await this.orm.call(
                "inventory.scan.session",
                "register_scan",
                [
                    this.state.sessionId,
                    productResult.product_id,
                    this.state.locationId,
                    1,
                    false,
                    false,
                ]
            );

            if (scanResult.success) {
                this.updateOrAddLine(scanResult);

                // Vibrate feedback on mobile
                if ('vibrate' in navigator) {
                    navigator.vibrate(50);
                }

                this.notification.add(
                    `${productResult.product_name}: ${scanResult.scanned_qty}`,
                    { type: "success", sticky: false }
                );
            }
        } catch (error) {
            console.error("Scan error:", error);
            this.notification.add("Lỗi", { type: "danger" });
        } finally {
            this.state.syncing = false;
        }
    }

    updateOrAddLine(scanResult) {
        const existingIndex = this.state.lines.findIndex(
            l => l.product_id === scanResult.product_id
        );

        if (existingIndex >= 0) {
            this.state.lines[existingIndex].scanned_qty = scanResult.scanned_qty;
            this.state.lines[existingIndex].difference = scanResult.difference;
        } else {
            this.state.lines.unshift({
                id: scanResult.line_id,
                product_id: scanResult.product_id,
                product_code: scanResult.product_code,
                product_name: scanResult.product_name,
                uom_name: scanResult.uom_name,
                scanned_qty: scanResult.scanned_qty,
                theoretical_qty: scanResult.theoretical_qty,
                difference: scanResult.difference,
            });
        }

        this.state.productCount = scanResult.product_count;
        this.state.totalScans = scanResult.total_scans;
    }

    // ==========================================================================
    // Location Selector
    // ==========================================================================

    openLocationSelector() {
        this.state.showLocationSelector = true;
        this.loadLocations();
    }

    closeLocationSelector() {
        this.state.showLocationSelector = false;
    }

    async loadLocations(search = '') {
        const results = await this.orm.call(
            "inventory.scan.session",
            "get_locations_for_dropdown",
            [search, 20]
        );
        this.state.locationResults = results;
    }

    async selectLocation(loc) {
        this.state.locationId = loc.id;
        this.state.locationName = loc.name;

        if (this.state.sessionId) {
            await this.orm.call(
                "inventory.scan.session",
                "set_location",
                [[this.state.sessionId], loc.id]
            );
        }

        this.closeLocationSelector();
    }

    // ==========================================================================
    // Line Actions
    // ==========================================================================

    async incrementQty(line, amount) {
        const newQty = Math.max(0, line.scanned_qty + amount);
        await this.updateLineQty(line, newQty);
    }

    async updateLineQty(line, newQty) {
        try {
            this.state.syncing = true;
            const result = await this.orm.call(
                "inventory.scan.session",
                "update_line_qty",
                [[this.state.sessionId], line.id, newQty]
            );

            if (result.success) {
                line.scanned_qty = result.scanned_qty;
                line.difference = result.difference;
                this.state.totalScans = result.total_scans;
            }
        } finally {
            this.state.syncing = false;
        }
    }

    async removeLine(line) {
        try {
            this.state.syncing = true;
            const result = await this.orm.call(
                "inventory.scan.session",
                "remove_line",
                [[this.state.sessionId], line.id]
            );

            if (result.success) {
                const index = this.state.lines.findIndex(l => l.id === line.id);
                if (index >= 0) {
                    this.state.lines.splice(index, 1);
                }
                this.state.productCount = result.product_count;
                this.state.totalScans = result.total_scans;
            }
        } finally {
            this.state.syncing = false;
        }
    }

    // ==========================================================================
    // UI Actions
    // ==========================================================================

    goBack() {
        this.action.doAction('menu_inventory_scanner_root'); // Hoặc logic back khác tùy ý
        // Nếu muốn về trang chủ Odoo:
        // window.location.href = '/web';
    }

    toggleScannerMode(mode) {
        // Toggle logic: nếu đang camera thì sang keyboard và ngược lại
        const targetMode = mode || (this.state.scannerMode === 'camera' ? 'keyboard' : 'camera');

        this.state.scannerMode = targetMode;

        if (targetMode === 'camera') {
            this.tryStartCamera();
        } else {
            this.stopCamera();
        }
    }

    // ==========================================================================
    // Add Product Dialog
    // ==========================================================================

    openAddProductDialog() {
        this.state.showAddProductDialog = true;
        this.state.addProduct = {
            searchTerm: '',
            searchResults: [],
            selectedProduct: null,
            quantity: 1,
        };
    }

    closeAddProductDialog() {
        this.state.showAddProductDialog = false;
    }

    onProductSearchChange(ev) {
        this.state.addProduct.searchTerm = ev.target.value;
        // Có thể thêm debounce search logic ở đây nếu muốn list gợi ý
    }

    setAddQty(qty) {
        this.state.addProduct.quantity = qty;
    }

    adjustAddQty(delta) {
        const newQty = this.state.addProduct.quantity + delta;
        if (newQty >= 0) {
            this.state.addProduct.quantity = newQty;
        }
    }

    async confirmAddProduct() {
        const term = this.state.addProduct.searchTerm;
        const qty = this.state.addProduct.quantity;

        if (!term) {
            this.notification.add("Vui lòng nhập tên hoặc mã sản phẩm", { type: "warning" });
            return;
        }

        if (qty <= 0) {
            this.notification.add("Số lượng phải lớn hơn 0", { type: "warning" });
            return;
        }

        // Search và add giống như scan
        await this.processBarcode(term); // Tạm dùng logic này, sẽ cải tiến nếu cần tạo mới

        // Nếu search ra và add thành công (dựa vào line count tăng lên hoặc notif)
        // Hiện tại processBarcode đã handle logic tìm+add.

        // Cần truyền qty vào processBarcode hoặc scanProduct?
        // Hiện tại scanProduct mặc định qty=1. 
        // Logic đúng: Search product -> lấy ID -> gọi register_scan với qty cụ thể.

        await this.manualAddProduct(term, qty);
        this.closeAddProductDialog();
    }

    async manualAddProduct(term, qty) {
        try {
            this.state.syncing = true;
            const productResult = await this.orm.call(
                "inventory.scan.session",
                "search_product",
                [term] // Có thể cần sửa backend để search flexible hơn
            );

            if (!productResult.success) {
                this.notification.add(productResult.error, { type: "warning" });
                return;
            }

            const scanResult = await this.orm.call(
                "inventory.scan.session",
                "register_scan",
                [
                    this.state.sessionId,
                    productResult.product_id,
                    this.state.locationId,
                    qty,
                    false,
                    false,
                ]
            );

            if (scanResult.success) {
                this.updateOrAddLine(scanResult);
                this.notification.add(
                    `Đã thêm: ${productResult.product_name} (${qty})`,
                    { type: "success" }
                );
            }
        } catch (error) {
            console.error("Manual add error:", error);
            this.notification.add("Lỗi khi thêm sản phẩm", { type: "danger" });
        } finally {
            this.state.syncing = false;
        }
    }

    // ==========================================================================
    // Confirm Session
    // ==========================================================================

    async confirmSession() {
        if (this.state.lines.length === 0) {
            this.notification.add("Không có sản phẩm", { type: "warning" });
            return;
        }

        try {
            this.state.syncing = true;
            const result = await this.orm.call(
                "inventory.scan.session",
                "confirm_session",
                [[this.state.sessionId]]
            );

            if (result.success) {
                this.notification.add(result.message, { type: "success" });

                // Reset session
                this.state.lines = [];
                this.state.productCount = 0;
                this.state.totalScans = 0;
                this.state.sessionId = null;

                await this.initSession();
            }
        } finally {
            this.state.syncing = false;
        }
    }
}

registry.category("actions").add("hlv_inventory_scanner", InventoryScanner);

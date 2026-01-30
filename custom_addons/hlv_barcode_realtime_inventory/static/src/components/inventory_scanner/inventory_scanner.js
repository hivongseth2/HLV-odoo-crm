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
        if (location.protocol !== 'https:' && location.hostname !== 'localhost') {
            const msg = 'Camera yêu cầu HTTPS hoặc localhost';
            console.warn(msg);
            this.state.cameraError = msg;
            this.state.scannerMode = 'keyboard';
            return;
        }

        if (!('BarcodeDetector' in window)) {
            const msg = 'Trình duyệt không hỗ trợ BarcodeDetector. Vui lòng dùng Chrome trên Android hoặc Safari trên iOS (bật Experimental Features).';
            console.warn(msg);
            this.state.scannerMode = 'keyboard';
            this.state.cameraError = 'Trình duyệt chưa hỗ trợ quét';
            return;
        }

        try {
            await this.startCamera();
        } catch (error) {
            console.error('Camera error:', error);
            this.state.scannerMode = 'keyboard';

            if (error.name === 'NotAllowedError') {
                this.state.cameraError = 'Quyền truy cập Camera bị từ chối';
            } else if (error.name === 'NotFoundError') {
                this.state.cameraError = 'Không tìm thấy Camera';
            } else {
                this.state.cameraError = 'Lỗi Camera: ' + error.message;
            }
        }
    }

    // Fix Open Location Selector
    openLocationSelector(forAddProduct = false) {
        this.state.selectingLocationForAddProduct = forAddProduct;
        this.state.showLocationSelector = true;
        this.state.locationSearch = '';
        this.loadLocations('');
        // Focus search input
        setTimeout(() => {
            const input = document.getElementById('hlv-loc-search-input');
            if (input) input.focus();
        }, 100);
    }

    openAddProductLocationSelector() {
        this.openLocationSelector(true);
    }

    async onLocationSearchChange(ev) {
        const val = ev.target.value;
        this.state.locationSearch = val;

        if (this.locSearchTimeout) clearTimeout(this.locSearchTimeout);
        this.locSearchTimeout = setTimeout(() => {
            this.loadLocations(val);
        }, 300);
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
        if (this.state.selectingLocationForAddProduct) {
            this.state.addProduct.locationId = loc.id;
            this.state.addProduct.locationName = loc.name;
            this.state.showLocationSelector = false;
            return;
        }

        this.state.locationId = loc.id;
        this.state.locationName = loc.name;

        if (this.state.sessionId) {
            await this.orm.call(
                "inventory.scan.session",
                "set_location",
                [[this.state.sessionId], loc.id]
            );
            this.notification.add("Đã chuyển vị trí: " + loc.name, { type: "success" });
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
        // Quay về trang chủ Odoo
        window.location.href = '/web';
    }

    toggleScannerMode() {
        // Toggle giữa camera và keyboard
        const newMode = this.state.scannerMode === 'camera' ? 'keyboard' : 'camera';
        this.state.scannerMode = newMode;

        if (newMode === 'camera') {
            this.tryStartCamera();
        } else {
            this.stopCamera();
        }
    }

    // ==========================================================================
    // Add Product Dialog - Enhanced with Search
    // ==========================================================================

    openAddProductDialog() {
        this.state.showAddProductDialog = true;
        this.state.addProduct = {
            searchTerm: '',
            searchResults: [],
            selectedProduct: null,
            quantity: 1,
            showDropdown: false,
        };
        // Auto focus input via ref or simple timeout
        setTimeout(() => {
            const input = document.getElementById('hlv-product-search-input');
            if (input) input.focus();
        }, 100);
    }

    closeAddProductDialog() {
        this.state.showAddProductDialog = false;
    }

    async onProductSearchChange(ev) {
        const val = ev.target.value;
        this.state.addProduct.searchTerm = val;
        this.state.addProduct.selectedProduct = null; // Reset selection

        if (this.searchTimeout) clearTimeout(this.searchTimeout);

        if (val.length < 2) {
            this.state.addProduct.searchResults = [];
            this.state.addProduct.showDropdown = false;
            return;
        }

        this.searchTimeout = setTimeout(async () => {
            const results = await this.orm.call(
                "inventory.scan.session",
                "search_product_suggestions",
                [val]
            );
            this.state.addProduct.searchResults = results;
            this.state.addProduct.showDropdown = results.length > 0;
        }, 300);
    }

    selectProduct(product) {
        this.state.addProduct.searchTerm = product.display_name;
        this.state.addProduct.selectedProduct = product;
        this.state.addProduct.showDropdown = false;
        this.state.addProduct.searchResults = [];
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
        const selected = this.state.addProduct.selectedProduct;
        const term = this.state.addProduct.searchTerm;
        const qty = this.state.addProduct.quantity;

        // Use specific location if selected in dialog, otherwise session location
        const targetLocationId = this.state.addProduct.locationId || this.state.locationId;

        if (qty <= 0) {
            this.notification.add("Số lượng phải lớn hơn 0", { type: "warning" });
            return;
        }

        if (selected) {
            await this.manualAddProductById(selected.id, qty, selected.display_name, targetLocationId);
            this.closeAddProductDialog();
            return;
        }

        if (!term) {
            this.notification.add("Vui lòng chọn sản phẩm", { type: "warning" });
            return;
        }

        // Fallback: search string manual
        await this.manualAddProduct(term, qty, targetLocationId);
        this.closeAddProductDialog();
    }

    async manualAddProductById(productId, qty, name, locationId) {
        try {
            this.state.syncing = true;
            // Use passed locationId
            const locId = locationId || this.state.locationId;

            const scanResult = await this.orm.call(
                "inventory.scan.session",
                "register_scan",
                [
                    this.state.sessionId,
                    productId,
                    locId,
                    qty,
                    false,
                    false,
                ]
            );

            if (scanResult.success) {
                this.updateOrAddLine(scanResult);
                this.notification.add(
                    `Đã thêm: ${name} (${qty})`,
                    { type: "success" }
                );
            }
        } catch (error) {
            this.notification.add("Lỗi thêm sản phẩm", { type: "danger" });
        } finally {
            this.state.syncing = false;
        }
    }

    async manualAddProduct(term, qty, locationId) {
        try {
            this.state.syncing = true;
            const locId = locationId || this.state.locationId;

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
                    locId,
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

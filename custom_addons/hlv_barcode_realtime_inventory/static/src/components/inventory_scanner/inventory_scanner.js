/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { isBarcodeScannerSupported, scanBarcode } from "@web/core/barcode/barcode_scanner";

/**
 * Generate device fingerprint (persist across sessions)
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
 * Main Inventory Scanner Component
 * Standalone OWL component for barcode-based inventory counting
 */
export class InventoryScanner extends Component {
    static template = "hlv_barcode_realtime_inventory.InventoryScanner";
    static props = {
        action: { type: Object, optional: true },
        actionId: { type: Number, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        this.action = useService("action");

        // Check if device supports camera scanning
        this.isMobile = isBarcodeScannerSupported();

        this.state = useState({
            // Session state
            sessionId: null,
            sessionName: '',
            deviceId: getDeviceId(),

            // Location
            locationId: null,
            locationName: '',
            showLocationSelector: false,
            locationSearch: '',
            locationResults: [],

            // Scanned products
            lines: [],
            productCount: 0,
            totalScans: 0,

            // UI state
            loading: true,
            syncing: false,
            barcodeInput: '',
            showAddProductDialog: false,

            // Add Product Dialog state
            addProduct: {
                searchTerm: '',
                searchResults: [],
                selectedProduct: null,
                quantity: 1,
                locationId: null,
                locationName: '',
                lotId: null,
                lotName: '',
                packageId: null,
                packageName: '',
            },
        });

        // Barcode input handler
        this.barcodeBuffer = '';
        this.barcodeTimeout = null;

        onMounted(() => {
            this.initSession();
            document.addEventListener('keydown', this.onKeyDown.bind(this));
        });

        onWillUnmount(() => {
            document.removeEventListener('keydown', this.onKeyDown.bind(this));
        });
    }

    // ==========================================================================
    // Camera Scanning
    // ==========================================================================

    async openCamera() {
        try {
            const barcode = await scanBarcode();
            if (barcode) {
                await this.processBarcode(barcode);
            }
        } catch (error) {
            console.error("Camera scan error:", error);
            // Don't show notification if user cancelled
            if (error.message !== "Cancelled") {
                this.notification.add(_t("Không thể mở camera"), { type: "warning" });
            }
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
                this.state.sessionName = result.session_name;
                this.state.locationId = result.location_id;
                this.state.locationName = result.location_name;
                this.state.lines = result.lines || [];
                this.state.productCount = result.product_count || 0;
                this.state.totalScans = result.scan_count || 0;

                if (result.lines && result.lines.length > 0) {
                    this.notification.add(
                        _t("Đã khôi phục %s sản phẩm từ phiên trước", result.lines.length),
                        { type: "success" }
                    );
                }
            } else {
                this.notification.add(result.error || _t("Không thể tạo phiên"), { type: "danger" });
            }
        } catch (error) {
            console.error("Init session error:", error);
            this.notification.add(_t("Lỗi kết nối server"), { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    // ==========================================================================
    // Barcode Handling
    // ==========================================================================

    onKeyDown(event) {
        // Ignore if dialog is open or input is focused
        if (this.state.showAddProductDialog || this.state.showLocationSelector) return;

        const target = event.target;
        if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') return;

        // Collect barcode from keyboard
        if (event.key === 'Enter') {
            if (this.barcodeBuffer.length >= 3) {
                this.processBarcode(this.barcodeBuffer);
            }
            this.barcodeBuffer = '';
            clearTimeout(this.barcodeTimeout);
        } else if (event.key.length === 1) {
            this.barcodeBuffer += event.key;
            clearTimeout(this.barcodeTimeout);
            this.barcodeTimeout = setTimeout(() => {
                this.barcodeBuffer = '';
            }, 100);
        }
    }

    onBarcodeInputChange(event) {
        this.state.barcodeInput = event.target.value;
    }

    async onBarcodeInputKeydown(event) {
        if (event.key === 'Enter' && this.state.barcodeInput.trim()) {
            await this.processBarcode(this.state.barcodeInput.trim());
            this.state.barcodeInput = '';
            event.target.focus();
        }
    }

    async processBarcode(barcode) {
        if (!barcode || this.state.syncing) return;

        // Nếu chưa có location, thử tìm location
        if (!this.state.locationId) {
            await this.trySetLocation(barcode);
            return;
        }

        // Tìm sản phẩm và đăng ký scan
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
                await this.setLocation(result.location_id, result.location_name);
                this.notification.add(
                    _t("Đã chọn vị trí: %s", result.location_name),
                    { type: "success" }
                );
            } else {
                this.notification.add(
                    _t("Vui lòng quét mã vị trí kho trước"),
                    { type: "warning" }
                );
            }
        } finally {
            this.state.syncing = false;
        }
    }

    async scanProduct(barcode) {
        if (!this.state.sessionId || !this.state.locationId) return;

        try {
            this.state.syncing = true;

            // Tìm product
            const productResult = await this.orm.call(
                "inventory.scan.session",
                "search_product",
                [barcode]
            );

            if (!productResult.success) {
                this.notification.add(productResult.error, { type: "warning" });
                return;
            }

            // Đăng ký scan
            const scanResult = await this.orm.call(
                "inventory.scan.session",
                "register_scan",
                [
                    this.state.sessionId,
                    productResult.product_id,
                    this.state.locationId,
                    1, // qty
                    false, // lot_id
                    false, // package_id
                ]
            );

            if (scanResult.success) {
                // Update hoặc add line
                const existingIndex = this.state.lines.findIndex(
                    l => l.product_id === productResult.product_id
                );

                if (existingIndex >= 0) {
                    this.state.lines[existingIndex].scanned_qty = scanResult.scanned_qty;
                    this.state.lines[existingIndex].difference = scanResult.difference;
                } else {
                    this.state.lines.unshift({
                        id: scanResult.line_id,
                        product_id: productResult.product_id,
                        product_code: productResult.product_code,
                        product_name: productResult.product_name,
                        uom_name: productResult.uom_name,
                        scanned_qty: scanResult.scanned_qty,
                        theoretical_qty: scanResult.theoretical_qty,
                        difference: scanResult.difference,
                    });
                }

                this.state.productCount = scanResult.product_count;
                this.state.totalScans = scanResult.total_scans;

                this.notification.add(
                    _t("%s: %s", productResult.product_name, scanResult.scanned_qty),
                    { type: "success", sticky: false }
                );
            } else {
                this.notification.add(scanResult.error, { type: "danger" });
            }
        } catch (error) {
            console.error("Scan error:", error);
            this.notification.add(_t("Lỗi đồng bộ"), { type: "danger" });
        } finally {
            this.state.syncing = false;
        }
    }

    // ==========================================================================
    // Location Management
    // ==========================================================================

    openLocationSelector() {
        this.state.showLocationSelector = true;
        this.state.locationSearch = '';
        this.loadLocations();
    }

    closeLocationSelector() {
        this.state.showLocationSelector = false;
    }

    async loadLocations(search = '') {
        try {
            const results = await this.orm.call(
                "inventory.scan.session",
                "get_locations_for_dropdown",
                [search, 20]
            );
            this.state.locationResults = results;
        } catch (error) {
            console.error("Load locations error:", error);
        }
    }

    onLocationSearchChange(event) {
        this.state.locationSearch = event.target.value;
        this.loadLocations(this.state.locationSearch);
    }

    async selectLocation(locationId, locationName) {
        await this.setLocation(locationId, locationName);
        this.closeLocationSelector();
    }

    async setLocation(locationId, locationName) {
        this.state.locationId = locationId;
        this.state.locationName = locationName;

        if (this.state.sessionId) {
            try {
                await this.orm.call(
                    "inventory.scan.session",
                    "set_location",
                    [[this.state.sessionId], locationId]
                );
            } catch (error) {
                console.error("Set location error:", error);
            }
        }
    }

    // ==========================================================================
    // Line Actions (+1, +10, delete, edit qty)
    // ==========================================================================

    async incrementQty(line, amount) {
        const newQty = Math.max(0, line.scanned_qty + amount);
        await this.updateLineQty(line, newQty);
    }

    async setLineQty(line, newQty) {
        await this.updateLineQty(line, newQty);
    }

    async updateLineQty(line, newQty) {
        if (!this.state.sessionId) return;

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
            } else {
                this.notification.add(result.error, { type: "danger" });
            }
        } catch (error) {
            console.error("Update qty error:", error);
            this.notification.add(_t("Lỗi cập nhật số lượng"), { type: "danger" });
        } finally {
            this.state.syncing = false;
        }
    }

    async removeLine(line) {
        if (!this.state.sessionId) return;

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
            } else {
                this.notification.add(result.error, { type: "danger" });
            }
        } catch (error) {
            console.error("Remove line error:", error);
            this.notification.add(_t("Lỗi xóa sản phẩm"), { type: "danger" });
        } finally {
            this.state.syncing = false;
        }
    }

    // ==========================================================================
    // Add Product Dialog
    // ==========================================================================

    openAddProductDialog() {
        this.state.addProduct = {
            searchTerm: '',
            searchResults: [],
            selectedProduct: null,
            quantity: 1,
            locationId: this.state.locationId,
            locationName: this.state.locationName,
            lotId: null,
            lotName: '',
            packageId: null,
            packageName: '',
        };
        this.state.showAddProductDialog = true;
    }

    closeAddProductDialog() {
        this.state.showAddProductDialog = false;
    }

    async onProductSearchChange(event) {
        const term = event.target.value;
        this.state.addProduct.searchTerm = term;

        if (term.length < 2) {
            this.state.addProduct.searchResults = [];
            return;
        }

        try {
            const products = await this.orm.searchRead(
                "product.product",
                ['|', '|',
                    ['barcode', 'ilike', term],
                    ['default_code', 'ilike', term],
                    ['name', 'ilike', term]
                ],
                ['id', 'display_name', 'default_code', 'barcode', 'uom_id'],
                { limit: 10 }
            );
            this.state.addProduct.searchResults = products;
        } catch (error) {
            console.error("Product search error:", error);
        }
    }

    selectProductForAdd(product) {
        this.state.addProduct.selectedProduct = {
            id: product.id,
            name: product.display_name,
            code: product.default_code || '',
            barcode: product.barcode || '',
            uom_name: product.uom_id ? product.uom_id[1] : 'Cái',
        };
        this.state.addProduct.searchTerm = product.display_name;
        this.state.addProduct.searchResults = [];
    }

    adjustAddQty(amount) {
        this.state.addProduct.quantity = Math.max(0, this.state.addProduct.quantity + amount);
    }

    setAddQty(value) {
        this.state.addProduct.quantity = Math.max(0, parseInt(value) || 0);
    }

    async confirmAddProduct() {
        const { selectedProduct, quantity, locationId, lotId, packageId } = this.state.addProduct;

        if (!selectedProduct) {
            this.notification.add(_t("Vui lòng chọn sản phẩm"), { type: "warning" });
            return;
        }

        if (!locationId) {
            this.notification.add(_t("Vui lòng chọn vị trí kho"), { type: "warning" });
            return;
        }

        if (quantity <= 0) {
            this.notification.add(_t("Số lượng phải lớn hơn 0"), { type: "warning" });
            return;
        }

        try {
            this.state.syncing = true;
            const result = await this.orm.call(
                "inventory.scan.session",
                "register_scan",
                [
                    this.state.sessionId,
                    selectedProduct.id,
                    locationId,
                    quantity,
                    lotId || false,
                    packageId || false,
                ]
            );

            if (result.success) {
                const existingIndex = this.state.lines.findIndex(
                    l => l.product_id === selectedProduct.id
                );

                if (existingIndex >= 0) {
                    this.state.lines[existingIndex].scanned_qty = result.scanned_qty;
                    this.state.lines[existingIndex].difference = result.difference;
                } else {
                    this.state.lines.unshift({
                        id: result.line_id,
                        product_id: selectedProduct.id,
                        product_code: result.product_code,
                        product_name: result.product_name,
                        uom_name: result.uom_name,
                        scanned_qty: result.scanned_qty,
                        theoretical_qty: result.theoretical_qty,
                        difference: result.difference,
                    });
                }

                this.state.productCount = result.product_count;
                this.state.totalScans = result.total_scans;

                this.closeAddProductDialog();
                this.notification.add(
                    _t("Đã thêm: %s x %s", selectedProduct.name, quantity),
                    { type: "success" }
                );
            } else {
                this.notification.add(result.error, { type: "danger" });
            }
        } catch (error) {
            console.error("Add product error:", error);
            this.notification.add(_t("Lỗi thêm sản phẩm"), { type: "danger" });
        } finally {
            this.state.syncing = false;
        }
    }

    // ==========================================================================
    // Session Actions (Confirm, Cancel)
    // ==========================================================================

    async confirmSession() {
        if (!this.state.sessionId || this.state.lines.length === 0) {
            this.notification.add(_t("Không có sản phẩm nào để xác nhận"), { type: "warning" });
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
                // Reset và tạo session mới
                this.state.lines = [];
                this.state.productCount = 0;
                this.state.totalScans = 0;
                this.state.sessionId = null;
                await this.initSession();
            } else {
                this.notification.add(result.error, { type: "danger" });
            }
        } catch (error) {
            console.error("Confirm error:", error);
            this.notification.add(_t("Lỗi xác nhận kiểm kê"), { type: "danger" });
        } finally {
            this.state.syncing = false;
        }
    }

    async cancelSession() {
        if (!this.state.sessionId) return;

        try {
            this.state.syncing = true;
            const result = await this.orm.call(
                "inventory.scan.session",
                "cancel_session",
                [[this.state.sessionId]]
            );

            if (result.success) {
                this.notification.add(result.message, { type: "info" });
                // Reset và tạo session mới
                this.state.lines = [];
                this.state.productCount = 0;
                this.state.totalScans = 0;
                this.state.sessionId = null;
                this.state.locationId = null;
                this.state.locationName = '';
                await this.initSession();
            } else {
                this.notification.add(result.error, { type: "danger" });
            }
        } catch (error) {
            console.error("Cancel error:", error);
            this.notification.add(_t("Lỗi hủy phiên"), { type: "danger" });
        } finally {
            this.state.syncing = false;
        }
    }

    goBack() {
        this.action.doAction({ type: "ir.actions.act_window_close" });
    }
}

// Register as client action
registry.category("actions").add("hlv_inventory_scanner", InventoryScanner);

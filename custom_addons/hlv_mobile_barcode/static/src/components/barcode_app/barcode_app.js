/** @odoo-module **/

import { Component, useState, onMounted, useEffect } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { PickingScanner } from "../picking_scanner/picking_scanner";
import { InventoryLookup } from "../inventory_lookup/inventory_lookup";
import { LocationMove } from "../location_move/location_move";
import { BatchLocationMove } from "../batch_location_move/batch_location_move";

export class BarcodeApp extends Component {
    static template = "hlv_mobile_barcode.BarcodeApp";
    static components = { PickingScanner, InventoryLookup, LocationMove, BatchLocationMove };

    setup() {
        this.notification = useService("notification");
        this.action = useService("action");
        
        let savedState = {};
        let savedHistory = [];
        try {
            const stored = sessionStorage.getItem('hlv_barcode_state');
            if (stored) {
                savedState = JSON.parse(stored);
                savedHistory = savedState.history || [];
            }
        } catch (e) {}
        
        this.history = savedHistory;

        this.state = useState({
            currentView: savedState.currentView || "main", 
            manualBarcode: "",
            pickingId: savedState.pickingId || null,
            pickingName: savedState.pickingName || "",
            lookupType: savedState.lookupType || null,
            recordId: savedState.recordId || null,
            lookupTitle: savedState.lookupTitle || "",
            prefillLocationBarcode: savedState.prefillLocationBarcode || null,
            prefillLocationName: savedState.prefillLocationName || null,
            cameraFallback: false,
            cameraNeedsActivation: false,
            cameraErrorMessage: "",
            showCameraPopup: false,
            pickingRefreshTick: 0,
        });
        
        useEffect(() => {
            sessionStorage.setItem('hlv_barcode_state', JSON.stringify({
                currentView: this.state.currentView,
                pickingId: this.state.pickingId,
                pickingName: this.state.pickingName,
                lookupType: this.state.lookupType,
                recordId: this.state.recordId,
                lookupTitle: this.state.lookupTitle,
                prefillLocationBarcode: this.state.prefillLocationBarcode,
                prefillLocationName: this.state.prefillLocationName,
                history: this.history
            }));
        }, () => [
            this.state.currentView,
            this.state.pickingId,
            this.state.pickingName,
            this.state.lookupType,
            this.state.recordId,
            this.state.lookupTitle,
            this.state.prefillLocationBarcode,
            this.state.prefillLocationName
        ]);

        this.barcodeBuffer = "";
        this.barcodeTimeout = null;
        
        onMounted(() => {
            document.addEventListener('keydown', this.handleKeyDown.bind(this));
            if (this.state.currentView !== 'main') {
                this.startPersistentCamera();
            }
        });
    }

    handleKeyDown(e) {
        if (['INPUT', 'TEXTAREA'].includes(e.target.tagName)) {
            return;
        }

        if (e.key === 'Enter' && this.barcodeBuffer.length > 2) {
            this.processBarcode(this.barcodeBuffer);
            this.barcodeBuffer = "";
            return;
        }
        
        if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
            this.barcodeBuffer += e.key;
            if (this.barcodeTimeout) clearTimeout(this.barcodeTimeout);
            this.barcodeTimeout = setTimeout(() => {
                this.barcodeBuffer = "";
            }, 500); 
        }
    }

    onManualBarcodeKeyup(ev) {
        if (ev.key === 'Enter') {
            this.processManualBarcode();
        }
    }

    async processManualBarcode() {
        if (this.state.manualBarcode) {
            await this.processBarcode(this.state.manualBarcode);
            this.state.manualBarcode = "";
        }
    }

    registerScanner(cb) {
        this.viewScannerCallback = cb;
    }

    async processBarcode(barcode) {
        if (!barcode) return;
        
        if (this.viewScannerCallback) {
            this.viewScannerCallback(barcode);
            return;
        }

        if (this.state.currentView === 'picking') {
            try {
                const res = await rpc("/hlv_mobile_barcode/process_barcode", { 
                    picking_id: this.state.pickingId, 
                    barcode: barcode,
                    destination_location_id: this.state.scannedLocationId,
                    last_product_id: this.state.lastScannedProduct
                });
                if (res.error) {
                    this.playSound('error');
                    this.notification.add(res.error, { type: "danger" });
                } else if (res.type === 'location') {
                    this.playSound('success');
                    this.state.scannedLocationId = res.location_id;
                    this.state.scannedLocationName = res.location_name;
                    this.notification.add(`Đã chọn vị trí: ${res.location_name}`, { type: "success" });
                    
                    if (res.updated_product_id) {
                        this.state.lastScannedProduct = res.updated_product_id;
                        // Reload picking data since we updated the line's location
                        // We can just rely on the component reloading when props change, or since we pass scannedLocationName, it will trigger an update.
                    }
                } else {
                    this.playSound('success');
                    this.notification.add(`Scanned ${res.product_name}`, { type: "success" });
                    this.state.lastScannedProduct = res.product_id;
                }
            } catch (e) {
                this.playSound('error');
                this.notification.add("Server error", { type: "danger" });
            }
            return;
        }
        
        try {
            const result = await rpc("/hlv_mobile_barcode/smart_scan", { barcode });
            if (result.error) {
                this.playSound('error');
                this.notification.add(result.error, { type: "danger" });
                return;
            }
            
            this.playSound('success');
            
            if (result.type === 'picking' || ['product', 'location', 'package'].includes(result.type)) {
                // Close the popup camera if it's currently open
                this.closeCamera();
                this.state.showCameraPopup = false;

                this.pushHistory();
                if (result.type === 'picking') {
                    this.state.pickingId = result.id;
                    this.state.pickingName = result.name;
                    this.state.currentView = 'picking';
                } else {
                    this.state.lookupType = result.type;
                    this.state.recordId = result.id;
                    this.state.lookupTitle = result.name;
                    this.state.currentView = 'lookup';
                }

                // Start persistent inline camera on the newly loaded view
                setTimeout(() => {
                    this.startPersistentCamera(false);
                }, 200);
            }
        } catch (error) {
            this.playSound('error');
            this.notification.add("Server error", { type: "danger" });
        }
    }

    playSound(type) {
        try {
            const audioPath = type === 'success' 
                ? '/custom_barcode_scan_redirect/static/src/sound/success.mp3' 
                : '/custom_barcode_scan_redirect/static/src/sound/error.mp3';
            const audio = new Audio(audioPath);
            audio.play().catch(e => console.error("Audio error:", e));
        } catch (e) {}
    }

    pushHistory() {
        if (!this.history) this.history = [];
        this.history.push({
            currentView: this.state.currentView,
            pickingId: this.state.pickingId,
            pickingName: this.state.pickingName,
            lookupType: this.state.lookupType,
            recordId: this.state.recordId,
            lookupTitle: this.state.lookupTitle,
            prefillLocationBarcode: this.state.prefillLocationBarcode,
            prefillLocationName: this.state.prefillLocationName,
        });
    }

    goBack() {
        this.closeCamera();
        this.state.showCameraPopup = false;
        if (this.history && this.history.length > 0) {
            const prevState = this.history.pop();
            this.state.currentView = prevState.currentView;
            this.state.pickingId = prevState.pickingId;
            this.state.pickingName = prevState.pickingName;
            this.state.lookupType = prevState.lookupType;
            this.state.recordId = prevState.recordId;
            this.state.lookupTitle = prevState.lookupTitle;
            this.state.prefillLocationBarcode = prevState.prefillLocationBarcode;
            this.state.prefillLocationName = prevState.prefillLocationName;
            this.viewScannerCallback = null;

            // If the restored view is not main, start the inline camera
            if (this.state.currentView !== 'main') {
                setTimeout(() => {
                    this.startPersistentCamera(false);
                }, 150);
            }
        } else {
            this.goToMain();
        }
    }

    goToMain() {
        this.closeCamera();
        this.state.showCameraPopup = false;
        this.history = [];
        this.state.currentView = 'main';
        this.state.pickingId = null;
        this.state.lookupType = null;
        this.state.recordId = null;
        this.state.prefillLocationBarcode = null;
        this.state.prefillLocationName = null;
        this.viewScannerCallback = null;
    }

    goToMove(productId, locationBarcode = null, locationName = null) {
        this.pushHistory();
        this.state.recordId = productId;
        this.state.prefillLocationBarcode = locationBarcode;
        this.state.prefillLocationName = locationName;
        this.state.currentView = 'move';
    }

    async goToBatchMove(locationBarcode, locationName) {
        // Now redirects to a newly created empty INT picking
        this.pushHistory();
        try {
            this.notification.add("Đang tạo phiếu xuất...", { type: "info" });
            // For create_empty_int, we pass the location record id. 
            // Wait, InventoryLookup state.location_barcode is just the barcode. We need the record_id.
            // Let's pass the recordId which we have in this.state.recordId!
            const res = await rpc("/hlv_mobile_barcode/create_empty_int", {
                location_id: this.state.recordId
            });
            
            if (res.error) {
                this.notification.add(res.error, { type: "danger" });
                this.goBack();
            } else {
                this.state.pickingId = res.picking_id;
                this.state.pickingName = res.picking_name;
                this.state.currentView = 'picking';
            }
        } catch (e) {
            this.notification.add("Lỗi kết nối máy chủ", { type: "danger" });
            this.goBack();
        }
    }

    goToProductLookup(productId, productName) {
        this.pushHistory();
        this.state.lookupType = 'product';
        this.state.recordId = productId;
        this.state.lookupTitle = productName;
        this.state.currentView = 'lookup';
    }

    openPopupCamera() {
        this.state.showCameraPopup = true;
        setTimeout(() => {
            this.startPersistentCamera(false);
        }, 150);
    }

    closePopupCamera() {
        this.closeCamera();
        this.state.showCameraPopup = false;
    }

    async startPersistentCamera(isUserGesture = false) {
        // Check if page is served securely (HTTPS or localhost)
        if (window.isSecureContext === false && window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1') {
            this.state.cameraFallback = true;
            this.state.cameraErrorMessage = "HTTPS_REQUIRED";
            return;
        }

        this.state.cameraNeedsActivation = false;
        this.state.cameraErrorMessage = "";

        if (!window.Html5Qrcode) {
            try {
                await new Promise((resolve, reject) => {
                    const script = document.createElement("script");
                    script.src = "https://unpkg.com/html5-qrcode";
                    script.onload = resolve;
                    script.onerror = reject;
                    document.head.appendChild(script);
                });
            } catch (e) {
                this.notification.add("Cannot load camera library. Need internet.", { type: "danger" });
                this.state.cameraFallback = true;
                return;
            }
        }
        
        try {
            if (this.html5Qrcode) {
                try { await this.html5Qrcode.stop(); } catch(e) {}
                try { this.html5Qrcode.clear(); } catch(e) {}
                this.html5Qrcode = null;
            }

            this.html5Qrcode = new window.Html5Qrcode("reader");
            
            const config = { 
                fps: 20,               
                disableFlip: false,    
                aspectRatio: 1.333334,      
                experimentalFeatures: {
                    useBarCodeDetectorIfSupported: true 
                }
            };
            
            await this.html5Qrcode.start(
                { facingMode: "environment" }, 
                config,
                async (decodedText, decodedResult) => {
                    if (this.html5Qrcode) {
                        try { this.html5Qrcode.pause(); } catch(e) {}
                    }
                    await this.processBarcode(decodedText);
                    
                    setTimeout(() => {
                        if (this.html5Qrcode && this.html5Qrcode.getState() === 2 /* PAUSED */) {
                            try { this.html5Qrcode.resume(); } catch(e) {}
                        }
                    }, 1500);
                },
                (errorMessage) => {
                    // ignore parse errors
                }
            );

            this.state.cameraNeedsActivation = false;
            this.state.cameraErrorMessage = "";
            this.state.cameraFallback = false;
        } catch (err) {
            const errStr = String(err).toLowerCase();
            console.error("Camera start error:", err);
            
            if (errStr.includes("notallowederror") || errStr.includes("permission")) {
                if (!isUserGesture) {
                    // Fail on load (possibly iOS user-gesture requirement or first time permission prompt block)
                    // We show the "Activate" overlay to let user click and trigger it via active gesture.
                    this.state.cameraNeedsActivation = true;
                    this.state.cameraErrorMessage = "PERMISSION_DENIED";
                } else {
                    // Real refusal or permission disabled globally
                    this.state.cameraFallback = true;
                    this.state.cameraErrorMessage = "PERMISSION_DENIED";
                    this.notification.add("Không thể mở Camera. Hãy cấp quyền Camera cho Chrome trong Cài đặt iPhone.", { type: "danger" });
                }
            } else {
                this.notification.add("Không thể mở Camera. Lỗi: " + err, { type: "warning" });
                this.state.cameraFallback = true;
            }
        }
    }

    async onFileSelected(ev) {
        if (!ev.target.files || ev.target.files.length === 0) return;
        const file = ev.target.files[0];
        try {
            if (!this.html5Qrcode) {
                this.html5Qrcode = new window.Html5Qrcode("reader");
            }
            const decodedText = await this.html5Qrcode.scanFile(file, true);
            await this.processBarcode(decodedText);
        } catch (err) {
            this.playSound('error');
            this.notification.add("Không tìm thấy mã vạch hợp lệ trong ảnh này.", { type: "danger" });
        }
    }

    async closeCamera() {
        this.state.showCamera = false;
        this.state.cameraFallback = false;
        this.state.cameraNeedsActivation = false;
        this.state.cameraErrorMessage = "";
        if (this.html5Qrcode) {
            try {
                await this.html5Qrcode.stop();
            } catch (e) {}
            try {
                this.html5Qrcode.clear();
            } catch (e) {}
            this.html5Qrcode = null;
        }
    }

    exitApp() {
        // Thoát ứng dụng Barcode, quay về màn hình chính Odoo
        window.location.href = "/web";
    }

    openSettings() {
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: 'Settings',
            res_model: 'res.config.settings',
            views: [[false, 'form']],
            target: 'current',
            context: { module: 'hlv_mobile_barcode' }
        });
    }

    async clearPicking() {
        if (!confirm("Bạn có chắc muốn xoá toàn bộ số lượng đã quét để quét lại từ đầu không?")) {
            return;
        }
        try {
            const res = await rpc("/hlv_mobile_barcode/clear_quantities", {
                picking_id: this.state.pickingId,
            });
            if (res.error) {
                this.notification.add(res.error, { type: "danger" });
            } else {
                this.notification.add("Đã làm mới số lượng", { type: "success" });
                this.state.pickingRefreshTick += 1;
            }
        } catch (e) {
            this.notification.add("Lỗi kết nối", { type: "danger" });
        }
    }
}

registry.category("actions").add("hlv_mobile_barcode.BarcodeApp", BarcodeApp);

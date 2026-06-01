/** @odoo-module **/

import { Component, useState, onMounted, useEffect, useRef, onWillUnmount } from "@odoo/owl";
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

        this.hiddenInputRef = useRef("hiddenInput");

        this.state = useState({
            currentView: savedState.currentView || "main", 
            manualBarcode: "",
            hiddenBarcode: "",
            isProcessing: false,
            pickingId: savedState.pickingId || null,
            pickingName: savedState.pickingName || "",
            warehouseCode: savedState.warehouseCode || "",
            scannedLocationId: savedState.scannedLocationId || null,
            scannedLocationName: savedState.scannedLocationName || "",
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
            pickingState: "",
            scanMode: savedState.scanMode || "source",
            warehouses: [],
            selectedWarehouseId: null,
            showWarehouseSelectPopup: false,
            destSelectionMode: 'location',
            destLocationBarcode: "",
            destLocationName: "",
            destLocationId: null,
            isLocatingDest: false,
            showExitOptions: false,
            pendingExitAction: null,
            isMultiLocationMode: savedState.isMultiLocationMode || false,
        });
        
        useEffect(() => {
            sessionStorage.setItem('hlv_barcode_state', JSON.stringify({
                currentView: this.state.currentView,
                pickingId: this.state.pickingId,
                pickingName: this.state.pickingName,
                warehouseCode: this.state.warehouseCode,
                scannedLocationId: this.state.scannedLocationId,
                scannedLocationName: this.state.scannedLocationName,
                lookupType: this.state.lookupType,
                recordId: this.state.recordId,
                lookupTitle: this.state.lookupTitle,
                prefillLocationBarcode: this.state.prefillLocationBarcode,
                prefillLocationName: this.state.prefillLocationName,
                history: this.history,
                scanMode: this.state.scanMode,
                isMultiLocationMode: this.state.isMultiLocationMode
            }));
        }, () => [
            this.state.currentView,
            this.state.pickingId,
            this.state.pickingName,
            this.state.warehouseCode,
            this.state.scannedLocationId,
            this.state.scannedLocationName,
            this.state.lookupType,
            this.state.recordId,
            this.state.lookupTitle,
            this.state.prefillLocationBarcode,
            this.state.prefillLocationName,
            this.state.scanMode,
            this.state.isMultiLocationMode
        ]);

        this.barcodeBuffer = "";
        this.barcodeTimeout = null;

        this.keepFocusOnHiddenInput = () => {
            const active = document.activeElement;
            if (active && ['INPUT', 'TEXTAREA', 'SELECT'].includes(active.tagName) && !active.classList.contains('hidden-barcode-input')) {
                return;
            }
            const inputEl = this.hiddenInputRef?.el;
            if (inputEl) {
                inputEl.focus();
            }
        };

        this.boundKeepFocus = this.keepFocusOnHiddenInput.bind(this);
        
        onMounted(async () => {
            document.addEventListener('keydown', this.handleKeyDown.bind(this));
            this.keepFocusOnHiddenInput();
            document.addEventListener('click', this.boundKeepFocus);
            
            try {
                const warehouses = await rpc("/hlv_mobile_barcode/get_warehouses", {});
                this.state.warehouses = warehouses;
            } catch (e) {
                console.error("Failed to load warehouses", e);
            }

            this.focusInterval = setInterval(this.boundKeepFocus, 2000);
            setTimeout(this.boundKeepFocus, 500);

            if (this.state.currentView !== 'main') {
                this.startPersistentCamera();
            }
        });

        onWillUnmount(() => {
            document.removeEventListener('click', this.boundKeepFocus);
            if (this.focusInterval) {
                clearInterval(this.focusInterval);
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

    async onHiddenInputKeyup(ev) {
        if (ev.key === 'Enter') {
            const barcode = this.state.hiddenBarcode ? this.state.hiddenBarcode.trim() : "";
            if (barcode) {
                await this.processBarcode(barcode);
            }
            this.state.hiddenBarcode = "";
            setTimeout(() => this.keepFocusOnHiddenInput(), 50);
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

    toggleScanMode(mode) {
        if (mode) {
            this.state.scanMode = mode;
        } else {
            this.state.scanMode = this.state.scanMode === 'source' ? 'dest' : 'source';
        }
    }

    async processBarcode(barcode) {
        if (!barcode) return;
        
        if (this.state.isProcessing) {
            this.playSound('error');
            this.notification.add("Hệ thống đang bận xử lý, vui lòng quét lại sau giây lát...", { type: "warning" });
            return;
        }

        this.state.isProcessing = true;
        
        if (this.viewScannerCallback) {
            try {
                await this.viewScannerCallback(barcode);
            } catch (e) {}
            this.state.isProcessing = false;
            return;
        }

        if (this.state.showWarehouseSelectPopup) {
            try {
                const res = await rpc("/hlv_mobile_barcode/smart_scan", { barcode: barcode });
                if (res && res.type === 'location') {
                    this.state.destLocationBarcode = barcode;
                    this.state.destLocationName = res.name;
                    this.state.destLocationId = res.id;
                    this.playSound('success');
                    this.notification.add(`Đã nhận vị trí đích: ${res.name}`, { type: "success" });
                } else {
                    this.playSound('error');
                    this.notification.add("Mã vạch không hợp lệ", { type: "warning" });
                }
            } catch (e) {
                this.playSound('error');
                this.notification.add("Lỗi kết nối", { type: "danger" });
            }
            this.state.isProcessing = false;
            return;
        }

        if (this.state.currentView === 'picking') {
            try {
                const res = await rpc("/hlv_mobile_barcode/process_barcode", { 
                    picking_id: this.state.pickingId, 
                    barcode: barcode,
                    destination_location_id: this.state.scannedLocationId,
                    last_product_id: this.state.lastScannedProduct,
                    location_mode: this.state.scanMode,
                    is_multi_location: this.state.isMultiLocationMode
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
                    }
                    this.state.pickingRefreshTick += 1;
                } else {
                    this.playSound('success');
                    this.notification.add(`Scanned ${res.product_name}`, { type: "success" });
                    this.state.lastScannedProduct = res.product_id;
                    this.state.pickingRefreshTick += 1;
                }
            } catch (e) {
                this.playSound('error');
                this.notification.add("Server error", { type: "danger" });
            } finally {
                this.state.isProcessing = false;
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
                await this.closeCamera();
                this.state.showCameraPopup = false;

                if (result.type === 'picking') {
                    this.state.isProcessing = false;
                    await this.selectPicking(result.id, result.name);
                } else {
                    this.pushHistory();
                    this.state.warehouseCode = result.warehouse_code || "HLV";
                    this.state.lookupType = result.type;
                    this.state.recordId = result.id;
                    this.state.lookupTitle = result.name;
                    this.state.currentView = 'lookup';
                    
                    // Start persistent inline camera on the newly loaded view
                    setTimeout(async () => {
                        await this.startPersistentCamera(false);
                    }, 200);
                }
            }
        } catch (error) {
            this.playSound('error');
            this.notification.add("Server error", { type: "danger" });
        } finally {
            this.state.isProcessing = false;
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
            warehouseCode: this.state.warehouseCode,
            lookupType: this.state.lookupType,
            recordId: this.state.recordId,
            lookupTitle: this.state.lookupTitle,
            prefillLocationBarcode: this.state.prefillLocationBarcode,
            prefillLocationName: this.state.prefillLocationName,
            isMultiLocationMode: this.state.isMultiLocationMode,
        });
    }

    async goBack() {
        const currentPickingId = this.state.pickingId;
        const currentView = this.state.currentView;

        if (currentView === 'picking' && this.state.pickingState !== 'done' && currentPickingId) {
            this.state.pendingExitAction = 'back';
            this.state.showExitOptions = true;
            return;
        } else if (currentView === 'picking' && currentPickingId) {
            const storageKey = 'hlv_opened_pickings';
            try {
                let opened = JSON.parse(localStorage.getItem(storageKey) || '[]');
                opened = opened.filter(id => id !== currentPickingId);
                localStorage.setItem(storageKey, JSON.stringify(opened));
            } catch (e) {}
        }

        await this._executeGoBack();
    }

    async _executeGoBack() {
        await this.closeCamera();
        this.state.showCameraPopup = false;

        if (this.history && this.history.length > 0) {
            const prevState = this.history.pop();
            
            this.state.currentView = prevState.currentView;
            this.state.pickingId = prevState.pickingId;
            this.state.pickingName = prevState.pickingName;
            this.state.warehouseCode = prevState.warehouseCode || "";
            this.state.lookupType = prevState.lookupType;
            this.state.recordId = prevState.recordId;
            this.state.lookupTitle = prevState.lookupTitle;
            this.state.prefillLocationBarcode = prevState.prefillLocationBarcode;
            this.state.prefillLocationName = prevState.prefillLocationName;
            this.state.isMultiLocationMode = prevState.isMultiLocationMode || false;
            this.state.pickingState = "";
            this.viewScannerCallback = null;

            if (this.state.currentView !== 'main') {
                setTimeout(async () => {
                    await this.startPersistentCamera(false);
                }, 150);
            }
        } else {
            await this._executeGoToMain();
        }
    }

    async goToMain(ev) {
        const currentPickingId = this.state.pickingId;
        const currentView = this.state.currentView;

        if (currentView === 'picking' && this.state.pickingState !== 'done' && currentPickingId) {
            this.state.pendingExitAction = 'main';
            this.state.showExitOptions = true;
            return;
        } else if (currentView === 'picking' && currentPickingId) {
            const storageKey = 'hlv_opened_pickings';
            try {
                let opened = JSON.parse(localStorage.getItem(storageKey) || '[]');
                opened = opened.filter(id => id !== currentPickingId);
                localStorage.setItem(storageKey, JSON.stringify(opened));
            } catch (e) {}
        }

        await this._executeGoToMain();
    }

    async _executeGoToMain() {
        await this.closeCamera();
        this.state.showCameraPopup = false;

        this.history = [];
        this.state.currentView = 'main';
        this.state.pickingId = null;
        this.state.pickingName = "";
        this.state.scannedLocationId = null;
        this.state.scannedLocationName = "";
        this.state.lastScannedProduct = null;
        this.state.warehouseCode = "";
        this.state.lookupType = null;
        this.state.recordId = null;
        this.state.prefillLocationBarcode = null;
        this.state.prefillLocationName = null;
        this.state.isMultiLocationMode = false;
        this.state.pickingState = "";
        this.viewScannerCallback = null;
    }

    async confirmExit(actionType) {
        this.state.showExitOptions = false;
        if (actionType === 'cancel') {
            this.state.pendingExitAction = null;
            return;
        }

        const isClear = actionType === 'clear';
        const targetAction = this.state.pendingExitAction;
        this.state.pendingExitAction = null;

        if (isClear) {
            this.state.isProcessing = true;
            try {
                const res = await rpc("/hlv_mobile_barcode/clear_and_cancel_picking", { picking_id: this.state.pickingId });
                if (res && res.error) {
                    this.notification.add(res.error, { type: "danger" });
                } else {
                    this.notification.add("Đã hủy phiếu và giải phóng sản phẩm thành công.", { type: "success" });
                }
            } catch (e) {
                console.error("Cancel error:", e);
            } finally {
                this.state.isProcessing = false;
            }
        }
        
        const storageKey = 'hlv_opened_pickings';
        try {
            let opened = JSON.parse(localStorage.getItem(storageKey) || '[]');
            opened = opened.filter(id => id !== this.state.pickingId);
            localStorage.setItem(storageKey, JSON.stringify(opened));
        } catch (e) {}

        if (targetAction === 'back') {
            await this._executeGoBack();
        } else {
            await this._executeGoToMain();
        }
    }

    goToMove(productId, locationBarcode = null, locationName = null, destWarehouseId = false, destLocationId = false) {
        this.pushHistory();
        this.state.recordId = productId;
        this.state.prefillLocationBarcode = locationBarcode;
        this.state.prefillLocationName = locationName;
        this.state.destWarehouseId = destWarehouseId;
        this.state.destLocationId = destLocationId;
        this.state.currentView = 'move';
    }

    promptMoveWarehouse(productId, locBarcode, locName, qty, productName) {
        this.pushHistory();
        this.state.recordId = productId;
        this.state.prefillLocationBarcode = locBarcode;
        this.state.prefillLocationName = locName;
        this.state.sourceQty = qty;
        this.state.productName = productName;
        this.state.currentView = 'move';
        
        // Start persistent inline camera on the newly loaded view
        setTimeout(async () => {
            await this.startPersistentCamera(false);
        }, 200);
    }

    promptBatchMoveWarehouse(locBarcode, locName) {
        this.pendingBatchMove = { locBarcode, locName, multiLocation: false };
        this.resetDestPopupState();
        this.state.showWarehouseSelectPopup = true;
    }

    promptMultiLocationMove() {
        this.pendingBatchMove = { multiLocation: true };
        this.state.multiLocationSourceWarehouseId = this.state.warehouses && this.state.warehouses.length > 0 ? this.state.warehouses[0].id.toString() : false;
        this.resetDestPopupState();
        this.state.showWarehouseSelectPopup = true;
    }

    resetDestPopupState() {
        this.state.selectedWarehouseId = null;
        this.state.destSelectionMode = 'location';
        this.state.destLocationBarcode = "";
        this.state.destLocationName = "";
        this.state.destLocationId = null;
        this.state.moveQty = 0;
        this.state.sourceQty = 0;
    }

    setDestSelectionMode(mode) {
        this.state.destSelectionMode = mode;
    }

    async validateDestLocation() {
        if (!this.state.destLocationBarcode) return;
        this.state.isLocatingDest = true;
        try {
            const result = await rpc("/hlv_mobile_barcode/smart_scan", { 
                barcode: this.state.destLocationBarcode 
            });
            
            if (result.error) {
                this.notification.add(result.error, { type: "danger" });
                this.state.destLocationName = "";
                this.state.destLocationId = null;
            } else if (result.type === 'location') {
                this.state.destLocationName = result.name;
                this.state.destLocationId = result.id;
                
                // Tự động xác nhận chuyển trang nếu vị trí đúng
                await this.confirmWarehouseSelection();
            } else {
                this.notification.add("Mã vạch không phải là vị trí", { type: "danger" });
                this.state.destLocationName = "";
                this.state.destLocationId = null;
            }
        } catch (error) {
            this.notification.add("Lỗi kết nối", { type: "danger" });
        } finally {
            this.state.isLocatingDest = false;
        }
    }

    closeWarehousePopup() {
        this.state.showWarehouseSelectPopup = false;
        this.pendingBatchMove = null;
        this.pendingMove = null;
    }

    selectWarehouse(whId) {
        this.state.selectedWarehouseId = whId;
    }

    async confirmWarehouseSelection() {
        const isLoc = this.state.destSelectionMode === 'location';
        
        if (isLoc && !this.state.destLocationId) {
            this.notification.add("Vui lòng quét hoặc nhập vị trí đích hợp lệ", { type: "warning" });
            return;
        }
        if (!isLoc && !this.state.selectedWarehouseId) {
            this.notification.add("Vui lòng chọn kho đích", { type: "warning" });
            return;
        }
        
        const destWarehouseId = isLoc ? false : this.state.selectedWarehouseId;
        const destLocationId = isLoc ? this.state.destLocationId : false;
        
        const pendingBatchMove = this.pendingBatchMove;
        
        let sourceWarehouseId = false;
        if (pendingBatchMove && pendingBatchMove.multiLocation) {
            sourceWarehouseId = this.state.multiLocationSourceWarehouseId;
        }
        
        this.closeWarehousePopup();
        
        if (pendingBatchMove) {
            if (pendingBatchMove.multiLocation) {
                await this.goToBatchMove(null, null, destWarehouseId, destLocationId, true, sourceWarehouseId);
            } else {
                const { locBarcode, locName } = pendingBatchMove;
                await this.goToBatchMove(locBarcode, locName, destWarehouseId, destLocationId, false);
            }
        }
    }

    async goToBatchMove(locationBarcode, locationName, destWarehouseId = false, destLocationId = false, isMultiLocation = false, sourceWarehouseId = false) {
        // Now redirects to a newly created empty INT picking
        this.pushHistory();
        try {
            this.notification.add("Đang tạo phiếu xuất...", { type: "info" });
            const res = await rpc("/hlv_mobile_barcode/create_empty_int", {
                location_id: this.state.recordId,
                dest_warehouse_id: destWarehouseId,
                dest_location_id: destLocationId,
                is_multi_location: isMultiLocation,
                source_warehouse_id: sourceWarehouseId
            });
            
            if (res.error) {
                this.notification.add(res.error, { type: "danger" });
                this.goBack();
            } else {
                this.state.pickingId = res.picking_id;
                this.state.pickingName = res.picking_name;
                this.state.warehouseCode = res.warehouse_code || "HLV";
                this.state.scannedLocationId = isMultiLocation ? null : res.location_id;
                this.state.scannedLocationName = isMultiLocation ? "" : res.location_name;
                this.state.currentView = 'picking';
                this.state.isMultiLocationMode = isMultiLocation;
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

    onMoveSuccess() {
        this.state.lookupRefreshTick = (this.state.lookupRefreshTick || 0) + 1;
        this.goBack();
    }

    async selectPicking(pickingId, pickingName) {
        if (this.state.isProcessing) return;
        this.state.isProcessing = true;
        try {
            await this.closeCamera();
            this.pushHistory();
            this.state.pickingId = pickingId;
            this.state.pickingName = pickingName;
            this.state.currentView = 'picking';
            this.state.scannedLocationId = null;
            this.state.scannedLocationName = "";
            this.state.lastScannedProduct = null;
            this.state.pickingState = "";
            this.state.pickingRefreshTick += 1;

            // Tải vị trí nguồn mặc định của phiếu để hiển thị trực tiếp lên tiêu đề
            rpc("/hlv_mobile_barcode/get_picking_data", { picking_id: pickingId }).then((data) => {
                if (data && !data.error) {
                    if (data.is_putaway && data.location_dest_name) {
                        this.state.scannedLocationId = data.location_dest_id;
                        this.state.scannedLocationName = data.location_dest_name;
                    } else if (!data.is_putaway && data.location_name) {
                        this.state.scannedLocationId = data.location_id;
                        this.state.scannedLocationName = data.location_name;
                    }
                }
            }).catch(() => {});
            
            setTimeout(async () => {
                await this.startPersistentCamera(false);
            }, 150);
        } finally {
            this.state.isProcessing = false;
        }
    }

    onPickingStateLoaded(pickingState) {
        this.state.pickingState = pickingState;
    }

    openPopupCamera() {
        this.state.showCameraPopup = true;
        setTimeout(() => {
            this.startPersistentCamera(false);
        }, 150);
    }

    async closePopupCamera() {
        await this.closeCamera();
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
            await this.closeCamera();

            // Wait for the #reader element to be mounted in the DOM (async transitions)
            let readerEl = document.getElementById("reader");
            let retries = 0;
            while (!readerEl && retries < 15) {
                await new Promise(resolve => setTimeout(resolve, 50));
                readerEl = document.getElementById("reader");
                retries++;
            }

            if (!readerEl) {
                console.warn("Html5Qrcode: #reader element not found in DOM after retries.");
                return;
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
                        if (this.html5Qrcode) {
                            const state = this.html5Qrcode.getState();
                            // 3 is PAUSED in Html5QrcodeScannerState
                            if (state === 3 || (window.Html5QrcodeScannerState && state === window.Html5QrcodeScannerState.PAUSED)) {
                                try { this.html5Qrcode.resume(); } catch(e) {}
                            }
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
        
        const qrcode = this.html5Qrcode;
        this.html5Qrcode = null; // Immediately nullify to prevent concurrent access
        
        if (qrcode) {
            try {
                await qrcode.stop();
            } catch (e) {}
            try {
                qrcode.clear();
            } catch (e) {}
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
        
        this.state.isProcessing = true;
        try {
            const res = await rpc("/hlv_mobile_barcode/clear_quantities", {
                picking_id: this.state.pickingId,
            });
            if (res.error) {
                this.notification.add(res.error, { type: "danger" });
            } else {
                // Remove from localStorage opened pickings to ensure clean re-load
                const storageKey = 'hlv_opened_pickings';
                try {
                    let opened = JSON.parse(localStorage.getItem(storageKey) || '[]');
                    opened = opened.filter(id => id !== this.state.pickingId);
                    localStorage.setItem(storageKey, JSON.stringify(opened));
                } catch (e) {}
                
                this.notification.add("Đã làm mới số lượng", { type: "success" });
                this.state.scannedLocationId = null;
                this.state.scannedLocationName = "";
                this.state.lastScannedProduct = null;
                this.state.pickingRefreshTick += 1;
                window.location.reload();
            }
        } catch (e) {
            this.notification.add("Lỗi kết nối", { type: "danger" });
        } finally {
            this.state.isProcessing = false;
        }
    }
}

registry.category("actions").add("hlv_mobile_barcode.BarcodeApp", BarcodeApp);

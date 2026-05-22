/** @odoo-module **/

import { Component, useState, onMounted, useEffect } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { PickingScanner } from "../picking_scanner/picking_scanner";
import { InventoryLookup } from "../inventory_lookup/inventory_lookup";
import { LocationMove } from "../location_move/location_move";

export class BarcodeApp extends Component {
    static template = "hlv_mobile_barcode.BarcodeApp";
    static components = { PickingScanner, InventoryLookup, LocationMove };

    setup() {
        this.notification = useService("notification");
        this.action = useService("action");
        
        let savedState = {};
        try {
            const stored = sessionStorage.getItem('hlv_barcode_state');
            if (stored) {
                savedState = JSON.parse(stored);
            }
        } catch (e) {}

        this.state = useState({
            currentView: savedState.currentView || "main", 
            manualBarcode: "",
            pickingId: savedState.pickingId || null,
            pickingName: savedState.pickingName || "",
            lookupType: savedState.lookupType || null,
            recordId: savedState.recordId || null,
            lookupTitle: savedState.lookupTitle || "",
            showCamera: false,
            cameraFallback: false,
        });
        
        useEffect(() => {
            sessionStorage.setItem('hlv_barcode_state', JSON.stringify({
                currentView: this.state.currentView,
                pickingId: this.state.pickingId,
                pickingName: this.state.pickingName,
                lookupType: this.state.lookupType,
                recordId: this.state.recordId,
                lookupTitle: this.state.lookupTitle,
            }));
        }, () => [
            this.state.currentView,
            this.state.pickingId,
            this.state.pickingName,
            this.state.lookupType,
            this.state.recordId,
            this.state.lookupTitle
        ]);

        this.barcodeBuffer = "";
        this.barcodeTimeout = null;
        
        onMounted(() => {
            document.addEventListener('keydown', this.handleKeyDown.bind(this));
        });
    }

    handleKeyDown(e) {
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
        
        this.state.showCamera = false;
        
        if (this.viewScannerCallback) {
            this.viewScannerCallback(barcode);
            return;
        }

        if (this.state.currentView === 'picking') {
            try {
                const res = await rpc("/hlv_mobile_barcode/process_barcode", { 
                    picking_id: this.state.pickingId, 
                    barcode: barcode 
                });
                if (res.error) {
                    this.playSound('error');
                    this.notification.add(res.error, { type: "danger" });
                } else {
                    this.playSound('success');
                    this.notification.add(`Scanned ${res.product_name}`, { type: "success" });
                    this.state.lastScannedProduct = res.product_id;
                }
            } catch (e) {
                this.playSound('error');
                this.notification.add("Server error", { type: "danger" });
            }
            await this.closeCamera();
            return;
        }
        
        try {
            const result = await rpc("/hlv_mobile_barcode/smart_scan", { barcode });
            if (result.error) {
                this.playSound('error');
                this.notification.add(result.error, { type: "danger" });
                await this.closeCamera();
                return;
            }
            
            this.playSound('success');
            await this.closeCamera();
            
            if (result.type === 'picking') {
                this.state.pickingId = result.id;
                this.state.pickingName = result.name;
                this.state.currentView = 'picking';
            } else if (['product', 'location', 'package'].includes(result.type)) {
                this.state.lookupType = result.type;
                this.state.recordId = result.id;
                this.state.lookupTitle = result.name;
                this.state.currentView = 'lookup';
            }
        } catch (error) {
            this.playSound('error');
            this.notification.add("Server error", { type: "danger" });
            await this.closeCamera();
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

    goToMain() {
        this.state.currentView = 'main';
        this.state.pickingId = null;
        this.state.lookupType = null;
        this.state.recordId = null;
        this.viewScannerCallback = null;
    }

    goToMove(productId, locationBarcode = null, locationName = null) {
        this.state.recordId = productId;
        this.state.prefillLocationBarcode = locationBarcode;
        this.state.prefillLocationName = locationName;
        this.state.currentView = 'move';
    }

    async openCamera() {
        this.state.showCamera = true;
        
        await new Promise(r => setTimeout(r, 100));

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
                this.state.showCamera = false;
                return;
            }
        }
        
        try {
            this.html5Qrcode = new window.Html5Qrcode("reader");
            
            const config = { 
                fps: 20,               
                disableFlip: false,    
                aspectRatio: 1.0,      
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
                },
                (errorMessage) => {
                    // ignore parse errors
                }
            );
        } catch (err) {
            const errStr = String(err).toLowerCase();
            if (errStr.includes("notallowederror") || errStr.includes("permission")) {
                this.notification.add("Trình duyệt từ chối quyền Camera. Đã chuyển sang chế độ chụp ảnh/chọn file.", { type: "info" });
                this.state.cameraFallback = true;
            } else {
                this.notification.add("Không thể mở Camera. Lỗi: " + err, { type: "warning" });
                await this.closeCamera();
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
            await this.closeCamera();
        }
    }

    async closeCamera() {
        this.state.showCamera = false;
        this.state.cameraFallback = false;
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
}

registry.category("actions").add("hlv_mobile_barcode.BarcodeApp", BarcodeApp);

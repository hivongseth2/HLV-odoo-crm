/** @odoo-module **/

import { Component, useState, onMounted } from "@odoo/owl";
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
        
        this.state = useState({
            currentView: "main", // 'main', 'picking', 'lookup'
            manualBarcode: "",
            pickingId: null,
            pickingName: "",
            lookupType: null, // 'product', 'location', 'package'
            recordId: null,
            lookupTitle: "",
        });
        
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

    async processBarcode(barcode) {
        if (!barcode) return;
        
        if (this.state.currentView === 'picking') {
            // Check if it's a product to process in picking
            try {
                const res = await rpc("/hlv_mobile_barcode/process_barcode", { 
                    picking_id: this.state.pickingId, 
                    barcode: barcode 
                });
                if (res.error) {
                    // It might not be a product, maybe it's another picking or something else.
                    // For now, if it's not a product in picking, we show error.
                    this.notification.add(res.error, { type: "danger" });
                } else {
                    this.notification.add(`Scanned ${res.product_name}`, { type: "success" });
                    // Force re-render of picking scanner by toggling state or calling a method
                    // A simple way is to pass a prop that changes
                    this.state.lastScannedProduct = res.product_id;
                }
            } catch (e) {
                this.notification.add("Server error", { type: "danger" });
            }
            return;
        }
        
        try {
            const result = await rpc("/hlv_mobile_barcode/smart_scan", { barcode });
            if (result.error) {
                this.notification.add(result.error, { type: "danger" });
                return;
            }
            
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
            this.notification.add("Server error", { type: "danger" });
        }
    }

    goToMain() {
        this.state.currentView = 'main';
        this.state.pickingId = null;
        this.state.lookupType = null;
        this.state.recordId = null;
    }

    goToMove(productId) {
        this.state.recordId = productId;
        this.state.currentView = 'move';
    }

    openCamera() {
        this.notification.add("Camera integration requires HTTPS and WebRTC support.", { type: "info" });
    }
}

registry.category("actions").add("hlv_mobile_barcode.BarcodeApp", BarcodeApp);

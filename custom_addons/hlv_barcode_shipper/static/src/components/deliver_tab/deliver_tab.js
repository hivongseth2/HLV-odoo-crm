/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { CameraScanner } from "../camera_scanner/camera_scanner";
import { BarcodeApiService } from "../../services/barcode_api_service";

export class DeliverTab extends Component {
    static template = "hlv_barcode_shipper.DeliverTab";
    static components = { CameraScanner };

    setup() {
        this.state = useState({
            step: "scan_pick", // scan_pick, scan_items, photo
            showCamera: false,
            searchQuery: "",
            errorMessage: "",
            isLoading: false,
            activePickingId: null,
            scannedItems: []
        });
    }

    onBarcodeScanned(barcode) {
        this.state.searchQuery = barcode;
        this.state.showCamera = false;
        this.scanPickOrder();
    }

    async scanPickOrder() {
        this.state.isLoading = true;
        this.state.errorMessage = "";
        try {
            // Giả lập call API, sau này sẽ map hàm từ barcode_scanner.js
            console.log("Scanning pick order:", this.state.searchQuery);
            // const res = await BarcodeApiService.callApi('/api/barcode/pick/scan', { barcode: this.state.searchQuery });
        } catch (error) {
            this.state.errorMessage = "Có lỗi xảy ra: " + error.message;
        } finally {
            this.state.isLoading = false;
        }
    }
}

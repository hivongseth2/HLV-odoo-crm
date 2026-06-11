/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { CameraScanner } from "../camera_scanner/camera_scanner";
import { BarcodeApiService } from "../../services/barcode_api_service";

export class ReturnTab extends Component {
    static template = "hlv_barcode_shipper.ReturnTab";
    static components = { CameraScanner };

    setup() {
        this.state = useState({
            step: "list", // list, scan_detail
            showCamera: false,
            searchQuery: "",
            isLoading: false,
            returnPickings: []
        });
    }

    onBarcodeScanned(barcode) {
        this.state.searchQuery = barcode;
        this.state.showCamera = false;
        // logic find return picking
    }
}

/** @odoo-module **/

import { Component, xml, useState } from "@odoo/owl";
import { CameraScanner } from "../camera_scanner/camera_scanner";
import { BarcodeApiService } from "../../services/barcode_api_service";

export class ReceiveTab extends Component {
    static template = xml`<div class="tab-content active">
            <!-- Step 1: Scan / Search List -->
            <div t-if="state.step === 'list'" class="scan-step active">
                
                <!-- Bọc Camera component dùng chung -->
                <t t-if="state.showCamera">
                    <CameraScanner 
                        onBarcodeScanned="onBarcodeScanned.bind(this)" 
                        onClose="() => state.showCamera = false" 
                    />`;
    static components = { CameraScanner };

    setup() {
        this.state = useState({
            step: "list", // list, detail
            showCamera: false,
            searchQuery: "",
            isLoading: false,
            errorMessage: "",
            soGroups: [],
        });
    }

    onSearchKeyUp(ev) {
        if (ev.key === "Enter") {
            this.searchPickings();
        }
    }

    async searchPickings() {
        this.state.isLoading = true;
        this.state.errorMessage = "";
        this.state.soGroups = [];
        try {
            const res = await BarcodeApiService.getAvailableToReceive(this.state.searchQuery);
            if (res.success) {
                this.state.soGroups = res.so_groups || [];
                if (this.state.soGroups.length === 0) {
                    this.state.errorMessage = "Không tìm thấy phiếu nào.";
                }
            } else {
                this.state.errorMessage = res.error || "Lỗi tìm kiếm.";
            }
        } catch (error) {
            this.state.errorMessage = "Lỗi kết nối API: " + error.message;
        } finally {
            this.state.isLoading = false;
        }
    }

    onBarcodeScanned(barcode) {
        this.state.searchQuery = barcode;
        this.state.showCamera = false;
        this.searchPickings();
    }
}

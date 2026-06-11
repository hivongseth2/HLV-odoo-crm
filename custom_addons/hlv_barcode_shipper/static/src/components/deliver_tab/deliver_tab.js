/** @odoo-module **/

import { Component, xml, useState } from "@odoo/owl";
import { CameraScanner } from "../camera_scanner/camera_scanner";
import { BarcodeApiService } from "../../services/barcode_api_service";

export class DeliverTab extends Component {
    static template = xml`<div class="tab-content active">
            <div t-if="state.step === 'scan_pick'" class="scan-step active">
                
                <t t-if="state.showCamera">
                    <CameraScanner 
                        onBarcodeScanned="onBarcodeScanned.bind(this)" 
                        onClose="() => state.showCamera = false" 
                    />
                </t>

                <div class="scan-bar-card">
                    <t t-if="state.errorMessage">
                        <div class="alert alert-danger"><t t-esc="state.errorMessage"/></div>
                    </t>
                    <div class="input-group-row" style="margin-bottom:0;">
                        <input type="text" class="form-control"
                            placeholder="Quét mã phiếu PICK / Đơn hàng để lấy thông tin..."
                            t-model="state.searchQuery"
                            autocomplete="off" inputmode="none"/>
                        <button class="btn btn-secondary" title="Quét phiếu" t-on-click="scanPickOrder">
                            <i class="fa fa-search"></i>
                        </button>
                        <button class="btn btn-primary" title="Mở camera" t-on-click="() => state.showCamera = true">
                            <i class="fa fa-camera"></i>
                        </button>
                    </div>
                </div>

                <div class="mt-3 text-center text-muted">
                    <p>Quy trình Giao Hàng bao gồm: Quét mã PICK -> Quét từng kiện hàng -> Ký nhận/Chụp ảnh.<br/> Tính năng đang trong quá trình chuyển đổi sang OWL.</p>
                </div>
            </div>
        </div>`;
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

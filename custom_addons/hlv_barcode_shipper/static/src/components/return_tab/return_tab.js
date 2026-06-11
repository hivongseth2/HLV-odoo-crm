/** @odoo-module **/

import { Component, xml, useState } from "@odoo/owl";
import { CameraScanner } from "../camera_scanner/camera_scanner";
import { BarcodeApiService } from "../../services/barcode_api_service";

export class ReturnTab extends Component {
    static template = xml`<div class="tab-content active">
            <div class="scan-step active">
                <t t-if="state.showCamera">
                    <CameraScanner 
                        onBarcodeScanned="onBarcodeScanned.bind(this)" 
                        onClose="() => state.showCamera = false" 
                    />
                </t>

                <div class="scan-bar-card">
                    <div class="input-group-row" style="margin-bottom:0;">
                        <input type="text" class="form-control"
                            placeholder="Quét mã vạch kiện hàng hoặc phiếu xuất để trả hàng..."
                            t-model="state.searchQuery"
                            autocomplete="off" inputmode="none"/>
                        <button class="btn btn-secondary" title="Tìm kiếm">
                            <i class="fa fa-search"></i>
                        </button>
                        <button class="btn btn-primary" title="Mở camera" t-on-click="() => state.showCamera = true">
                            <i class="fa fa-camera"></i>
                        </button>
                    </div>
                </div>

                <div class="mt-3 text-center text-muted">
                    <p>Danh sách các phiếu cần Trả Hàng (Return). Đang cấu trúc...</p>
                </div>
            </div>
        </div>`;
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

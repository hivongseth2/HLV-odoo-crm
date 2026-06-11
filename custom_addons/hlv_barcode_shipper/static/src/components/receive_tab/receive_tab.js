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
                    ></CameraScanner>
                </t>

                <!-- Scan bar -->
                <div class="scan-bar-card">
                    <t t-if="state.errorMessage">
                        <div class="alert alert-danger"><t t-esc="state.errorMessage"/></div>
                    </t>
                    <div class="input-group-row" style="margin-bottom:0;">
                        <input type="text" class="form-control"
                            placeholder="Quét mã phiếu / đơn hàng để tìm nhanh..."
                            t-model="state.searchQuery"
                            t-on-keyup="onSearchKeyUp"
                            autocomplete="off" inputmode="none"/>
                        <button class="btn btn-secondary" title="Tìm kiếm" t-on-click="searchPickings">
                            <i class="fa fa-search"></i>
                        </button>
                        <button class="btn btn-primary" title="Mở camera" t-on-click="() => state.showCamera = true">
                            <i class="fa fa-camera"></i>
                        </button>
                    </div>
                </div>

                <!-- List Placeholder -->
                <div class="receive-available-accordion mt-3">
                    <t t-if="state.isLoading">
                        <div class="loading-placeholder text-center">
                            <i class="fa fa-spinner fa-spin" style="font-size:1.5rem;color:#aaa;"></i>
                            <div style="color:#888;margin-top:8px;">Đang tìm kiếm phiếu...</div>
                        </div>
                    </t>
                    <t t-else="">
                        <t t-if="state.soGroups.length > 0">
                            <t t-foreach="state.soGroups" t-as="group" t-key="group.so_name">
                                <div class="card mb-2 shadow-sm">
                                    <div class="card-header bg-light">
                                        <strong><t t-esc="group.so_name"/></strong> - <t t-esc="group.partner"/>
                                    </div>
                                    <ul class="list-group list-group-flush">
                                        <t t-foreach="group.pickings" t-as="picking" t-key="picking.id">
                                            <li class="list-group-item d-flex justify-content-between align-items-center">
                                                <span>
                                                    <t t-esc="picking.name"/><br/>
                                                    <small class="text-muted"><t t-esc="picking.origin"/></small>
                                                </span>
                                                <button class="btn btn-sm btn-outline-primary">Chọn</button>
                                            </li>
                                        </t>
                                    </ul>
                                </div>
                            </t>
                        </t>
                        <t t-else="">
                            <div class="text-center p-3 text-muted">
                                <i class="fa fa-box-open fa-2x mb-2"></i>
                                <p>Chưa có dữ liệu phiếu Nhận Hàng.</p>
                            </div>
                        </t>
                    </t>
                </div>

            </div>

            <!-- Các Step khác của Nhận hàng sẽ đặt ở đây -->
        </div>`;
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

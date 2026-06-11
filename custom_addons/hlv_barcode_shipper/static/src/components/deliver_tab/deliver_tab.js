/** @odoo-module **/

import { Component, xml, useState } from "@odoo/owl";
import { CameraScanner } from "../camera_scanner/camera_scanner";
import { BarcodeApiService } from "../../services/barcode_api_service";
import { DeliveryDetail } from "./delivery_detail";

export class DeliverTab extends Component {
    static template = xml`<div class="tab-content active">
        
        <!-- Step 1: Scan / Search List -->
        <div t-if="state.step === 'list'" class="scan-step active">
            
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
                        placeholder="Quét mã phiếu lấy hàng (PICK) để tìm OUT..."
                        t-model="state.searchQuery"
                        t-on-keyup="onSearchKeyUp"
                        autocomplete="off" inputmode="none"/>
                    <button class="btn btn-secondary" title="Tìm kiếm" t-on-click="searchPickOrder">
                        <i class="fas fa-search"></i>
                    </button>
                    <button class="btn btn-primary" title="Mở camera" t-on-click="() => state.showCamera = true">
                        <i class="fas fa-camera"></i>
                    </button>
                </div>
            </div>

            <!-- List of Outgoing Pickings -->
            <div class="deliver-available-accordion mt-3">
                <t t-if="state.isLoading">
                    <div class="loading-placeholder text-center p-4">
                        <i class="fas fa-spinner fa-spin" style="font-size:2rem;color:#1591DC;"></i>
                        <div style="color:#666;margin-top:10px;">Đang tìm phiếu xuất kho...</div>
                    </div>
                </t>
                <t t-else="">
                    <t t-if="state.soGroups.length > 0">
                        <div class="alert alert-info p-2 mb-2">
                            <strong>Khách hàng: </strong> <t t-esc="state.customerName"/>
                        </div>
                        <div class="d-flex justify-content-between align-items-center mb-2 px-2">
                            <span class="text-muted"><i class="fas fa-list-ul"></i> Danh sách phiếu xuất:</span>
                            <button class="btn btn-sm btn-outline-secondary" t-on-click="toggleSelectAll">
                                <i class="fas fa-check-double"></i> Chọn/Bỏ tất cả
                            </button>
                        </div>
                        
                        <t t-foreach="state.soGroups" t-as="group" t-key="group.so_name">
                            <div class="card mb-2 shadow-sm border-primary">
                                <div class="card-header bg-light text-primary py-2 d-flex justify-content-between align-items-center">
                                    <strong><t t-esc="group.so_name"/></strong>
                                </div>
                                <ul class="list-group list-group-flush">
                                    <t t-foreach="group.pickings" t-as="picking" t-key="picking.id">
                                        <li class="list-group-item d-flex justify-content-between align-items-center cursor-pointer"
                                            t-on-click="() => this.togglePicking(picking.id)">
                                            <div>
                                                <div class="font-weight-bold"><t t-esc="picking.name"/></div>
                                                <small class="text-muted"><t t-esc="picking.scheduled_date"/></small>
                                            </div>
                                            <div class="custom-control custom-checkbox" style="pointer-events:none;">
                                                <input type="checkbox" class="custom-control-input" t-att-checked="state.selectedPickings.includes(picking.id)"/>
                                                <label class="custom-control-label"></label>
                                            </div>
                                        </li>
                                    </t>
                                </ul>
                            </div>
                        </t>

                        <!-- Action Button -->
                        <div class="fixed-bottom p-3 bg-white border-top shadow-lg" style="bottom: 0; z-index: 1000; left: 0; right: 0;">
                            <button class="btn btn-primary btn-block btn-lg" 
                                    t-att-disabled="state.selectedPickings.length === 0"
                                    t-on-click="startDelivery">
                                Bắt đầu giao <t t-if="state.selectedPickings.length > 0">(<t t-esc="state.selectedPickings.length"/> đơn)</t>
                                <i class="fas fa-arrow-right ml-2"></i>
                            </button>
                        </div>
                        <div style="height: 80px;"></div> <!-- Spacer -->
                    </t>
                    <t t-else="">
                        <div class="text-center p-5 text-muted" style="margin-top: 30px;">
                            <i class="fas fa-truck-loading" style="font-size: 4rem; color: #e0e0e0; margin-bottom: 15px;"></i>
                            <p style="color: #999;">Nhập mã phiếu Nhặt hàng (PICK) để tìm đơn Xuất kho (OUT) cần giao</p>
                            
                            <div class="mt-5 d-flex justify-content-center gap-5">
                                <button class="btn btn-text text-secondary" style="font-size: 0.95rem;"><i class="fas fa-history"></i> Lịch sử</button>
                            </div>
                        </div>
                    </t>
                </t>
            </div>
        </div>

        <!-- Step 2: Delivery Details -->
        <div t-if="state.step === 'detail'" class="scan-step active">
            <DeliveryDetail 
                data="state.deliveryData" 
                onBack="() => state.step = 'list'"
                onComplete="() => this.onDeliveryDetailComplete()"
            ></DeliveryDetail>
        </div>

    </div>`;
    
    static components = { CameraScanner, DeliveryDetail };

    setup() {
        this.state = useState({
            step: "list", // list, detail, photo
            showCamera: false,
            searchQuery: "",
            isLoading: false,
            errorMessage: "",
            soGroups: [],
            customerName: "",
            selectedPickings: [],
            
            // Detail states
            deliveryData: [], 
        });
    }

    onSearchKeyUp(ev) {
        if (ev.key === "Enter") {
            this.searchPickOrder();
        }
    }

    onBarcodeScanned(barcode) {
        this.state.searchQuery = barcode;
        this.state.showCamera = false;
        this.searchPickOrder();
    }

    async searchPickOrder() {
        if (!this.state.searchQuery) return;
        
        this.state.isLoading = true;
        this.state.errorMessage = "";
        this.state.soGroups = [];
        this.state.selectedPickings = [];
        
        try {
            const res = await BarcodeApiService.scanPickOrder(this.state.searchQuery);
            if (res.success) {
                this.state.soGroups = res.so_groups || [];
                this.state.customerName = res.customer_name || "Khách hàng";
                
                // Tự động chọn tất cả các phiếu
                const allIds = [];
                this.state.soGroups.forEach(group => {
                    group.pickings.forEach(p => allIds.push(p.id));
                });
                this.state.selectedPickings = allIds;
            } else {
                this.state.errorMessage = res.error || "Không tìm thấy phiếu.";
            }
        } catch (error) {
            this.state.errorMessage = "Lỗi kết nối API: " + error.message;
        } finally {
            this.state.isLoading = false;
        }
    }

    togglePicking(id) {
        const index = this.state.selectedPickings.indexOf(id);
        if (index > -1) {
            this.state.selectedPickings.splice(index, 1);
        } else {
            this.state.selectedPickings.push(id);
        }
    }

    toggleSelectAll() {
        const allIds = [];
        this.state.soGroups.forEach(group => {
            group.pickings.forEach(p => allIds.push(p.id));
        });
        
        if (this.state.selectedPickings.length === allIds.length) {
            // Deselect all
            this.state.selectedPickings = [];
        } else {
            // Select all
            this.state.selectedPickings = allIds;
        }
    }

    async startDelivery() {
        if (this.state.selectedPickings.length === 0) return;
        
        this.state.isLoading = true;
        this.state.errorMessage = "";
        try {
            const res = await BarcodeApiService.getMultipleOutDetails(this.state.selectedPickings);
            if (res.success) {
                this.state.deliveryData = res.data;
                this.state.step = 'detail';
            } else {
                this.state.errorMessage = res.error || "Không thể lấy chi tiết đơn giao.";
            }
        } catch (error) {
            this.state.errorMessage = "Lỗi API getMultipleOutDetails: " + error.message;
        } finally {
            this.state.isLoading = false;
        }
    }

    onDeliveryDetailComplete() {
        // Chuyển sang màn hình chụp ảnh & signature
        this.state.step = 'photo';
        // (Sẽ triển khai DeliveryPhoto sau)
    }
}

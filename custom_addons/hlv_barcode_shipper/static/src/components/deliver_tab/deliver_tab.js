/** @odoo-module **/

import { Component, xml, useState } from "@odoo/owl";
import { CameraScanner } from "../camera_scanner/camera_scanner";
import { BarcodeApiService } from "../../services/barcode_api_service";
import { DeliveryDetail } from "./delivery_detail";

export class DeliverTab extends Component {
    static template = xml`<div class="tab-content active" style="height: 100%;">
        
        <!-- Step 1: Scan / Search List -->
        <div t-if="state.step === 'list'" class="scan-step active" style="height: 100%;">
            
            <t t-if="state.showCamera">
                <CameraScanner 
                    onBarcodeScanned="onBarcodeScanned.bind(this)" 
                    onClose="() => state.showCamera = false" 
                ></CameraScanner>
            </t>

            <!-- Khi CHƯA có kết quả tìm kiếm -->
            <t t-if="state.soGroups.length === 0">
                <!-- Scan bar -->
                <div class="scan-bar-card">
                    <t t-if="state.errorMessage">
                        <div class="alert alert-danger"><t t-esc="state.errorMessage"/></div>
                    </t>
                    <div class="input-group-row" style="margin-bottom:0;">
                        <input type="text" class="form-control"
                            placeholder="Quét mã phiếu (PICK) để tìm đơn..."
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

                <!-- Empty State / Loading -->
                <div class="deliver-available-accordion mt-3">
                    <t t-if="state.isLoading">
                        <div class="loading-placeholder text-center p-4">
                            <i class="fas fa-spinner fa-spin" style="font-size:2rem;color:#1591DC;"></i>
                            <div style="color:#666;margin-top:10px;">Đang tìm phiếu xuất kho...</div>
                        </div>
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
                </div>
            </t>

            <!-- Khi ĐÃ CÓ kết quả (Grab Style Map & Bottom Sheet) -->
            <t t-else="">
                <!-- MAP Background -->
                <div class="grab-map-container">
                    <button class="grab-back-btn" t-on-click="clearSearch">
                        <i class="fas fa-arrow-left"></i>
                    </button>
                    <iframe class="grab-map-iframe"
                        t-att-src="getMapUrl()"
                        allowfullscreen="true">
                    </iframe>
                </div>

                <!-- Bottom Sheet -->
                <div class="grab-bottom-sheet" t-att-class="state.sheetExpanded ? 'expanded' : ''">
                    <!-- Drag handle acts as a toggle button -->
                    <div class="grab-drag-handle" t-on-click="() => state.sheetExpanded = !state.sheetExpanded"></div>
                    
                    <div class="grab-sheet-header">
                        <h4 class="mb-1 text-primary font-weight-bold"><t t-esc="state.customerName"/></h4>
                        <div class="text-muted small">
                            <i class="fas fa-map-marker-alt text-danger mr-1"></i>
                            <t t-esc="state.customerAddress || 'Chưa có địa chỉ'"/>
                        </div>
                    </div>

                    <div class="grab-sheet-content">
                        <div class="d-flex justify-content-between align-items-center mb-3 mt-2">
                            <span class="text-muted font-weight-bold">Danh sách đơn cần giao:</span>
                            <button class="btn btn-sm btn-outline-primary" t-on-click="toggleSelectAll">
                                <i class="fas fa-check-double"></i> Chọn tất cả
                            </button>
                        </div>
                        
                        <t t-foreach="state.soGroups" t-as="group" t-key="group.so_name">
                            <div class="card mb-3 shadow-sm border-0" style="background: #f8f9fa;">
                                <div class="card-body p-2 d-flex justify-content-between align-items-center">
                                    <strong style="font-size: 1.1rem;"><t t-esc="group.so_name"/></strong>
                                    <span class="badge badge-primary badge-pill"><t t-esc="group.pickings.length"/> đơn</span>
                                </div>
                                <ul class="list-group list-group-flush" style="border-radius: 0 0 10px 10px; overflow: hidden;">
                                    <t t-foreach="group.pickings" t-as="picking" t-key="picking.id">
                                        <li class="list-group-item d-flex justify-content-between align-items-center cursor-pointer"
                                            t-on-click="() => this.togglePicking(picking.id)" style="background: transparent;">
                                            <div>
                                                <div class="font-weight-bold text-dark"><t t-esc="picking.name"/></div>
                                                <small class="text-muted"><i class="far fa-calendar-alt"></i> <t t-esc="picking.scheduled_date"/></small>
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
                    </div>

                    <div class="grab-action-bar">
                        <button class="btn btn-primary btn-block btn-lg shadow font-weight-bold" 
                                t-att-disabled="state.selectedPickings.length === 0"
                                t-on-click="startDelivery" style="border-radius: 12px; height: 50px;">
                            Bắt đầu giao hàng <t t-if="state.selectedPickings.length > 0">(<t t-esc="state.selectedPickings.length"/> đơn)</t>
                            <i class="fas fa-arrow-right ml-2"></i>
                        </button>
                    </div>
                </div>
            </t>
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
            
            // Dữ liệu list
            soGroups: [],
            customerName: "",
            customerAddress: "",
            selectedPickings: [],
            sheetExpanded: false, // Quản lý trạng thái mở rộng của Bottom Sheet
            
            // Dữ liệu Detail
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

    clearSearch() {
        this.state.searchQuery = "";
        this.state.soGroups = [];
        this.state.customerName = "";
        this.state.customerAddress = "";
        this.state.selectedPickings = [];
        this.state.sheetExpanded = false;
    }

    getMapUrl() {
        if (!this.state.customerAddress && !this.state.customerName) return "";
        const addr = this.state.customerAddress ? this.state.customerAddress : this.state.customerName;
        const query = encodeURIComponent(addr);
        return `https://maps.google.com/maps?q=${query}&t=&z=15&ie=UTF8&iwloc=&output=embed`;
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
                this.state.customerAddress = res.customer_address || "";
                this.state.sheetExpanded = false; // Mặc định thu nhỏ khi mới vào
                
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
            this.state.selectedPickings = [];
        } else {
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
        this.state.step = 'photo';
    }
}

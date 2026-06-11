/** @odoo-module **/

import { Component, xml, useState, onWillStart } from "@odoo/owl";

export class DeliveryDetail extends Component {
    static template = xml`
        <div class="delivery-detail-container pb-5">
            <div class="shipper-header bg-primary text-white p-3 d-flex align-items-center" style="position: sticky; top: 0; z-index: 10;">
                <button class="btn btn-link text-white p-0 mr-3" t-on-click="props.onBack">
                    <i class="fas fa-arrow-left fa-lg"></i>
                </button>
                <h5 class="mb-0 mx-auto">Chi tiết Giao hàng</h5>
                <div style="width:24px;"></div>
            </div>

            <div class="p-3">
                <div class="alert alert-info shadow-sm">
                    <strong>Đang giao:</strong> <t t-esc="props.pickings.length"/> phiếu
                </div>

                <!-- Barcode Input field -->
                <div class="input-group mb-3 shadow-sm">
                    <div class="input-group-prepend">
                        <span class="input-group-text bg-white"><i class="fas fa-barcode"></i></span>
                    </div>
                    <input type="text" class="form-control form-control-lg" 
                        placeholder="Quét mã SP/Combo..." 
                        t-model="state.scanInput" 
                        t-on-keyup="onScanInputKeyUp" 
                        inputmode="none" autocomplete="off" />
                    <div class="input-group-append">
                        <button class="btn btn-primary" type="button" t-on-click="onScanBtnClick">
                            <i class="fas fa-search"></i>
                        </button>
                    </div>
                </div>

                <t t-if="state.errorMessage">
                    <div class="alert alert-danger p-2"><t t-esc="state.errorMessage"/></div>
                </t>
                <t t-if="state.successMessage">
                    <div class="alert alert-success p-2"><t t-esc="state.successMessage"/></div>
                </t>

                <!-- Items List -->
                <t t-foreach="state.pickingDataList" t-as="pData" t-key="pData.id">
                    <div class="card mb-3 shadow-sm" t-att-class="pData.progress.isDone ? 'border-success' : 'border-secondary'">
                        <div class="card-header d-flex justify-content-between align-items-center"
                            t-att-class="pData.progress.isDone ? 'bg-success text-white' : 'bg-light'">
                            <div>
                                <h6 class="mb-0"><t t-esc="pData.name"/></h6>
                                <small t-if="pData.so_name"><t t-esc="pData.so_name"/></small>
                            </div>
                            <span class="badge" t-att-class="pData.progress.isDone ? 'badge-light text-success' : 'badge-primary'">
                                <t t-esc="pData.progress.done"/> / <t t-esc="pData.progress.total"/>
                            </span>
                        </div>
                        <ul class="list-group list-group-flush">
                            <!-- Hiển thị Package/Combo trước -->
                            <t t-foreach="pData.packages" t-as="pkg" t-key="pkg.id">
                                <li class="list-group-item" t-att-class="pkg.scanned ? 'bg-success-light' : ''">
                                    <div class="d-flex justify-content-between align-items-center cursor-pointer"
                                         t-on-click="() => this.togglePackageExpanded(pkg.id)">
                                        <div>
                                            <i class="fas" t-att-class="pkg.scanned ? 'fa-check-circle text-success' : 'fa-box text-warning'"></i>
                                            <strong class="ml-2"><t t-esc="pkg.name"/></strong>
                                            <div class="text-muted small ml-4 mt-1"><t t-esc="pkg.barcode"/></div>
                                        </div>
                                        <div>
                                            <span class="badge badge-secondary mr-2">x<t t-esc="pkg.qty"/></span>
                                            <i class="fas" t-att-class="state.expandedPkgs.includes(pkg.id) ? 'fa-chevron-up' : 'fa-chevron-down'"></i>
                                        </div>
                                    </div>
                                    <!-- Child items (MISA logic) -->
                                    <div t-if="state.expandedPkgs.includes(pkg.id)" class="mt-2 ml-4 pl-2 border-left">
                                        <t t-foreach="pkg.children" t-as="child" t-key="child.id">
                                            <div class="d-flex justify-content-between small py-1">
                                                <span><i class="fas fa-cube text-muted"></i> <t t-esc="child.name"/></span>
                                                <span class="text-muted">SL: <t t-esc="child.qty"/></span>
                                            </div>
                                        </t>
                                    </div>
                                </li>
                            </t>

                            <!-- Hiển thị Sản phẩm lẻ -->
                            <t t-foreach="pData.products" t-as="prod" t-key="prod.id">
                                <li class="list-group-item d-flex justify-content-between align-items-center"
                                    t-att-class="prod.scanned ? 'bg-success-light' : ''">
                                    <div>
                                        <i class="fas" t-att-class="prod.scanned ? 'fa-check-circle text-success' : 'fa-cube text-info'"></i>
                                        <span class="ml-2"><t t-esc="prod.name"/></span>
                                        <div class="text-muted small ml-4"><t t-esc="prod.barcode"/></div>
                                    </div>
                                    <span class="badge badge-secondary">x<t t-esc="prod.qty"/></span>
                                </li>
                            </t>
                        </ul>
                    </div>
                </t>

                <!-- Fixed Bottom Actions -->
                <div class="fixed-bottom p-3 bg-white border-top shadow-lg d-flex gap-2" style="bottom: 0; z-index: 1000;">
                    <button class="btn btn-outline-secondary flex-grow-1" t-on-click="onForceDoneClick">
                        <i class="fas fa-check-double"></i> Bỏ qua quét
                    </button>
                    <button class="btn btn-primary flex-grow-2" 
                            t-att-disabled="!state.allDone"
                            t-on-click="props.onComplete">
                        Hoàn tất &amp; Chụp ảnh <i class="fas fa-camera ml-1"></i>
                    </button>
                </div>
            </div>
        </div>
    `;

    setup() {
        this.state = useState({
            scanInput: "",
            errorMessage: "",
            successMessage: "",
            pickingDataList: [],
            expandedPkgs: [],
            allDone: false
        });

        onWillStart(() => {
            this.initData();
        });
    }

    initData() {
        // Parse props.data (là kết quả từ API get_multiple_outs)
        // Cấu trúc dự kiến: { picking: {id, name, so_name}, items: [...] }
        const rawList = this.props.data || [];
        
        const parsedList = rawList.map(item => {
            const pkgs = item.items.filter(i => i.type === 'package').map(p => ({...p, id: 'pkg_'+Math.random()}));
            const prods = item.items.filter(i => i.type === 'product').map(p => ({...p, id: 'prd_'+Math.random()}));
            
            const total = pkgs.length + prods.length;
            const done = pkgs.filter(p => p.scanned).length + prods.filter(p => p.scanned).length;

            return {
                id: item.picking.id,
                name: item.picking.name,
                so_name: item.picking.so_name,
                packages: pkgs,
                products: prods,
                progress: { total, done, isDone: total > 0 && done === total }
            };
        });

        this.state.pickingDataList = parsedList;
        this.checkAllDone();
    }

    onScanInputKeyUp(ev) {
        if (ev.key === "Enter") {
            this.onScanBtnClick();
        }
    }

    onScanBtnClick() {
        const barcode = this.state.scanInput.trim();
        if (!barcode) return;
        
        this.processBarcode(barcode);
        this.state.scanInput = "";
    }

    processBarcode(barcode) {
        this.state.errorMessage = "";
        this.state.successMessage = "";
        
        let found = false;
        let pDataId = null;

        for (let pData of this.state.pickingDataList) {
            // Search in packages
            for (let pkg of pData.packages) {
                if (!pkg.scanned && (pkg.barcode === barcode || pkg.name === barcode)) {
                    pkg.scanned = true;
                    found = true;
                    pDataId = pData.id;
                    break;
                }
            }
            if (found) break;

            // Search in products
            for (let prod of pData.products) {
                if (!prod.scanned && (prod.barcode === barcode || prod.name === barcode)) {
                    prod.scanned = true;
                    found = true;
                    pDataId = pData.id;
                    break;
                }
            }
            if (found) break;
        }

        if (found) {
            this.state.successMessage = "Đã xác nhận: " + barcode;
            this.recalcProgress();
        } else {
            this.state.errorMessage = "Mã không hợp lệ hoặc đã được quét: " + barcode;
        }
    }

    recalcProgress() {
        let allFinished = true;
        for (let pData of this.state.pickingDataList) {
            const done = pData.packages.filter(p => p.scanned).length + pData.products.filter(p => p.scanned).length;
            pData.progress.done = done;
            pData.progress.isDone = pData.progress.total > 0 && done === pData.progress.total;
            if (!pData.progress.isDone) allFinished = false;
        }
        this.state.allDone = allFinished;
    }

    checkAllDone() {
        this.recalcProgress();
    }

    togglePackageExpanded(id) {
        const idx = this.state.expandedPkgs.indexOf(id);
        if (idx > -1) this.state.expandedPkgs.splice(idx, 1);
        else this.state.expandedPkgs.push(id);
    }

    onForceDoneClick() {
        for (let pData of this.state.pickingDataList) {
            pData.packages.forEach(p => p.scanned = true);
            pData.products.forEach(p => p.scanned = true);
        }
        this.recalcProgress();
        this.state.successMessage = "Đã bỏ qua quét. Tất cả được đánh dấu hoàn tất.";
    }
}

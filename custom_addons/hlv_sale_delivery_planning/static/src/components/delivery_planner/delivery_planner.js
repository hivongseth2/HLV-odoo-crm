/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class DeliveryPlannerDashboard extends Component {
    static template = "hlv_sale_delivery_planning.Dashboard";

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.state = useState({
            saleOrders: [],
            warehouses: [],
            isLoading: true,

            // Search & Filters
            searchQuery: "",
            filterWarehouseId: "all",
            filterDeliveryStatus: "all",
            filterStockStatus: "all",
            filterDateFrom: "",
            filterDateTo: null,
            filterPODateFrom: null,
            filterPODateTo: null,
            filterPOStatus: "all",
            filterPackingStatus: "all",

            // Stats
            dashboardStats: { total: 0, ready: 0, partial: 0, out_of_stock: 0 },

            // Pagination
            currentPage: 1,
            itemsPerPage: 12,
            totalCount: 0,

            // Drawer
            isDrawerOpen: false,
            selectedOrder: null,

            // Package Modal
            isPackageModalOpen: false,
            selectedPackage: null,
        });

        onWillStart(async () => {
            await this.fetchData();
        });
    }

    async fetchData() {
        this.state.isLoading = true;
        try {
            const result = await this.orm.call(
                "sale.order",
                "get_delivery_dashboard_data",
                [],
                {
                    search_query: this.state.searchQuery.trim(),
                    filter_warehouse_id: this.state.filterWarehouseId,
                    filter_delivery_status: this.state.filterDeliveryStatus,
                    filter_stock_status: this.state.filterStockStatus,
                    filter_date_from: this.state.filterDateFrom,
                    filter_date_to: this.state.filterDateTo,
                    filter_po_date_from: this.state.filterPODateFrom,
                    filter_po_date_to: this.state.filterPODateTo,
                    filter_po_status: this.state.filterPOStatus,
                    filter_packing_status: this.state.filterPackingStatus,
                    limit: this.state.itemsPerPage,
                    offset: (this.state.currentPage - 1) * this.state.itemsPerPage,
                }
            );

            this.state.dashboardStats = result.dashboard_stats || { total: 0, ready: 0, partial: 0, out_of_stock: 0 };
            const fetchedOrders = result.orders || [];
            this.state.saleOrders = fetchedOrders.map(so => {
                so.flows = so.flows || [];
                so.pickings = so.pickings || [];
                so.lines = so.lines || [];
                so.pos = so.pos || [];

                // Map of name -> node for finding parent
                const nodeByName = {};
                so.flows.forEach(flow => {
                    (flow.nodes || []).forEach(node => {
                        nodeByName[node.name] = node;
                    });
                });

                // Assign persistent visual link info
                const colorClasses = ['info', 'warning', 'danger', 'primary', 'success', 'dark'];
                let colorIdx = 0;

                so.flows.forEach(flow => {
                    (flow.nodes || []).forEach(node => {
                        const parentName = node.return_of || node.backorder_of;
                        if (parentName && nodeByName[parentName]) {
                            const parentNode = nodeByName[parentName];
                            node.parent_seq = parentNode.global_seq;

                            if (!parentNode.link_color) {
                                parentNode.link_color = colorClasses[colorIdx % colorClasses.length];
                                colorIdx++;
                            }
                            node.link_color = parentNode.link_color;
                        }
                    });
                });

                return so;
            });
            this.state.totalCount = result.total_count || 0;
            if (this.state.warehouses.length === 0) {
                this.state.warehouses = result.warehouses || [];
            }
        } catch (error) {
            console.error("Lỗi khi tải dữ liệu bảng điều phối:", error);
        } finally {
            this.state.isLoading = false;
        }
    }

    // --- Computed Filters & Pagination ---
    get totalPages() {
        return Math.ceil(this.state.totalCount / this.state.itemsPerPage) || 1;
    }

    get paginatedOrders() {
        return this.state.saleOrders;
    }

    // --- Actions ---
    async nextPage() {
        if (this.state.currentPage < this.totalPages) {
            this.state.currentPage++;
            await this.fetchData();
        }
    }

    async prevPage() {
        if (this.state.currentPage > 1) {
            this.state.currentPage--;
            await this.fetchData();
        }
    }

    async onFilterChange() {
        this.state.currentPage = 1;
        await this.fetchData();
    }

    async setStockFilter(status) {
        if (this.state.filterStockStatus === status) {
            // Nếu click lại chính Tab đó thì bỏ lọc (Về Tất Cả)
            this.state.filterStockStatus = 'all';
        } else {
            this.state.filterStockStatus = status;
        }
        this.state.currentPage = 1;
        await this.fetchData();
    }

    async setPackingFilter(status) {
        if (this.state.filterPackingStatus === status) {
            this.state.filterPackingStatus = 'all';
        } else {
            this.state.filterPackingStatus = status;
        }
        this.state.currentPage = 1;
        await this.fetchData();
    }

    async onSearchKeyup(ev) {
        if (ev.key === "Enter") {
            this.state.currentPage = 1;
            await this.fetchData();
        }
    }

    openSaleOrder(soId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "sale.order",
            res_id: soId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openPurchaseOrder(poId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "purchase.order",
            res_id: poId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openPicking(pickingId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "stock.picking",
            res_id: pickingId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openVideo(url) {
        window.open(url, '_blank');
    }

    // --- PO Status Formatting (Receipt Based) ---
    getPOStatusClass(receiptStatus) {
        switch (receiptStatus) {
            case "pending":
                return "bg-secondary"; // Chưa nhận
            case "partial":
                return "bg-warning text-dark"; // Nhận 1 phần
            case "full":
                return "bg-success"; // Nhận đủ
            default:
                return "bg-light text-muted border";
        }
    }

    translatePOStatus(receiptStatus) {
        const trans = {
            partial: "Nhận 1 phần",
            pending: "Chưa nhận",
            full: "Đã nhận đủ",
            unknown: "Không rõ"
        };
        return trans[receiptStatus] || "Mới Tạo / Hủy";
    }

    // --- Translations ---
    translateDeliveryStatus(status) {
        const trans = {
            'unknown': 'Chưa cập nhật',
            'pending': 'CHƯA GIAO',
            'unshipped': 'CHƯA GIAO',
            'partial': 'Giao 1 phần',
            'pending_partial': 'Chưa & Giao 1 phần',
            'full': 'Đã giao đủ'
        };
        return trans[status] || (status ? status.toUpperCase() : '');
    }

    translatePickingState(state) {
        const trans = {
            'draft': 'Nháp',
            'waiting': 'Chờ phiếu khác',
            'confirmed': 'Chờ hàng',
            'assigned': 'Sẵn sàng',
            'done': 'Đã giao khách',
            'cancel': 'Đã hủy'
        };
        return trans[state] || state;
    }

    getPickingStateBadgeClass(state) {
        const mapping = {
            'draft': 'bg-light text-dark',
            'waiting': 'bg-warning text-dark',
            'confirmed': 'bg-info text-white',
            'assigned': 'bg-primary text-white',
            'done': 'bg-success text-white',
            'cancel': 'bg-danger text-white'
        };
        return mapping[state] || 'bg-secondary text-white';
    }

    translateStockStatus(status) {
        const trans = {
            'out_of_stock': 'Không có hàng',
            'partial_ready': 'Có hàng 1 phần',
            'ready': 'Đủ hàng xuất'
        };
        return trans[status] || (status ? status.toUpperCase() : '');
    }

    translatePackingStatus(status) {
        const trans = {
            'waiting_stock': 'Chờ Hàng Đóng',
            'unpacked': 'Chưa Đóng Gói (Có Hàng)',
            'partial_packed': 'Đã Đóng 1 Phần',
            'fully_packed': 'Đã Đóng Đủ Kiện'
        };
        return trans[status] || (status ? status.toUpperCase() : '');
    }

    translateSOStatus(status) {
        const trans = {
            'draft': 'Báo giá',
            'sent': 'Đã gửi',
            'sale': 'Đơn hàng',
            'done': 'Khóa',
            'cancel': 'Đã hủy',
        };
        return trans[status] || (status ? status.toUpperCase() : '');
    }

    translatePickingStatus(state) {
        const trans = {
            'draft': 'Nháp',
            'waiting': 'Chờ QĐ',
            'confirmed': 'Chờ hàng',
            'assigned': 'Sẵn sàng',
            'done': 'Hoàn thành',
            'cancel': 'Hủy'
        };
        return trans[state] || (state ? state.toUpperCase() : '');
    }

    getPOStatusBadgeClass(state, receiptStatus) {
        if (state === 'cancel') return 'text-bg-secondary';
        if (receiptStatus === 'full') return 'text-bg-success';
        if (receiptStatus === 'partial') return 'text-bg-info';
        if (state === 'purchase' || state === 'done') return 'text-bg-primary';
        return 'text-bg-light border text-dark';
    }

    getDeliveryStatusBadgeClass(status) {
        if (status === 'full') return 'text-bg-success';
        if (status === 'partial') return 'text-bg-warning';
        if (status === 'pending') return 'text-bg-secondary';
        return 'text-bg-light border text-dark';
    }

    getStockStatusBadgeClass(status) {
        if (status === 'ready') return 'text-bg-primary';
        if (status === 'partial_ready') return 'text-bg-warning';
        if (status === 'out_of_stock') return 'text-bg-danger';
        return 'text-bg-light border text-dark';
    }

    getPackingStatusBadgeClass(status) {
        if (status === 'fully_packed') return 'text-bg-success';
        if (status === 'partial_packed') return 'text-bg-info';
        if (status === 'unpacked') return 'text-bg-warning';
        if (status === 'waiting_stock') return 'text-bg-danger mb-opacity-75';
        return 'text-bg-light border text-dark';
    }

    getPickingStatusBadgeClass(state) {
        if (state === 'done') return 'text-bg-success';
        if (state === 'assigned') return 'text-bg-primary';
        if (state === 'cancel') return 'text-bg-secondary opacity-50';
        return 'text-bg-warning';
    }

    getDatesComparisonClass(soDate, poDate) {
        if (!soDate || !poDate) return '';
        const so = new Date(soDate);
        const po = new Date(poDate);
        if (po > so) return 'text-danger fw-bold';
        return 'text-success';
    }

    formatCurrency(value) {
        return new Intl.NumberFormat('vi-VN', { style: 'currency', currency: 'VND' }).format(value);
    }

    formatQty(value) {
        return parseFloat(Number(value).toFixed(2));
    }

    getSOCardColorClass(so) {
        if (so.real_delivery_status === 'full') return 'border-success border-2 shadow-sm';
        if (so.stock_status === 'ready') return 'border-primary border-2 shadow-sm';
        if (so.stock_status === 'partial_ready') return 'border-warning border-2 shadow-sm';
        return 'border-danger border-2 shadow-sm';
    }

    // --- Hover Interactions cho Liên kết Return/Backorder ---
    onPickingHover(pickingName) {
        const safeName = pickingName.split('/').join('-');

        // Highlight chính nó và các node con (Các phiếu return từ nó)
        const childNodes = document.querySelectorAll(`.linked-return-${safeName}`);
        childNodes.forEach(node => {
            node.classList.add('shadow', 'border-warning', 'bg-warning', 'bg-opacity-10');
            node.style.transform = 'scale(1.05)';
        });

        // Nếu nó bè Phiếu Con (return_of / backorder_of) -> Highlight Thẻ Cha 
        const pickingElement = document.querySelector(`[data-picking-name="${safeName}"]`);
        if (pickingElement) {
            // Check nếu chính thẻ này là thẻ con (có return_of)
            const parentClassMatches = Array.from(pickingElement.classList).find(cls => cls.startsWith('linked-return-'));
            if (parentClassMatches) {
                const parentName = parentClassMatches.replace('linked-return-', '');
                const parentNode = document.querySelector(`.original-picking-${parentName}`);
                if (parentNode) {
                    parentNode.classList.add('shadow', 'border-warning', 'bg-warning', 'bg-opacity-10');
                    parentNode.style.transform = 'scale(1.05)';
                }
            }
        }
    }

    onPickingLeave() {
        // Gỡ bỏ toàn bộ hiệu ứng Highlight
        const allHighlighted = document.querySelectorAll('.picking-node');
        allHighlighted.forEach(node => {
            node.classList.remove('shadow', 'border-warning', 'bg-warning', 'bg-opacity-10');
            node.style.transform = 'scale(1)';
        });
    }

    // --- Drawer Actions ---
    openOverviewDrawer(so) {
        this.state.selectedOrder = so;
        this.state.isDrawerOpen = true;
    }

    closeOverviewDrawer() {
        this.state.isDrawerOpen = false;
    }

    // --- Package Modal Actions ---
    openPackageDetails(pack) {
        this.state.selectedPackage = pack;
        this.state.isPackageModalOpen = true;
    }

    closePackageDetails() {
        this.state.isPackageModalOpen = false;
        this.state.selectedPackage = null;
    }

    async printPackageLabel(pack) {
        if (!pack || !pack.picking_id) return;

        await this.actionService.doAction("hlv_pack_sequence.action_report_package_labels", {
            additionalContext: {
                active_ids: [pack.picking_id],
                active_model: 'stock.picking'
            },
        });
    }

    formatPackageLocation(locationName) {
        if (!locationName) {
            return "khu vực đóng gói";
        }
        if (locationName.includes("Partners/Customers")) {
            return "đã giao khách";
        }
        if (locationName.includes("/OUT")) {
            return "chờ xuất kho";
        }
        return locationName;
    }

    // --- Filter Helpers ---
    get hasActiveFilters() {
        return this.state.searchQuery ||
            this.state.filterWarehouseId !== "all" ||
            this.state.filterDeliveryStatus !== "all" ||
            this.state.filterStockStatus !== "all" ||
            this.state.filterDateFrom ||
            this.state.filterDateTo ||
            this.state.filterPODateFrom ||
            this.state.filterPODateTo ||
            this.state.filterPOStatus !== "all" ||
            this.state.filterPackingStatus !== "all";
    }

    resetFilters() {
        this.state.searchQuery = "";
        this.state.filterWarehouseId = "all";
        this.state.filterDeliveryStatus = "all";
        this.state.filterStockStatus = "all";
        this.state.filterDateFrom = "";
        this.state.filterDateTo = null;
        this.state.filterPODateFrom = null;
        this.state.filterPODateTo = null;
        this.state.filterPOStatus = "all";
        this.state.filterPackingStatus = "all";
        this.state.currentPage = 1;
        this.fetchData();
    }
}

registry.category("actions").add("hlv_sale_delivery_planning.dashboard", DeliveryPlannerDashboard);

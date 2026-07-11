/** @odoo-module **/
// Purpose: Main OWL dashboard component: owns state/lifecycle and composes delivery planner mixins.

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart, onMounted, onWillDestroy, markup, useEffect } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import {
    translateDeliveryStatus, translatePickingState, translatePickingStatus,
    translateStockStatus, translatePackingStatus, translateSOStatus, translatePOStatus,
    getPickingStateBadgeClass, getPickingStatusBadgeClass, getDeliveryStatusBadgeClass,
    getStockStatusBadgeClass, getPackingStatusBadgeClass, getPOStatusBadgeClass,
    getSOCardColorClass, formatCurrency, formatQty, getDatesComparisonClass,
} from "./delivery_planner_utils";
import { DeliveryPlannerRealtimeMixin } from "./delivery_planner_realtime_mixin";
import { DeliveryPlannerDataMixin } from "./delivery_planner_data_mixin";
import { DeliveryPlannerCacheMixin } from "./delivery_planner_cache_mixin";
import { DeliveryPlannerPreferencesMixin } from "./delivery_planner_preferences_mixin";
import { DeliveryPlannerTableMixin } from "./delivery_planner_table_mixin";
import { DeliveryPlannerKanbanSelectionMixin } from "./delivery_planner_kanban_selection_mixin";
import { DeliveryPlannerPrintingMixin } from "./delivery_planner_printing_mixin";
import { DeliveryPlannerDisplayMixin } from "./delivery_planner_display_mixin";
import { DeliveryPlannerDisplayHelpersMixin } from "./delivery_planner_display_helpers_mixin";
import { DeliveryPlannerDrawerMessagesMixin } from "./delivery_planner_drawer_messages_mixin";
import { DeliveryPlannerTransferMixin } from "./delivery_planner_transfer_mixin";
import { DeliveryPlannerRelocationMixin } from "./delivery_planner_relocation_mixin";

export class DeliveryPlannerDashboard extends Component {
    static template = "hlv_sale_delivery_planning.Dashboard";

    setup() {
        this._dataChangedDebounce = null;
        this._pendingChangedSoIds = null;
        this._pendingFallbackFull = false;
        this._CACHE_DB = 'hlv_dp_cache';
        this._CACHE_STORE = 'dashboard';
        this._CACHE_TTL = 5 * 60 * 1000; // 5 minutes
        this._autoLoadSeq = 0;
        this.orm = useService("orm");
        this.actionService = useService("action");
        const today = new Date().toISOString().slice(0, 10);
        this.state = useState({
            // menu print từng phiếu lấy theo axenor rule
            printMenuReports: [],
            // menu in nhiều hard theo tên lấy hàng
            selectedPrintMenuReports: [],
            packerUsers: [],
            packerUsersLoading: false,
            isPackerAssignModalOpen: false,
            selectedPackerUserId: null,
            pendingPrintReportId: null,
            pendingPrintReportType: 'qweb-pdf',
            pendingSinglePrintPickingId: null,
            changePackerPickingId: null,

            saleOrders: [],
            warehouses: [],
            tags: [],
            isLoading: true,
            isRefreshing: false,  // Refresh in progress with data already on screen (thin top bar instead of full overlay)

            // Search & Filters
            searchQuery: "",
            filterWarehouseId: "all",
            filterDeliveryStatus: "pending_partial",
            filterStockStatus: "all",
            filterDateFrom: "",
            filterDateTo: null,
            filterDoneDateFrom: "",
            filterDoneDateTo: "",
            filterPODateFrom: null,
            filterPODateTo: null,
            filterPOStatus: "all",
            filterPackingStatus: "all",
            filterSalerCode: "",
            filterHtgh: "",
            filterDeliveryType: "all",
            filterTagIds: [],
            filterNeedTransfer: false,
            filterNewOrders: false,
            filterPrintStatus: 'all',         // 'all' | 'has_unprinted' | 'all_printed'
            filterShipperReceived: 'all',     // 'all' | 'received' | 'not_received'
            showCompleted: false,

            // HTGH presets (lưu localStorage)
            htghPresets: JSON.parse(localStorage.getItem('hlv_htgh_presets') || 'null') || [
                { label: 'Hãng VC', value: 'ghn,cpn,chuy\u1ec3n ph\u00e1t nhanh,giao h\u00e0ng nhanh,j&t' },
                { label: 'Tr\u1eeb h\u00e3ng VC', value: '!ghn,!cpn,!chuy\u1ec3n ph\u00e1t nhanh,!giao h\u00e0ng nhanh,!j&t' },
            ],

            // Stats
            // KPI dashboard stats (loaded ASYNCHRONOUSLY via a separate endpoint
            // — main fetchData does NOT touch this so the table/kanban can render
            // without waiting for stats compute.)
            dashboardStats: { total: 0, ready: 0, partial: 0, out_of_stock: 0 },
            statsLoading: false,
            isLoadingMore: false,
            isPackingProgressDrawerOpen: false,
            packingProgressLoading: false,
            packingProgress: { summary: {}, groups: [] },
            packingProgressDateFrom: today,
            packingProgressDateTo: today,
            packingProgressState: 'all',

            // Pagination
            currentPage: 1,
            itemsPerPage: (function () {
                try {
                    var v = parseInt(localStorage.getItem('hlv_dp_items_per_page'), 10);
                    return [12, 25, 50, 100, 200].indexOf(v) >= 0 ? v : 12;
                } catch (e) { return 12; }
            })(),
            totalCount: 0,

            // Drawer
            isDrawerOpen: false,
            selectedOrder: null,

            // Message Drawer (Left)
            isMessageDrawerOpen: false,
            globalUnreadOrders: [],
            globalUnreadOrdersLoading: false,

            // Package Modal
            isPackageModalOpen: false,
            selectedPackage: null,

            // UI State
            collapsedSections: new Set(['packages', 'flows', 'pending_products']), // Default collapsed

            // View Mode
            viewMode: 'kanban',               // 'kanban' | 'list' (Card) | 'table' (Bảng)
            kanbanGroupBy: 'packing_status', // 'packing_status' | 'delivery_status' | 'stock_status'
            draggedSoId: null,
            dragOverColumn: null,
            kanbanColumnOrder: {},           // { colValue: [soId, ...] } — thứ tự DnD client-side
            kanbanColPageSize: {},           // { colValue: N } — số card hiển thị mỗi cột
            kanbanBatchSize: 100,            // số đơn tải backend cho toàn kanban

            // Table (Bảng) View State
            tableSortField: 'commitment_date', // 'name'|'misa_order_date'|'partner'|'warehouse'|'delivery_status'|'stock_status'|'packing_status'|'commitment_date'|'amount_total'
            tableSortDir: 'desc',              // 'asc' | 'desc'
            expandedTableRows: new Set(),      // Set of soId currently expanded

            // Selection for printing
            selectedSOIds: new Set(),        // Set of selected sale order IDs for printing

            // Archive (cất đơn) — backend persisted (per user) via
            // hlv.delivery.planner.user.pref. Loaded in onWillStart.
            //   - archivedSOIds: đơn đã cất vì không còn dùng
            //   - consolidateSOIds: đơn chờ gom (đã đóng gói chờ KH xác
            //     nhận / chờ đơn khác để đi 1 chuyến).
            // Cả 2 đều bị loại khỏi kế hoạch giao hôm nay.
            archivedSOIds: new Set(),
            consolidateSOIds: new Set(),
            // 'none' = bình thường (loại cả 2),
            // 'archived' = chỉ xem đơn đã cất,
            // 'consolidate' = chỉ xem đơn chờ gom
            archivedView: 'none',
            // Backwards compat — một số chỗ cũ còn đọc state này
            showArchivedOnly: false,
            hasDefaultFilters: false,

            // Returned/Stopped group paging
            returnedColPageSize: 15,

            // Transfer Modal
            isTransferModalOpen: false,
            transferModalLoading: false,
            transferModalData: null,         // { warehouses, all_partners }
            transferSelections: {},          // { [wh_id]: { selected, partner_id, products: {[prod_id]: {include, qty}} } }
            isCreatingTransfer: false,

            // Message export modal
            isMessageExportModalOpen: false,
            messageExportDateFrom: today,
            messageExportDateTo: today,

            // Relocation Modal (Chuyển vị trí)
            isRelocationModalOpen: false,
            relocationModalLoading: false,
            relocationModalData: null,       // { orders, dest_locations, default_dest_location_id }
            relocationDestLocationId: null,
            relocationSaveDefault: false,
            relocationOrderSelections: {},   // { [so_id]: { selected, products: {[prod_id]: { include, qty }} } }
            isCreatingRelocation: false,

            // Picking print menu
            pickingReports: [],       // [{id, name, report_type}] — báo cáo có thể in cho stock.picking
            printMenuPickingId: null, // picking.id đang hiển thị menu in
            printMenuPos: null,       // { top, right } — vị trí fixed của dropdown
            selectedPrintMenuPos: null, // vị trí dropdown in cho các SO đã chọn

            // Inline editing: Ghi Chú Odoo
            inlineEditSOId: null,     // soId đang edit ghi chu
            inlineEditGhiChu: '',     // giá trị đang nhập

            // Inline editing: Tag picker
            tagPickerSOId: null,      // soId đang mở tag picker
            tagPickerPos: null,       // { top, right } — vị trí fixed dropdown

            // Drawer messages
            drawerMessages: [],
            drawerMessagesLoading: false,
            drawerMessageText: '',
            drawerMessageFiles: [],
            drawerMessageSending: false,
            drawerMentionAliases: [],
            drawerMentionSuggestions: [],
            drawerMentionActiveIndex: 0,
            busListening: false,
            busServiceAvailable: false,
            desktopNotificationPermission: (typeof window !== 'undefined' && 'Notification' in window) ? Notification.permission : 'unsupported',
        });

        this.notification = useService("notification");
        try {
            this.busService = useService("bus_service");
            this.state.busServiceAvailable = true;
        } catch (e) {
            console.warn("bus_service not available");
        }

        // click ra ngoài thì dóng menu
        useEffect(() => {
            const handler = () => {
                if (this.state.selectedPrintMenuPos) {
                    this.state.selectedPrintMenuPos = null;
                }
            };
            document.addEventListener('click', handler);
            return () => document.removeEventListener('click', handler);
        }, () => []);

        onWillStart(async () => {
            if (this.busService) {
                this.busService.addChannel("delivery_planner_channel");
                // Odoo 18: use subscribe(type, callback) — addEventListener("notification") is internal-only
                this._onBusDataChanged = (payload) => this._onDataChanged(payload);
                this._onBusNewPortalMessage = (payload) => this.onNewPortalMessage(payload);
                this._onBusPrefChanged = (payload) => this._onPreferenceChanged(payload);
                this.busService.subscribe("delivery_planner_data_changed", this._onBusDataChanged);
                this.busService.subscribe("new_portal_message", this._onBusNewPortalMessage);
                this.busService.subscribe("delivery_planner_pref_changed", this._onBusPrefChanged);
                this.state.busListening = true;
            }

            // Load per-user preferences (archived SOs + default filters) BEFORE
            // the first fetch so the dashboard opens with the user's saved state.
            await this._loadUserPreferences();

            // Try to restore from IndexedDB cache for instant display
            const cached = await this._loadFromCache();
            if (cached) {
                this._applyResult(cached);
                this.state.isLoading = false;
                this._isCacheRestored = true;
            }

            // Only load lightweight reports here — heavy fetchData moves to onMounted
            const reports = await this.orm.searchRead(
                'ir.actions.report',
                [['model', '=', 'stock.picking'], ['binding_model_id', '!=', false]],
                ['id', 'name', 'report_type', 'report_name'],
                { order: 'name' }
            );
            this.state.pickingReports = reports;
        });

        // fetchData runs AFTER mount so cached data shows instantly
        onMounted(async () => {
            await this.fetchData();
            this.loadPackingProgress();
            this._isCacheRestored = false;
        });

        this.pollUnreadMessages(true); // Initial fetch
        // Polling fallback cho notification (chạy mỗi 15s) vì bus trên server cấu hình có thể không ổn định
        this.messagePollingInterval = setInterval(() => {
            this.pollUnreadMessages(false);
        }, 15000);

        onWillDestroy(() => {
            if (this.busService) {
                if (this._onBusDataChanged) {
                    this.busService.unsubscribe("delivery_planner_data_changed", this._onBusDataChanged);
                }
                if (this._onBusNewPortalMessage) {
                    this.busService.unsubscribe("new_portal_message", this._onBusNewPortalMessage);
                }
                if (this._onBusPrefChanged) {
                    this.busService.unsubscribe("delivery_planner_pref_changed", this._onBusPrefChanged);
                }
                this.busService.deleteChannel("delivery_planner_channel");
                this.state.busListening = false;
            }
            if (this.messagePollingInterval) {
                clearInterval(this.messagePollingInterval);
            }
            if (this._dataChangedDebounce) {
                clearTimeout(this._dataChangedDebounce);
            }
        });
    }


}

function applyPlannerMixin(mixinClass) {
    const descriptors = Object.getOwnPropertyDescriptors(mixinClass.prototype);
    delete descriptors.constructor;
    Object.defineProperties(DeliveryPlannerDashboard.prototype, descriptors);
}

[
    DeliveryPlannerRealtimeMixin,
    DeliveryPlannerDataMixin,
    DeliveryPlannerCacheMixin,
    DeliveryPlannerPreferencesMixin,
    DeliveryPlannerTableMixin,
    DeliveryPlannerKanbanSelectionMixin,
    DeliveryPlannerPrintingMixin,
    DeliveryPlannerDisplayMixin,
    DeliveryPlannerDisplayHelpersMixin,
    DeliveryPlannerDrawerMessagesMixin,
    DeliveryPlannerTransferMixin,
    DeliveryPlannerRelocationMixin,
].forEach(applyPlannerMixin);

registry.category("actions").add("hlv_sale_delivery_planning.dashboard", DeliveryPlannerDashboard);

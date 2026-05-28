/** @odoo-module **/

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

export class DeliveryPlannerDashboard extends Component {
    static template = "hlv_sale_delivery_planning.Dashboard";

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
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
        });

        this.notification = useService("notification");
        try {
            this.busService = useService("bus_service");
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
            }
            if (this.messagePollingInterval) {
                clearInterval(this.messagePollingInterval);
            }
            if (this._dataChangedDebounce) {
                clearTimeout(this._dataChangedDebounce);
            }
        });
    }

    async pollUnreadMessages(isInitial = false) {
        try {
            const notifications = await this.orm.call(
                'hlv.sale.plan.message',
                'list_for_current_user',
                [],
                { limit: 100 }
            );

            const prevByOrderId = new Map(
                this.state.globalUnreadOrders.map((o) => [o.sale_order_id ? o.sale_order_id[0] : o.id, o])
            );

            const merged = notifications.map((n) => ({
                id: n.id,
                sale_order_id: n.sale_order_id,
                name: n.sale_order_id ? n.sale_order_id[1] : '',
                last_message_author: n.last_message_author || '',
                _preview: n.last_message_preview || '',
                _isRead: !!n.is_read,
                last_message_date: n.last_message_date,
                _time_str: this._formatMsgDate(n.last_message_date),
            }));

            // Giữ lại trạng thái read/unread đã cập nhật local cho đến khi DB trả về trạng thái mới.
            for (const item of merged) {
                const prev = prevByOrderId.get(item.sale_order_id ? item.sale_order_id[0] : item.id);
                if (prev && prev._isRead && !item._isRead) {
                    item._isRead = false;
                }
            }

            this.state.globalUnreadOrders = merged;

            const shouldNotifyFromPolling = !isInitial;
            if (shouldNotifyFromPolling) {
                for (const notification of notifications.filter((n) => !n.is_read)) {
                    const orderId = notification.sale_order_id ? notification.sale_order_id[0] : false;
                    if (!orderId) {
                        continue;
                    }
                    const prev = prevByOrderId.get(orderId);
                    if (!prev || prev._isRead) {
                        const so = this.state.saleOrders.find(o => o.id === orderId);
                        if (so) so.has_unread_message = true;

                        this.notification.add(
                            `Đơn hàng ${notification.sale_order_id ? notification.sale_order_id[1] : ''} vừa có tin nhắn mới.`,
                            {
                                type: "info",
                                title: `Tin nhắn chưa đọc`,
                                buttons: [
                                    {
                                        name: "Xem thông báo",
                                        onClick: () => this.openDrawerFromMessageList(orderId),
                                        primary: true,
                                    }
                                ]
                            }
                        );
                    }
                }
            }
        } catch (e) {
            console.warn("Polling unread failed", e);
        }
    }

    /**
     * Format Odoo Datetime string (UTC) sang giờ VN (UTC+7).
     * Odoo trả về dạng "YYYY-MM-DD HH:MM:SS" hoặc false.
     */
    _formatMsgDate(dateStr) {
        if (!dateStr) return '';
        try {
            // Odoo Datetime field trả về dạng "2026-04-22 07:30:00" — UTC, không có 'Z'
            // Thêm 'Z' để browser parse đúng UTC rồi cộng +7h.
            const utc = new Date(dateStr.replace(' ', 'T') + 'Z');
            if (isNaN(utc.getTime())) return '';
            const vn = new Date(utc.getTime() + 7 * 60 * 60 * 1000);
            const pad = n => String(n).padStart(2, '0');
            return `${pad(vn.getUTCDate())}/${pad(vn.getUTCMonth() + 1)} ${pad(vn.getUTCHours())}:${pad(vn.getUTCMinutes())}`;
        } catch (e) {
            return '';
        }
    }

    async markOrderAsRead(soId) {
        try {
            await this.orm.call('hlv.sale.plan.message', 'mark_read_for_sale_order', [soId]);
        } catch (e) {
            console.warn('markOrderAsRead failed', e);
        }
    }

    _extractPreviewText(htmlText) {
        const plain = String(htmlText || '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
        if (!plain) {
            return '';
        }
        return plain.length > 120 ? `${plain.slice(0, 120)}...` : plain;
    }

    get unreadMessageCount() {
        return this.state.globalUnreadOrders.filter((o) => !o._isRead).length;
    }

    async openDrawerFromMessageList(soId) {
        this.state.globalUnreadOrders = this.state.globalUnreadOrders.map((o) =>
            (o.sale_order_id && o.sale_order_id[0] === soId) ? { ...o, _isRead: true } : o
        );
        this.markOrderAsRead(soId);

        const soLocal = this.state.saleOrders.find(o => o.id === soId);
        if (soLocal) {
            soLocal.has_unread_message = false;
        }

        // Mở drawer
        let so = this.state.saleOrders.find(o => o.id === soId);
        if (so) {
            this.openOverviewDrawer(so);
        } else {
            // Đơn chưa được tải trên màn hình Kanban hiện tại, query dữ liệu single SO
            this.state.isLoading = true;
            try {
                const result = await this.orm.call('hlv.delivery.planner.service', 'get_dashboard_data', [], {
                    domain: [['id', '=', soId]],
                    limit: 1,
                    offset: 0
                });
                const fetched = result && result.orders ? result.orders.find((o) => o.id === soId) : null;
                if (fetched) {
                    this.openOverviewDrawer(fetched);
                } else {
                    this.openSaleOrder(soId);
                }
            } catch (e) {
                this.openSaleOrder(soId);
            } finally {
                this.state.isLoading = false;
            }
        }
        this.state.isMessageDrawerOpen = false; // Đóng cửa sổ bên trái
    }

    async onNewPortalMessage(payload) {
        // payload: {so_id, so_name, author_name, body}

        // Cập nhật danh sách drawer realtime: có tin mới thì đưa lên đầu và bật trạng thái chưa đọc.
        const existing = this.state.globalUnreadOrders.find(o => (o.sale_order_id && o.sale_order_id[0] === payload.so_id) || o.id === payload.so_id);
        const headItem = {
            id: payload.so_id,
            sale_order_id: [payload.so_id, payload.so_name],
            name: payload.so_name,
            last_message_author: payload.author_name || 'Khách hàng',
            _isRead: false,
            _preview: this._extractPreviewText(payload.body || ''),
        };
        this.state.globalUnreadOrders = [
            headItem,
            ...this.state.globalUnreadOrders.filter(o => !((o.sale_order_id && o.sale_order_id[0] === payload.so_id) || o.id === payload.so_id)),
        ].slice(0, 100);

        // Show toaster notification
        const rawBody = (payload.body || '').replace(/<[^>]+>/g, '').substring(0, 80);
        const so = this.state.saleOrders.find(o => o.id === payload.so_id);
        if (so) {
            so.has_unread_message = true;
        }
        if (!existing || existing._isRead) {
            this.notification.add(
                `Đơn hàng ${payload.so_name}: ${rawBody}...`,
                {
                    type: "info",
                    title: `Khách hàng ${payload.author_name} vừa nhắn tin`,
                    buttons: [
                        {
                            name: "Xem đơn hàng",
                            onClick: () => this.openDrawerFromMessageList(payload.so_id),
                            primary: true,
                        }
                    ]
                }
            );
        }
    }

    // --- Real-time data refresh via bus ---
    _dataChangedDebounce = null;
    _pendingChangedSoIds = null;
    _pendingFallbackFull = false;

    _onDataChanged(payload) {
        // Only show toast on the FIRST event in a burst (not every bus message)
        if (!this._dataChangedDebounce) {
            this.notification.add(
                "Đang cập nhật dữ liệu...",
                { type: "warning", title: "Thay đổi phát hiện", sticky: false }
            );
        }
        // Accumulate affected SO ids across the burst (ids come from sale_order/picking/move triggers).
        // If a payload has no ids, mark fallback so we do a full refresh.
        if (!this._pendingChangedSoIds) {
            this._pendingChangedSoIds = new Set();
            this._pendingFallbackFull = false;
        }
        const ids = payload && payload.sale_order_ids;
        if (Array.isArray(ids) && ids.length) {
            for (const i of ids) this._pendingChangedSoIds.add(i);
        } else {
            this._pendingFallbackFull = true;
        }
        // Debounce: multiple writes can fire in quick succession (e.g. batch picking validation).
        if (this._dataChangedDebounce) {
            clearTimeout(this._dataChangedDebounce);
        }
        this._dataChangedDebounce = setTimeout(async () => {
            this._dataChangedDebounce = null;
            const ids = Array.from(this._pendingChangedSoIds || []);
            const fallback = this._pendingFallbackFull;
            this._pendingChangedSoIds = null;
            this._pendingFallbackFull = false;
            // Only orders currently on screen need a subset refresh; others can be ignored
            // (they aren't displayed; the next full refresh / cache load will pick them up).
            const visibleIds = new Set(this.state.saleOrders.map(o => o.id));
            const subsetIds = ids.filter(i => visibleIds.has(i));
            const offscreenIds = ids.filter(i => !visibleIds.has(i));
            if (!fallback && ids.length > 0 && subsetIds.length + offscreenIds.length === ids.length) {
                // Auto-load: refresh visible + auto-pull offscreen vào danh sách (không hỏi user)
                await this._refreshSubset(ids);
                if (offscreenIds.length) {
                    // Sau khi backend lọc theo filter hiện tại, chỉ những offscreen
                    // ids thật sự được thêm vào state mới đáng thông báo (tránh
                    // báo nhầm đơn kho khác / không khớp filter).
                    const visibleAfter = new Set(this.state.saleOrders.map(o => o.id));
                    const addedOffscreen = offscreenIds.filter(i => visibleAfter.has(i));
                    if (addedOffscreen.length) {
                        await this._notifyOffscreenAutoLoaded(addedOffscreen);
                    }
                }
            } else {
                // Fallback: full silent refresh (filters may have caused new matches)
                await this._silentRefresh();
            }
            this.notification.add(
                "Dữ liệu đã được cập nhật tự động",
                { type: "info", title: "Cập nhật xong" }
            );
            if (this.state.isPackingProgressDrawerOpen) {
                this.loadPackingProgress();
            }
        }, 800);
    }

    _onPreferenceChanged(payload) {
        if (!payload) return;
        const archived = Array.isArray(payload.archived_so_ids) ? payload.archived_so_ids : [];
        const consolidate = Array.isArray(payload.consolidate_so_ids) ? payload.consolidate_so_ids : [];
        this.state.archivedSOIds = new Set(archived);
        this.state.consolidateSOIds = new Set(consolidate);
    }

    /**
     * Off-screen auto-loaded notification — đã tự động merge vào state, chỉ thông báo cho user biết.
     * Toast nhẹ (info, không sticky) kèm tên SO để user thấy rõ đơn nào vừa xuất hiện.
     */
    async _notifyOffscreenAutoLoaded(soIds) {
        if (!soIds || !soIds.length) return;
        let names = [];
        try {
            const recs = await this.orm.read("sale.order", soIds, ["name"]);
            names = (recs || []).map(r => r.name).filter(Boolean);
        } catch (e) {
            console.warn("read SO names failed:", e);
        }
        const previewNames = names.slice(0, 3).join(", ");
        const moreCount = names.length > 3 ? ` (+${names.length - 3})` : "";
        const label = names.length ? `${previewNames}${moreCount}` : `${soIds.length} đơn`;
        this.notification.add(
            `Đã tự động tải ${label} vào danh sách.`,
            { type: "info", title: "Cập nhật ngoài danh sách" }
        );
    }

    /**
     * Partial refresh — re-fetches only the given SO ids and merges them in.
     * Works for both kanban and list views (both share state.saleOrders).
     */
    async _refreshSubset(soIds) {
        try {
            // Truyền filter_kwargs để backend loại các SO không khớp filter
            // hiện tại (vd: bus đẩy đơn kho A nhưng dashboard đang lọc kho B
            // → backend trả về removed_ids → FE skip / remove khỏi state).
            // Capture filter key BEFORE the async RPC so we can detect stale
            // responses: if the user changes filter while the request is in
            // flight, the response belongs to the old filter and must be
            // discarded — otherwise orders from the wrong warehouse get merged.
            const filterKeyAtStart = this._buildFilterKey();
            const res = await this.orm.call(
                "sale.order", "get_delivery_orders_subset", [],
                { order_ids: soIds, filter_kwargs: this._buildFetchKwargs() }
            );
            // Drop stale response if filter changed while RPC was in-flight
            if (this._buildFilterKey() !== filterKeyAtStart) {
                return;
            }
            const fresh = (res && res.orders) || [];
            const removed = new Set((res && res.removed_ids) || []);
            this._mergeSubset(fresh, removed);
            // Persist the merged state to cache
            const cacheable = {
                dashboard_stats: this.state.dashboardStats,
                orders: this.state.saleOrders,
                total_count: this.state.totalCount,
                warehouses: this.state.warehouses,
                tags: this.state.tags,
            };
            await this._saveToCache(cacheable);
        } catch (e) {
            console.error("Subset refresh failed, falling back to full refresh:", e);
            await this._silentRefresh();
        }
    }

    /**
     * Merge subset result into state.saleOrders WITHOUT replacing the array.
     * - Update existing orders in-place (only changed properties are reactive-touched).
     * - Insert new orders that pass the screen filter at the end.
     * - Remove orders explicitly marked as removed by the backend.
     */
    _mergeSubset(freshOrders, removedIds) {
        const todayStr = new Date().toISOString().slice(0, 10);
        const indexById = new Map();
        this.state.saleOrders.forEach((o, idx) => indexById.set(o.id, idx));

        for (const fresh of freshOrders) {
            fresh.flows = fresh.flows || [];
            fresh.pickings = fresh.pickings || [];
            fresh.lines = fresh.lines || [];
            fresh.pos = fresh.pos || [];
            const orderDate = fresh.misa_order_date || (fresh.date_order ? fresh.date_order.substring(0, 10) : '');
            fresh.is_new_order = orderDate === todayStr;
            this._applyFlowColors(fresh);

            const idx = indexById.get(fresh.id);
            if (idx !== undefined) {
                // In-place property update — preserves reactive identity, only touched keys re-render
                const old = this.state.saleOrders[idx];
                for (const key of Object.keys(fresh)) {
                    old[key] = fresh[key];
                }
                // Drop any old keys not present in fresh
                for (const key of Object.keys(old)) {
                    if (!(key in fresh)) delete old[key];
                }
            } else {
                // New order entered the visible set — append
                this.state.saleOrders.push(fresh);
            }
        }
        // Remove deleted/cancelled orders
        if (removedIds && removedIds.size) {
            for (let i = this.state.saleOrders.length - 1; i >= 0; i--) {
                if (removedIds.has(this.state.saleOrders[i].id)) {
                    this.state.saleOrders.splice(i, 1);
                }
            }
        }
    }

    /**
     * Refresh data without loading spinner.
     * Smart-merge: only update orders that changed, add new, remove deleted.
     * Preserves scroll position and avoids full kanban re-render.
     */
    async _silentRefresh() {
        const isKanban = this.state.viewMode === 'kanban';
        // Stats refreshed independently \u2014 don't block silent refresh on it
        this._fetchStatsAsync();
        try {
            const result = await this.orm.call(
                "sale.order",
                "get_delivery_dashboard_data",
                [],
                {
                    ...this._buildFetchKwargs(),
                    limit: isKanban ? this.state.kanbanBatchSize : this.state.itemsPerPage,
                    offset: isKanban ? 0 : (this.state.currentPage - 1) * this.state.itemsPerPage,
                    include_stats: false,
                }
            );
            this._mergeResult(result);
            await this._saveToCache(result);
        } catch (error) {
            console.error("Silent refresh failed:", error);
        }
    }

    /**
     * Smart merge: update existing orders in-place, add new, remove deleted.
     * OWL only re-renders cards whose reactive properties actually changed.
     */
    _mergeResult(result) {
        // Stats handled independently — only update if backend returned them
        if (result.dashboard_stats) {
            this.state.dashboardStats = result.dashboard_stats;
        }
        this.state.totalCount = result.total_count || 0;

        const newOrders = result.orders || [];
        const todayStr = new Date().toISOString().slice(0, 10);

        // Build map of current orders by ID for O(1) lookup
        const oldMap = new Map();
        for (const so of this.state.saleOrders) {
            oldMap.set(so.id, so);
        }

        // Build new order list, reusing old objects where nothing changed
        const merged = [];
        for (const fresh of newOrders) {
            fresh.flows = fresh.flows || [];
            fresh.pickings = fresh.pickings || [];
            fresh.lines = fresh.lines || [];
            fresh.pos = fresh.pos || [];
            const orderDate = fresh.misa_order_date || (fresh.date_order ? fresh.date_order.substring(0, 10) : '');
            fresh.is_new_order = orderDate === todayStr;

            const old = oldMap.get(fresh.id);
            if (old) {
                // Update existing order in-place (OWL detects property changes)
                const skipKeys = new Set(['id']);
                for (const key of Object.keys(fresh)) {
                    if (skipKeys.has(key)) continue;
                    old[key] = fresh[key];
                }
                // Re-apply flow link colors
                this._applyFlowColors(old);
                merged.push(old);
                oldMap.delete(fresh.id);
            } else {
                // New order
                this._applyFlowColors(fresh);
                merged.push(fresh);
            }
        }

        // Replace array only if order IDs changed (added/removed/reordered)
        const oldIds = this.state.saleOrders.map(o => o.id).join(',');
        const newIds = merged.map(o => o.id).join(',');
        if (oldIds !== newIds) {
            this.state.saleOrders = merged;
        }

        // Update warehouses/tags if first time
        if (this.state.warehouses.length === 0) {
            this.state.warehouses = result.warehouses || [];
        }
        if (this.state.tags.length === 0) {
            this.state.tags = result.tags || [];
        }
    }

    _applyFlowColors(so) {
        const nodeByName = {};
        so.flows.forEach(flow => {
            (flow.nodes || []).forEach(node => { nodeByName[node.name] = node; });
        });
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
    }


    // --- IndexedDB Cache helpers ---
    _CACHE_DB = 'hlv_dp_cache';
    _CACHE_STORE = 'dashboard';
    _CACHE_TTL = 5 * 60 * 1000; // 5 minutes

    _openCacheDB() {
        return new Promise((resolve, reject) => {
            const req = indexedDB.open(this._CACHE_DB, 1);
            req.onupgradeneeded = () => {
                const db = req.result;
                if (!db.objectStoreNames.contains(this._CACHE_STORE)) {
                    db.createObjectStore(this._CACHE_STORE);
                }
            };
            req.onsuccess = () => resolve(req.result);
            req.onerror = () => reject(req.error);
        });
    }

    _buildFilterKey() {
        return JSON.stringify({
            q: this.state.searchQuery.trim(),
            wh: this.state.filterWarehouseId,
            ds: this.state.filterDeliveryStatus,
            ss: this.state.filterStockStatus,
            ps: this.state.filterPackingStatus,
            df: this.state.filterDateFrom,
            dt: this.state.filterDateTo,
            ddf: this.state.filterDoneDateFrom,
            ddt: this.state.filterDoneDateTo,
            pdf: this.state.filterPODateFrom,
            pdt: this.state.filterPODateTo,
            pos: this.state.filterPOStatus,
            sc: this.state.filterSalerCode.trim(),
            htgh: this.state.filterHtgh.trim(),
            dtype: this.state.filterDeliveryType,
            tags: this.state.filterTagIds.join(','),
            comp: this.state.showCompleted,
            nt: this.state.filterNeedTransfer,
            no: this.state.filterNewOrders,
            pr: this.state.filterPrintStatus,
            sr: this.state.filterShipperReceived,
            vm: this.state.viewMode,
        });
    }

    async _saveToCache(result) {
        try {
            // Serialize through JSON to strip OWL reactive Proxy objects —
            // IndexedDB's structured clone algorithm cannot clone Proxies and
            // throws DataCloneError when state arrays are passed directly
            // (e.g. from _refreshSubset or _autoLoadAllRemaining).
            let orders, dashboardStats, warehouses, tags;
            try {
                orders = JSON.parse(JSON.stringify(result.orders || []));
                dashboardStats = result.dashboard_stats ? JSON.parse(JSON.stringify(result.dashboard_stats)) : undefined;
                warehouses = result.warehouses ? JSON.parse(JSON.stringify(result.warehouses)) : undefined;
                tags = result.tags ? JSON.parse(JSON.stringify(result.tags)) : undefined;
            } catch (serErr) {
                console.warn('[DP Cache] _saveToCache serialization failed:', serErr);
                return;
            }
            const db = await this._openCacheDB();
            const tx = db.transaction(this._CACHE_STORE, 'readwrite');
            tx.objectStore(this._CACHE_STORE).put({
                filterKey: this._buildFilterKey(),
                timestamp: Date.now(),
                kanbanBatchSize: this.state.kanbanBatchSize,
                data: {
                    dashboard_stats: dashboardStats,
                    orders: orders,
                    total_count: result.total_count,
                    warehouses: warehouses,
                    tags: tags,
                },
            }, 'latest');
            await new Promise((resolve, reject) => {
                tx.oncomplete = () => resolve();
                tx.onerror = () => reject(tx.error);
            });
            db.close();
            console.log('[DP Cache] Saved', orders.length, 'orders to IndexedDB');
        } catch (e) {
            console.warn('[DP Cache] _saveToCache failed:', e);
        }
    }

    async _loadFromCache() {
        try {
            const db = await this._openCacheDB();
            return new Promise((resolve) => {
                const tx = db.transaction(this._CACHE_STORE, 'readonly');
                const req = tx.objectStore(this._CACHE_STORE).get('latest');
                req.onsuccess = () => {
                    db.close();
                    const payload = req.result;
                    if (!payload) { console.log('[DP Cache] No cached data found'); return resolve(null); }
                    if (payload.filterKey !== this._buildFilterKey()) { console.log('[DP Cache] Filter key mismatch, skipping cache'); return resolve(null); }
                    if (Date.now() - payload.timestamp > this._CACHE_TTL) { console.log('[DP Cache] Cache expired'); return resolve(null); }
                    // Restore kanbanBatchSize so "tải thêm" data persists
                    if (payload.kanbanBatchSize) {
                        this.state.kanbanBatchSize = payload.kanbanBatchSize;
                    }
                    console.log('[DP Cache] Restored', (payload.data.orders || []).length, 'orders (batchSize=' + (payload.kanbanBatchSize || '?') + ') from IndexedDB');
                    resolve(payload.data);
                };
                req.onerror = () => { db.close(); console.warn('[DP Cache] _loadFromCache read error'); resolve(null); };
            });
        } catch (e) {
            console.warn('[DP Cache] _loadFromCache failed:', e);
            return null;
        }
    }

    _applyResult(result) {
        // NOTE: do not overwrite dashboardStats here — stats are loaded
        // independently via _fetchStatsAsync so the kanban/table can render
        // without waiting on stats compute. We only assign if the backend
        // actually returned non-null stats (legacy callers / first paint).
        if (result.dashboard_stats) {
            this.state.dashboardStats = result.dashboard_stats;
        }
        const fetchedOrders = result.orders || [];
        this.state.saleOrders = fetchedOrders.map(so => {
            so.flows = so.flows || [];
            so.pickings = so.pickings || [];
            so.lines = so.lines || [];
            so.pos = so.pos || [];
            this._applyFlowColors(so);
            return so;
        });

        // Đánh dấu đơn mới: misa_order_date (hoặc date_order) = hôm nay
        const todayStr = new Date().toISOString().slice(0, 10);
        for (const so of this.state.saleOrders) {
            const orderDate = so.misa_order_date || (so.date_order ? so.date_order.substring(0, 10) : '');
            so.is_new_order = orderDate === todayStr;
        }

        this.state.totalCount = result.total_count || 0;
        if (this.state.warehouses.length === 0) {
            this.state.warehouses = result.warehouses || [];
        }
        if (this.state.tags.length === 0) {
            this.state.tags = result.tags || [];
        }
    }

    /**
     * Build the kwargs object passed to RPC calls.
     * Shared by full data fetch and stats-only prefetch.
     */
    _buildFetchKwargs() {
        return {
            search_query: this.state.searchQuery.trim(),
            filter_warehouse_id: this.state.filterWarehouseId,
            filter_delivery_status: this.state.filterDeliveryStatus,
            filter_stock_status: this.state.filterStockStatus,
            filter_date_from: this.state.filterDateFrom,
            filter_date_to: this.state.filterDateTo,
            filter_done_date_from: this.state.filterDoneDateFrom,
            filter_done_date_to: this.state.filterDoneDateTo,
            filter_po_date_from: this.state.filterPODateFrom,
            filter_po_date_to: this.state.filterPODateTo,
            filter_po_status: this.state.filterPOStatus,
            filter_packing_status: this.state.filterPackingStatus,
            filter_saler_code: this.state.filterSalerCode.trim(),
            filter_htgh: this.state.filterHtgh.trim(),
            filter_delivery_type: this.state.filterDeliveryType,
            filter_tag_ids: this.state.filterTagIds.join(','),
            show_completed: this.state.showCompleted,
            filter_need_transfer: this.state.filterNeedTransfer,
            filter_new_orders: this.state.filterNewOrders,
            filter_print_status: this.state.filterPrintStatus,
            filter_shipper_received: this.state.filterShipperReceived,
        };
    }

    /**
     * Fetch KPI stats independently of the main data fetch. Runs in the
     * background and updates `state.dashboardStats` whenever it returns —
     * the table/kanban/card view never waits on it. Cached on backend so
     * cost is ~ms when warm.
     */
    async _fetchStatsAsync() {
        const myToken = (this._statsRequestSeq = (this._statsRequestSeq || 0) + 1);
        this.state.statsLoading = true;
        try {
            const stats = await this.orm.call(
                "sale.order",
                "get_delivery_dashboard_stats",
                [],
                this._buildFetchKwargs(),
            );
            // Drop stale responses if a newer request superseded this one
            if (myToken !== this._statsRequestSeq) return;
            if (stats && stats.dashboard_stats) {
                this.state.dashboardStats = stats.dashboard_stats;
                if (typeof stats.total_count === 'number') {
                    // Only update totalCount from stats if main fetch hasn't
                    // already populated it (avoid flicker).
                    if (!this.state.totalCount) {
                        this.state.totalCount = stats.total_count;
                    }
                }
            }
        } catch (e) {
            console.debug('[DP Stats] async fetch failed:', e);
        } finally {
            if (myToken === this._statsRequestSeq) {
                this.state.statsLoading = false;
            }
        }
    }

    async fetchData() {
        // Don't show full loading spinner if we already have data on screen
        // (cache restored OR previous fetch already populated saleOrders).
        // This prevents the full-screen overlay from flashing on every
        // filter change — instead the user keeps seeing the current rows
        // while a thin "refreshing" indicator runs at the top.
        const hasDataOnScreen = this._isCacheRestored || (this.state.saleOrders && this.state.saleOrders.length > 0);
        if (!hasDataOnScreen) {
            this.state.isLoading = true;
        } else {
            this.state.isRefreshing = true;
        }
        const isKanban = this.state.viewMode === 'kanban';

        // Fire stats fetch INDEPENDENTLY — we don't await it. Stats render
        // when ready, and never block kanban/table painting.
        this._fetchStatsAsync();

        try {
            const result = await this.orm.call(
                "sale.order",
                "get_delivery_dashboard_data",
                [],
                {
                    ...this._buildFetchKwargs(),
                    // Kanban tải theo batch, không phân trang backend
                    limit: isKanban ? this.state.kanbanBatchSize : this.state.itemsPerPage,
                    offset: isKanban ? 0 : (this.state.currentPage - 1) * this.state.itemsPerPage,
                    include_stats: false,
                }
            );

            this._applyResult(result);
            // Save to IndexedDB cache for instant restore on next page load
            await this._saveToCache(result);
            // Auto-load all remaining orders in background — no spinner, no confirm.
            // Ensures không xót đơn khi tổng số đơn > initial batch size.
            this._autoLoadAllRemaining(); // intentionally NOT awaited
        } catch (error) {
            console.error("Lỗi khi tải dữ liệu bảng điều phối:", error);
        } finally {
            this.state.isLoading = false;
            this.state.isRefreshing = false;
        }
    }

    // --- Background auto-load (no-spinner, no confirm) ---
    _autoLoadSeq = 0;

    /**
     * Tải hết toàn bộ đơn còn lại vào state.saleOrders trong nền,
     * ngay sau khi fetchData xong batch đầu.
     * - Không cần user bấm nút "Tải hết" nữa.
     * - Sequence token tự hủy load cũ khi filter thay đổi (tránh race condition).
     * - Chỉ dùng cho internal dashboard (không public web).
     */
    async _autoLoadAllRemaining() {
        const mySeq = ++this._autoLoadSeq;
        // Đợi 1 tick để render ban đầu hoàn thành trước
        await new Promise(r => setTimeout(r, 50));
        if (mySeq !== this._autoLoadSeq) return;

        const remaining = (this.state.totalCount || 0) - this.state.saleOrders.length;
        if (remaining <= 0) return;

        this.state.isLoadingMore = true;
        try {
            const offset = this.state.saleOrders.length;
            const result = await this.orm.call(
                "sale.order",
                "get_delivery_dashboard_data",
                [],
                {
                    ...this._buildFetchKwargs(),
                    limit: remaining,
                    offset: offset,
                    include_stats: false,
                }
            );
            if (mySeq !== this._autoLoadSeq) return; // stale — filter đổi trong lúc đang tải

            const fresh = (result && result.orders) || [];
            const todayStr = new Date().toISOString().slice(0, 10);
            const existingIds = new Set(this.state.saleOrders.map(o => o.id));
            for (const so of fresh) {
                if (existingIds.has(so.id)) continue;
                so.flows = so.flows || [];
                so.pickings = so.pickings || [];
                so.lines = so.lines || [];
                so.pos = so.pos || [];
                this._applyFlowColors(so);
                const orderDate = so.misa_order_date || (so.date_order ? so.date_order.substring(0, 10) : '');
                so.is_new_order = orderDate === todayStr;
                this.state.saleOrders.push(so);
            }
            if (typeof result.total_count === 'number') {
                this.state.totalCount = result.total_count;
            }
            // Cập nhật kanbanBatchSize để cache biết full dataset đã được tải
            this.state.kanbanBatchSize = this.state.saleOrders.length;
            await this._saveToCache({
                dashboard_stats: this.state.dashboardStats,
                orders: this.state.saleOrders,
                total_count: this.state.totalCount,
                warehouses: this.state.warehouses,
                tags: this.state.tags,
            });
            console.log('[DP AutoLoad] Loaded all', this.state.saleOrders.length, '/', this.state.totalCount, 'orders');
        } catch (e) {
            console.error('[DP AutoLoad] _autoLoadAllRemaining failed:', e);
        } finally {
            if (mySeq === this._autoLoadSeq) {
                this.state.isLoadingMore = false;
            }
        }
    }

    // --- Computed Filters & Pagination ---
    get totalPages() {
        return Math.ceil(this.state.totalCount / this.state.itemsPerPage) || 1;
    }

    get paginatedOrders() {
        return this._applyArchiveFilter(this.state.saleOrders);
    }

    /**
     * Apply the archive / consolidate view filter:
     *  - archivedView = 'archived'    → only archived SOs
     *  - archivedView = 'consolidate' → only consolidate (chờ gom) SOs
     *  - archivedView = 'none'        → all SOs except archived AND consolidate
     */
    _applyArchiveFilter(orders) {
        const archived = this.state.archivedSOIds;
        const consolidate = this.state.consolidateSOIds;
        if (this.state.archivedView === 'archived') {
            return orders.filter(so => archived.has(so.id));
        }
        if (this.state.archivedView === 'consolidate') {
            return orders.filter(so => consolidate.has(so.id));
        }
        if (!archived.size && !consolidate.size) return orders;
        return orders.filter(so => !archived.has(so.id) && !consolidate.has(so.id));
    }

    isSOArchived(soId) {
        return this.state.archivedSOIds.has(soId);
    }

    isSOConsolidate(soId) {
        return this.state.consolidateSOIds.has(soId);
    }

    async toggleArchiveSO(soId) {
        if (!soId) return;
        const wasArchived = this.state.archivedSOIds.has(soId);
        // Optimistic UI: archive và consolidate là mutually exclusive.
        if (wasArchived) {
            this.state.archivedSOIds.delete(soId);
        } else {
            this.state.archivedSOIds.add(soId);
            this.state.consolidateSOIds.delete(soId);
        }
        try {
            const res = await this.orm.call(
                'hlv.delivery.planner.user.pref', 'toggle_archive', [], { so_id: soId }
            );
            this.state.archivedSOIds = new Set(res.archived_so_ids || []);
            this.state.consolidateSOIds = new Set(res.consolidate_so_ids || []);
        } catch (e) {
            console.error('toggle_archive failed:', e);
            if (wasArchived) {
                this.state.archivedSOIds.add(soId);
            } else {
                this.state.archivedSOIds.delete(soId);
            }
            this.notification.add('Không thể cập nhật trạng thái cất đơn', {
                type: 'danger', title: 'Lỗi',
            });
        }
    }

    async toggleConsolidateSO(soId) {
        if (!soId) return;
        const wasInBucket = this.state.consolidateSOIds.has(soId);
        if (wasInBucket) {
            this.state.consolidateSOIds.delete(soId);
        } else {
            this.state.consolidateSOIds.add(soId);
            this.state.archivedSOIds.delete(soId);
        }
        try {
            const res = await this.orm.call(
                'hlv.delivery.planner.user.pref', 'toggle_consolidate', [], { so_id: soId }
            );
            this.state.archivedSOIds = new Set(res.archived_so_ids || []);
            this.state.consolidateSOIds = new Set(res.consolidate_so_ids || []);
        } catch (e) {
            console.error('toggle_consolidate failed:', e);
            if (wasInBucket) {
                this.state.consolidateSOIds.add(soId);
            } else {
                this.state.consolidateSOIds.delete(soId);
            }
            this.notification.add('Không thể cập nhật đơn chờ gom', {
                type: 'danger', title: 'Lỗi',
            });
        }
    }

    toggleShowArchivedOnly() {
        // Cycle through views: 'none' → 'archived' → 'consolidate' → 'none'
        const nextView = {
            'none': 'archived',
            'archived': 'consolidate',
            'consolidate': 'none'
        }[this.state.archivedView] || 'none';
        this.setArchivedView(nextView);
    }

    setArchivedView(mode) {
        // mode: 'none' | 'archived' | 'consolidate'
        this.state.archivedView = (['archived', 'consolidate'].includes(mode)) ? mode : 'none';
        this.state.showArchivedOnly = (this.state.archivedView === 'archived');
    }

    async clearAllArchived() {
        if (!this.state.archivedSOIds.size) return;
        if (!window.confirm('Phục hồi tất cả ' + this.state.archivedSOIds.size + ' đơn đã cất?')) return;
        try {
            const res = await this.orm.call(
                'hlv.delivery.planner.user.pref', 'set_archived', [], { so_ids: [] }
            );
            this.state.archivedSOIds = new Set(res.archived_so_ids || []);
            this.state.consolidateSOIds = new Set(res.consolidate_so_ids || []);
            if (this.state.archivedView === 'archived') this.setArchivedView('none');
        } catch (e) {
            console.error('clearAllArchived failed:', e);
            this.notification.add('Không thể phục hồi đơn đã cất', {
                type: 'danger', title: 'Lỗi',
            });
        }
    }

    async clearAllConsolidate() {
        if (!this.state.consolidateSOIds.size) return;
        if (!window.confirm('Bỏ gom tất cả ' + this.state.consolidateSOIds.size + ' đơn chờ gom?')) return;
        try {
            const res = await this.orm.call(
                'hlv.delivery.planner.user.pref', 'set_consolidate', [], { so_ids: [] }
            );
            this.state.archivedSOIds = new Set(res.archived_so_ids || []);
            this.state.consolidateSOIds = new Set(res.consolidate_so_ids || []);
            if (this.state.archivedView === 'consolidate') this.setArchivedView('none');
        } catch (e) {
            console.error('clearAllConsolidate failed:', e);
            this.notification.add('Không thể bỏ gom đơn', {
                type: 'danger', title: 'Lỗi',
            });
        }
    }

    /**
     * Load per-user preferences from backend on startup. Applies the saved
     * default filter set IN PLACE on this.state, so the first fetchData()
     * call uses them. Falls back silently if the model is missing (module
     * not yet upgraded) — UI still works, just without backend persistence.
     */
    async _loadUserPreferences() {
        try {
            const res = await this.orm.call(
                'hlv.delivery.planner.user.pref', 'get_user_preferences', [], {}
            );
            this.state.archivedSOIds = new Set(res.archived_so_ids || []);
            this.state.consolidateSOIds = new Set(res.consolidate_so_ids || []);
            const defaults = res.default_filters || {};
            if (defaults && Object.keys(defaults).length) {
                this._applyFilterSnapshot(defaults);
                this.state.hasDefaultFilters = true;
            }
        } catch (e) {
            console.warn('[DP Pref] could not load user preferences:', e);
        }
    }

    /**
     * Snapshot of all filter form state — keys MUST match _applyFilterSnapshot
     * (and _buildFetchKwargs where applicable). Stored as JSON in user pref.
     */
    _buildFilterSnapshot() {
        const s = this.state;
        return {
            searchQuery: s.searchQuery,
            filterWarehouseId: s.filterWarehouseId,
            filterDeliveryStatus: s.filterDeliveryStatus,
            filterStockStatus: s.filterStockStatus,
            filterPackingStatus: s.filterPackingStatus,
            filterDateFrom: s.filterDateFrom,
            filterDateTo: s.filterDateTo,
            filterDoneDateFrom: s.filterDoneDateFrom,
            filterDoneDateTo: s.filterDoneDateTo,
            filterPODateFrom: s.filterPODateFrom,
            filterPODateTo: s.filterPODateTo,
            filterPOStatus: s.filterPOStatus,
            filterSalerCode: s.filterSalerCode,
            filterHtgh: s.filterHtgh,
            filterDeliveryType: s.filterDeliveryType,
            filterTagIds: Array.from(s.filterTagIds || []),
            showCompleted: s.showCompleted,
            filterNeedTransfer: s.filterNeedTransfer,
            filterNewOrders: s.filterNewOrders,
            viewMode: s.viewMode,
            kanbanGroupBy: s.kanbanGroupBy,
        };
    }

    _applyFilterSnapshot(snap) {
        if (!snap || typeof snap !== 'object') return;
        const s = this.state;
        const assign = (key, fallback) => {
            if (snap[key] !== undefined && snap[key] !== null) s[key] = snap[key];
            else if (fallback !== undefined) s[key] = fallback;
        };
        assign('searchQuery');
        assign('filterWarehouseId');
        assign('filterDeliveryStatus');
        assign('filterStockStatus');
        assign('filterPackingStatus');
        assign('filterDateFrom');
        assign('filterDateTo');
        assign('filterDoneDateFrom');
        assign('filterDoneDateTo');
        assign('filterPODateFrom');
        assign('filterPODateTo');
        assign('filterPOStatus');
        assign('filterSalerCode');
        assign('filterHtgh');
        assign('filterDeliveryType');
        if (Array.isArray(snap.filterTagIds)) s.filterTagIds = snap.filterTagIds.slice();
        assign('showCompleted');
        assign('filterNeedTransfer');
        assign('filterNewOrders');
        assign('viewMode');
        assign('kanbanGroupBy');
    }

    /** Save the current filter form as the user's default. */
    async saveCurrentFiltersAsDefault() {
        try {
            const snap = this._buildFilterSnapshot();
            await this.orm.call(
                'hlv.delivery.planner.user.pref', 'save_default_filters',
                [], { filters: snap }
            );
            this.state.hasDefaultFilters = true;
            this.notification.add('Đã lưu bộ lọc mặc định cho bạn', {
                type: 'success', title: 'Lưu thành công',
            });
        } catch (e) {
            console.error('saveCurrentFiltersAsDefault failed:', e);
            this.notification.add('Không thể lưu bộ lọc mặc định', {
                type: 'danger', title: 'Lỗi',
            });
        }
    }

    async clearDefaultFilters() {
        if (!window.confirm('Xoá bộ lọc mặc định đã lưu?')) return;
        try {
            await this.orm.call(
                'hlv.delivery.planner.user.pref', 'clear_default_filters', [], {}
            );
            this.state.hasDefaultFilters = false;
            this.notification.add('Đã xoá bộ lọc mặc định', { type: 'info' });
        } catch (e) {
            console.error('clearDefaultFilters failed:', e);
        }
    }

    // --- Actions ---
    async nextPage() {
        if (this.state.currentPage < this.totalPages) {
            this.state.currentPage++;
            // Khi đã tải hết đơn vào memory, phân trang client-side (không cần gọi server)
            if (this.state.saleOrders.length < this.state.totalCount) {
                await this.fetchData();
            }
        }
    }

    async prevPage() {
        if (this.state.currentPage > 1) {
            this.state.currentPage--;
            // Khi đã tải hết đơn vào memory, phân trang client-side (không cần gọi server)
            if (this.state.saleOrders.length < this.state.totalCount) {
                await this.fetchData();
            }
        }
    }

    /**
     * Cho phép user tự chọn số dòng/trang ở bảng (Card/Table view).
     * Lưu localStorage để nhớ pref qua các phiên.
     */
    async onItemsPerPageChange(ev) {
        var n = parseInt(ev.target.value, 10);
        if (![12, 25, 50, 100, 200].includes(n)) n = 12;
        this.state.itemsPerPage = n;
        this.state.currentPage = 1;
        try { localStorage.setItem('hlv_dp_items_per_page', String(n)); } catch (e) { /* quota / private mode */ }
        await this.fetchData();
    }

    async onFilterChange() {
        this.state.currentPage = 1;
        this.state.kanbanColumnOrder = {};
        this.state.kanbanColPageSize = {};
        this.state.kanbanBatchSize = 100;
        this.state.returnedColPageSize = 15;
        // Xóa selection khi filter thay đổi (tránh giữ đơn không còn trong view)
        this.state.selectedSOIds = new Set();
        await this.fetchData();
    }

    // --- View Mode Toggle ---
    async setViewMode(mode) {
        this.state.viewMode = mode;
        if (mode === 'kanban') {
            // Mặc định: chỉ hiện đơn chưa giao + giao 1 phần (tiết kiệm tải)
            if (this.state.filterDeliveryStatus === 'all') {
                this.state.filterDeliveryStatus = 'pending_partial';
            }
            this.state.filterStockStatus = 'all';
            this.state.kanbanColumnOrder = {};
            this.state.kanbanColPageSize = {};
            this.state.kanbanBatchSize = 100;
        }
        this.state.currentPage = 1;
        await this.fetchData();
    }

    // ============================================================
    // TABLE (BẢNG) VIEW HELPERS
    // ============================================================
    toggleTableSort(field) {
        if (this.state.tableSortField === field) {
            this.state.tableSortDir = this.state.tableSortDir === 'asc' ? 'desc' : 'asc';
        } else {
            this.state.tableSortField = field;
            this.state.tableSortDir = 'asc';
        }
    }

    /**
     * Reset toàn bộ filter cột Bảng (các filter backend được bind từ
     * dropdown trên column header) về giá trị mặc định và refetch backend.
     */
    async resetTableColumnFilters() {
        this.state.filterWarehouseId = 'all';
        this.state.filterDeliveryStatus = 'all';
        this.state.filterStockStatus = 'all';
        this.state.filterPackingStatus = 'all';
        this.state.filterDeliveryType = 'all';
        this.state.filterTagIds = [];
        this.state.filterPrintStatus = 'all';
        this.state.filterShipperReceived = 'all';
        this.state.filterHtgh = '';
        this.state.filterSalerCode = '';
        this.state.searchQuery = '';
        this.state.filterDateFrom = '';
        await this.onFilterChange();
    }

    toggleTableRowExpand(soId) {
        if (this.state.expandedTableRows.has(soId)) {
            this.state.expandedTableRows.delete(soId);
        } else {
            this.state.expandedTableRows.add(soId);
        }
        // Force reactivity
        this.state.expandedTableRows = new Set(this.state.expandedTableRows);
    }

    isTableRowExpanded(soId) {
        return this.state.expandedTableRows.has(soId);
    }

    /**
     * Debounced backend filter trigger for Bảng column text inputs.
     * Updates `state[stateKey]` immediately (so input value is responsive)
     * but waits 400ms of idle before calling onFilterChange() → backend.
     */
    setTableFilterDebounced(stateKey, value) {
        this.state[stateKey] = value;
        if (this._tableFilterDebounceTimer) {
            clearTimeout(this._tableFilterDebounceTimer);
        }
        this._tableFilterDebounceTimer = setTimeout(() => {
            this._tableFilterDebounceTimer = null;
            this.onFilterChange();
        }, 400);
    }

    /** True if any filter beyond the defaults is active (used to show "clear" button on Bảng) */
    get hasAnyTableFilter() {
        const s = this.state;
        return (
            (s.searchQuery && s.searchQuery.trim()) ||
            (s.filterWarehouseId && s.filterWarehouseId !== 'all') ||
            (s.filterDeliveryStatus && s.filterDeliveryStatus !== 'all' && s.filterDeliveryStatus !== 'pending_partial') ||
            (s.filterStockStatus && s.filterStockStatus !== 'all') ||
            (s.filterPackingStatus && s.filterPackingStatus !== 'all') ||
            (s.filterDeliveryType && s.filterDeliveryType !== 'all') ||
            (s.filterHtgh && s.filterHtgh.trim()) ||
            (s.filterSalerCode && s.filterSalerCode.trim()) ||
            (s.filterTagIds && s.filterTagIds.length > 0)
        );
    }

    /** Reset all Bảng-relevant filters to default and refetch */
    async clearAllTableFilters() {
        this.state.searchQuery = '';
        this.state.filterWarehouseId = 'all';
        this.state.filterDeliveryStatus = 'pending_partial';
        this.state.filterStockStatus = 'all';
        this.state.filterPackingStatus = 'all';
        this.state.filterDeliveryType = 'all';
        this.state.filterHtgh = '';
        this.state.filterSalerCode = '';
        this.state.filterTagIds = [];
        await this.onFilterChange();
    }

    /**
     * Compute the print status of a SO based on its outbound (PICK) pickings:
     *   - 'none'    : không có phiếu PICK
     *   - 'unprinted'  : có phiếu nhưng chưa in cái nào
     *   - 'partial'    : in một phần
     *   - 'printed'    : tất cả PICK đã in
     */
    getSOPrintStatus(so) {
        const pickings = (so.pickings || []).filter(p => (p.sequence_code || '').toUpperCase().startsWith('PICK'));
        if (!pickings.length) return 'none';
        const printed = pickings.filter(p => p.printed).length;
        if (printed === 0) return 'unprinted';
        if (printed === pickings.length) return 'printed';
        return 'partial';
    }

    getPrintStatusLabel(status) {
        return ({
            none: '—',
            unprinted: 'Chưa in',
            partial: 'In một phần',
            printed: 'Đã in',
        })[status] || '—';
    }

    getPrintStatusBadgeClass(status) {
        return ({
            none: 'bg-light text-muted',
            unprinted: 'bg-danger text-white',
            partial: 'bg-warning text-dark',
            printed: 'bg-success text-white',
        })[status] || 'bg-light text-muted';
    }

    /**
     * Compute shipper-receive status of a SO based on its outbound pickings:
     *   - 'none'      : không có phiếu PICK
     *   - 'unreceived': chưa shipper nào nhận
     *   - 'partial'   : nhận một phần
     *   - 'received'  : tất cả đã nhận
     */
    getSOReceiveStatus(so) {
        const pickings = (so.pickings || []).filter(p => (p.sequence_code || '').toUpperCase().startsWith('PICK'));
        if (!pickings.length) return 'none';
        const received = pickings.filter(p => p.shipper_received).length;
        if (received === 0) return 'unreceived';
        if (received === pickings.length) return 'received';
        return 'partial';
    }

    getReceiveStatusLabel(status) {
        return ({
            none: '—',
            unreceived: 'Chưa nhận',
            partial: 'Nhận một phần',
            received: 'Đã nhận',
        })[status] || '—';
    }

    getReceiveStatusBadgeClass(status) {
        return ({
            none: 'bg-light text-muted',
            unreceived: 'bg-secondary text-white',
            partial: 'bg-warning text-dark',
            received: 'bg-info text-dark',
        })[status] || 'bg-light text-muted';
    }

    /** Sorted client-side based on tableSortField/tableSortDir.
     *  Filtering is now done on the BACKEND via state.filter* fields. */
    get tableSortedOrders() {
        const orders = this._applyArchiveFilter(this.state.saleOrders || []);
        const field = this.state.tableSortField;
        const dir = this.state.tableSortDir === 'asc' ? 1 : -1;
        const getVal = (so) => {
            switch (field) {
                case 'name': return so.name || '';
                case 'misa_order_date': return so.misa_order_date || '';
                case 'partner': return (so.partner_id && so.partner_id[1]) || '';
                case 'warehouse': return (so.warehouse_id && so.warehouse_id[1]) || '';
                case 'delivery_status': return so.real_delivery_status || so.delivery_status || '';
                case 'stock_status': return so.stock_status || '';
                case 'packing_status': return so.packing_status || '';
                case 'commitment_date': return so.commitment_date || '';
                case 'amount_total': return Number(so.amount_total) || 0;
                default: return '';
            }
        };
        // Copy first to avoid mutating the reactive proxy in-place
        const arr = orders.slice();
        arr.sort((a, b) => {
            const va = getVal(a);
            const vb = getVal(b);
            if (typeof va === 'number' && typeof vb === 'number') {
                return (va - vb) * dir;
            }
            return String(va).localeCompare(String(vb), 'vi') * dir;
        });
        // Khi toàn bộ đơn đã được tải vào memory (sau auto-load),
        // phân trang client-side để tránh gọi server thêm.
        const allLoaded = this.state.totalCount > 0 && arr.length >= this.state.totalCount;
        if (allLoaded) {
            const start = (this.state.currentPage - 1) * this.state.itemsPerPage;
            return arr.slice(start, start + this.state.itemsPerPage);
        }
        return arr;
    }

    /** Color-code main row by status (delivery + packing) */
    getTableRowClass(so) {
        const classes = ['cursor-pointer'];
        const ds = so.real_delivery_status || so.delivery_status;
        if (ds === 'full') {
            classes.push('hlv-row-delivered');
        } else if (so.stock_status === 'out_of_stock') {
            classes.push('hlv-row-oos');
        } else if (so.stock_status === 'partial_ready') {
            classes.push('hlv-row-partial');
        } else if (so.stock_status === 'ready') {
            classes.push('hlv-row-ready');
        }
        if (so.is_returned_or_stopped) {
            classes.push('hlv-row-stopped');
        }
        if (so.has_unread_message) {
            classes.push('hlv-row-unread');
        }
        return classes.join(' ');
    }

    /** Collect distinct shipper names from active pickings */
    getShippersForSO(so) {
        const seen = new Set();
        const out = [];
        for (const pk of (so.pickings || [])) {
            const u = pk.shipper_user;
            if (u && !seen.has(u)) {
                seen.add(u);
                out.push(u);
            }
        }
        return out;
    }

    /** Select / deselect all SO currently visible (sorted page) */
    toggleSelectAllVisibleSO() {
        const visible = this.tableSortedOrders;
        const allSelected = visible.length > 0 &&
            visible.every(so => this.state.selectedSOIds.has(so.id));
        if (allSelected) {
            visible.forEach(so => this.state.selectedSOIds.delete(so.id));
        } else {
            visible.forEach(so => this.state.selectedSOIds.add(so.id));
        }
        this.state.selectedSOIds = new Set(this.state.selectedSOIds);
    }

    get allTableRowsSelected() {
        const visible = this.tableSortedOrders;
        return visible.length > 0 &&
            visible.every(so => this.state.selectedSOIds.has(so.id));
    }

    /** Column resize: drag right border of <th> to change its width */
    onColResizeStart(ev, colKey) {
        ev.stopPropagation();
        ev.preventDefault();
        const th = ev.target.closest('th');
        if (!th) return;
        const startX = ev.clientX;
        const startWidth = th.offsetWidth;
        const onMove = (e) => {
            const delta = e.clientX - startX;
            const newW = Math.max(80, startWidth + delta);
            th.style.width = newW + 'px';
            th.style.minWidth = newW + 'px';
        };
        const onUp = () => {
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
            document.body.style.userSelect = '';
        };
        document.body.style.userSelect = 'none';
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
    }

    setKanbanGroupBy(dim) {
        this.state.kanbanGroupBy = dim;
        this.state.kanbanColumnOrder = {};
        this.state.kanbanColPageSize = {};
    }

    // --- Kanban Column Definitions ---
    get kanbanColumnDefs() {
        switch (this.state.kanbanGroupBy) {
            case 'delivery_status': return [
                { value: 'pending', label: 'Chưa Giao', badgeClass: 'bg-danger', textClass: 'text-danger', iconClass: 'fa fa-clock-o', progressClass: 'bg-danger' },
                { value: 'partial', label: 'Giao 1 Phần', badgeClass: 'bg-warning text-dark', textClass: 'text-warning', iconClass: 'fa fa-truck', progressClass: 'bg-warning' },
                { value: 'full', label: 'Đã Giao Đủ', badgeClass: 'bg-success', textClass: 'text-success', iconClass: 'fa fa-check-circle', progressClass: 'bg-success' },
            ];
            case 'stock_status': return [
                { value: 'out_of_stock', label: 'Không Có Hàng', badgeClass: 'bg-danger', textClass: 'text-danger', iconClass: 'fa fa-times-circle', progressClass: 'bg-danger' },
                { value: 'partial_ready', label: 'Có Hàng 1 Phần', badgeClass: 'bg-warning text-dark', textClass: 'text-warning', iconClass: 'fa fa-exclamation-circle', progressClass: 'bg-warning' },
                { value: 'ready', label: 'Đủ Hàng Xuất', badgeClass: 'bg-success', textClass: 'text-success', iconClass: 'fa fa-check', progressClass: 'bg-success' },
            ];
            case 'packing_status': return [
                { value: 'waiting_stock', label: 'Không Có Hàng Đóng', badgeClass: 'bg-secondary', textClass: 'text-secondary', iconClass: 'fa fa-hourglass-start', progressClass: 'bg-secondary' },
                { value: 'unpacked', label: 'Có Hàng Chưa Đóng Gói', badgeClass: 'bg-warning text-dark', textClass: 'text-warning', iconClass: 'fa fa-exclamation-triangle', progressClass: 'bg-warning' },
                { value: 'printed_waiting', label: 'Đã In, Chờ Đóng Gói', badgeClass: 'bg-info', textClass: 'text-info', iconClass: 'fa fa-print', progressClass: 'bg-info' },
                { value: 'packed_waiting_ship', label: 'Đã Gói, Chờ Nhận Giao', badgeClass: 'bg-primary', textClass: 'text-primary', iconClass: 'fa fa-archive', progressClass: 'bg-primary' },
                { value: 'shipping', label: 'Đang Giao', badgeClass: 'bg-success', textClass: 'text-success', iconClass: 'fa fa-motorcycle', progressClass: 'bg-success' },
                { value: 'delivered_today', label: 'Đã Giao Trong Ngày', badgeClass: 'bg-success bg-opacity-75', textClass: 'text-success', iconClass: 'fa fa-calendar-check-o', progressClass: 'bg-success' },
            ];
            default: return [];
        }
    }

    // Internal: toàn bộ SO của cột (theo DnD order)
    _allOrdersForColumn(colValue) {
        const dim = this.state.kanbanGroupBy;
        const fieldMap = {
            delivery_status: 'real_delivery_status',
            stock_status: 'stock_status',
            packing_status: 'packing_status',
        };
        const field = fieldMap[dim];

        const base = this._applyArchiveFilter(this.state.saleOrders || []).filter(so => {
            if (so.is_returned_or_stopped) return false;   // hiện riêng trong cột "Trả hàng"
            let val = so[field];
            if (dim === 'delivery_status' && val === 'unshipped') val = 'pending';
            if (dim === 'packing_status') {
                // delivered_today: ưu tiên CAO NHẤT
                // - Đã giao hôm nay (kể cả partial) VÀ không có PICK nào assigned sẵn hàng
                if (so.has_delivered_today && (so.real_delivery_status === 'full' || !so.has_assigned_pick)) {
                    val = 'delivered_today';
                } else if (so.real_delivery_status === 'full') {
                    return false;
                }
                // Shipper đã nhận → "Đang giao"
                else if (so.has_shipper_received) val = 'shipping';
                // Đã đóng gói đủ → chuyển sang cột "Đã gói, chờ nhận giao"
                else if (val === 'fully_packed') val = 'packed_waiting_ship';
                // Active PICK đã in → "Đã in, chờ đóng gói"
                else if (so.has_active_pick_printed) val = 'printed_waiting';
                // Gơm nhóm: còn hàng chưa đóng = cần xử lý ngay.
                else if (val === 'partial_packed') val = 'unpacked';
            }
            return val === colValue;
        });

        const order = this.state.kanbanColumnOrder[colValue];
        if (!order || !order.length) return base;
        const orderMap = {};
        order.forEach((id, idx) => { orderMap[id] = idx; });
        return [...base].sort((a, b) => (orderMap[a.id] ?? 9999) - (orderMap[b.id] ?? 9999));
    }

    // Public: chỉ trả N card đầu (phân trang client-side)
    ordersForColumn(colValue) {
        const pageSize = this.state.kanbanColPageSize[colValue] || 15;
        return this._allOrdersForColumn(colValue).slice(0, pageSize);
    }

    totalInColumn(colValue) {
        return this._allOrdersForColumn(colValue).length;
    }

    hasMoreInColumn(colValue) {
        const pageSize = this.state.kanbanColPageSize[colValue] || 15;
        return this._allOrdersForColumn(colValue).length > pageSize;
    }

    loadMoreColumn(colValue) {
        const current = this.state.kanbanColPageSize[colValue] || 15;
        this.state.kanbanColPageSize[colValue] = current + 15;
    }

    get hasMoreKanbanData() {
        return this.state.viewMode === 'kanban' && this.state.saleOrders.length < this.state.totalCount;
    }

    get remainingKanbanCount() {
        return Math.max(0, (this.state.totalCount || 0) - (this.state.saleOrders || []).length);
    }

    /**
     * Tải hết các đơn còn lại trong Kanban với MỘT request duy nhất
     * (limit = số còn lại). Có confirm để tránh bấm nhầm.
     */
    async loadAllKanbanBatch() {
        if (this.state.isLoading || this.state.isLoadingMore || !this.hasMoreKanbanData) return;
        const remaining = this.remainingKanbanCount;
        if (!remaining) return;
        // Soft-confirm khi số đơn còn lại lớn để tránh tải nhầm gây lag
        if (remaining > 300) {
            const ok = window.confirm(`Tải tất cả ${remaining} đơn còn lại? Có thể chậm nếu số lượng lớn.`);
            if (!ok) return;
        }
        const currentLen = this.state.saleOrders.length;
        this.state.isLoadingMore = true;
        try {
            const result = await this.orm.call(
                "sale.order",
                "get_delivery_dashboard_data",
                [],
                {
                    ...this._buildFetchKwargs(),
                    limit: remaining,
                    offset: currentLen,
                    include_stats: false,
                }
            );
            const fresh = (result && result.orders) || [];
            const todayStr = new Date().toISOString().slice(0, 10);
            const existingIds = new Set(this.state.saleOrders.map(o => o.id));
            for (const so of fresh) {
                if (existingIds.has(so.id)) continue;
                so.flows = so.flows || [];
                so.pickings = so.pickings || [];
                so.lines = so.lines || [];
                so.pos = so.pos || [];
                this._applyFlowColors(so);
                const orderDate = so.misa_order_date || (so.date_order ? so.date_order.substring(0, 10) : '');
                so.is_new_order = orderDate === todayStr;
                this.state.saleOrders.push(so);
            }
            if (typeof result.total_count === 'number') {
                this.state.totalCount = result.total_count;
            }
            this.state.kanbanBatchSize = this.state.saleOrders.length;
            await this._saveToCache({
                dashboard_stats: this.state.dashboardStats,
                orders: this.state.saleOrders,
                total_count: this.state.totalCount,
                warehouses: this.state.warehouses,
                tags: this.state.tags,
            });
        } catch (e) {
            console.error("loadAllKanbanBatch failed:", e);
        } finally {
            this.state.isLoadingMore = false;
        }
    }

    async loadMoreKanbanBatch() {
        if (this.state.isLoading || this.state.isLoadingMore || !this.hasMoreKanbanData) return;
        const BATCH = 100;
        const currentLen = this.state.saleOrders.length;
        this.state.isLoadingMore = true;
        try {
            const result = await this.orm.call(
                "sale.order",
                "get_delivery_dashboard_data",
                [],
                {
                    ...this._buildFetchKwargs(),
                    limit: BATCH,
                    offset: currentLen,
                    include_stats: false,
                }
            );
            const fresh = (result && result.orders) || [];
            const todayStr = new Date().toISOString().slice(0, 10);
            const existingIds = new Set(this.state.saleOrders.map(o => o.id));
            for (const so of fresh) {
                if (existingIds.has(so.id)) continue; // dedupe (e.g. bus update during fetch)
                so.flows = so.flows || [];
                so.pickings = so.pickings || [];
                so.lines = so.lines || [];
                so.pos = so.pos || [];
                this._applyFlowColors(so);
                const orderDate = so.misa_order_date || (so.date_order ? so.date_order.substring(0, 10) : '');
                so.is_new_order = orderDate === todayStr;
                this.state.saleOrders.push(so);
            }
            if (typeof result.total_count === 'number') {
                this.state.totalCount = result.total_count;
            }
            this.state.kanbanBatchSize = this.state.saleOrders.length;
            // Persist appended state to cache
            await this._saveToCache({
                dashboard_stats: this.state.dashboardStats,
                orders: this.state.saleOrders,
                total_count: this.state.totalCount,
                warehouses: this.state.warehouses,
                tags: this.state.tags,
            });
        } catch (e) {
            console.error("loadMoreKanbanBatch failed:", e);
        } finally {
            this.state.isLoadingMore = false;
        }
    }

    // --- Returned / Stopped orders group ---
    get returnedOrders() {
        return this._applyArchiveFilter(this.state.saleOrders.filter(so => so.is_returned_or_stopped));
    }

    get returnedOrdersPaged() {
        return this.returnedOrders.slice(0, this.state.returnedColPageSize);
    }

    get hasMoreReturnedOrders() {
        return this.returnedOrders.length > this.state.returnedColPageSize;
    }

    loadMoreReturnedOrders() {
        this.state.returnedColPageSize += 15;
    }

    // --- Selection for Printing ---
    toggleSOSelection(soId) {
        if (this.state.selectedSOIds.has(soId)) {
            this.state.selectedSOIds.delete(soId);
        } else {
            this.state.selectedSOIds.add(soId);
        }
        // Force reactivity
        this.state.selectedSOIds = new Set(this.state.selectedSOIds);
    }

    isSOSelected(soId) {
        return this.state.selectedSOIds.has(soId);
    }

    selectAllInColumn(columnValue) {
        const ordersInColumn = this.ordersForColumn(columnValue);
        ordersInColumn.forEach(so => this.state.selectedSOIds.add(so.id));
        this.state.selectedSOIds = new Set(this.state.selectedSOIds);
    }

    deselectAllInColumn(columnValue) {
        const ordersInColumn = this.ordersForColumn(columnValue);
        ordersInColumn.forEach(so => this.state.selectedSOIds.delete(so.id));
        this.state.selectedSOIds = new Set(this.state.selectedSOIds);
    }

    clearAllSelections() {
        this.state.selectedSOIds.clear();
        this.state.selectedSOIds = new Set(this.state.selectedSOIds);
    }

    get allSelectedInColumn() {
        // Return object: { columnValue: boolean }
        const result = {};
        this.kanbanColumnDefs.forEach(col => {
            const ordersInCol = this.ordersForColumn(col.value);
            result[col.value] = ordersInCol.length > 0 &&
                ordersInCol.every(so => this.state.selectedSOIds.has(so.id));
        });
        return result;
    }

    get selectedCount() {
        return this.state.selectedSOIds.size;
    }

    getSelectedPickingIds() {
        const selectedIds = new Set(this.state.selectedSOIds);
        const pickingIds = [];
        const seenPickingIds = new Set();

        for (const so of this.state.saleOrders) {
            if (!selectedIds.has(so.id)) {
                continue;
            }
            for (const picking of so.pickings || []) {
                if (!picking || !picking.id) {
                    continue;
                }
                const sequenceCode = (picking.sequence_code || '').toUpperCase();
                if (!sequenceCode.includes('PICK')) {
                    continue;
                }
                if (picking.state === 'done' || picking.state === 'cancel' || picking.return_of_id) {
                    continue;
                }
                if (seenPickingIds.has(picking.id)) {
                    continue;
                }
                seenPickingIds.add(picking.id);
                pickingIds.push(picking.id);
            }
        }

        return pickingIds;
    }

    // toggle select print menu
    toggleSelectedPickingPrintMenu(ev) {
        ev.stopPropagation();
        if (this.state.selectedPrintMenuPos) {
            this.state.selectedPrintMenuPos = null;
            return;
        }
        const rect = ev.currentTarget.getBoundingClientRect();
        this.state.selectedPrintMenuPos = {
            top: rect.bottom + window.scrollY,
            right: window.innerWidth - rect.right,
        };

        // Chỉ show report có tên chứa "lấy hàng"
        this.state.selectedPrintMenuReports = this.state.pickingReports.filter((r) =>
            r.name.toLowerCase().includes('lấy hàng')
        );
    }

    closeSelectedPickingPrintMenu() {
        this.state.selectedPrintMenuPos = null;
    }

    async _ensurePackerUsers() {
        if (this.state.packerUsers.length || this.state.packerUsersLoading) return;
        this.state.packerUsersLoading = true;
        try {
            const users = await this.orm.call('stock.picking', 'get_packer_users_for_assignment', [], {});
            this.state.packerUsers = (users || []).map((u) => ({
                id: u.id,
                name: u.name,
                packer_name: u.packer_name || u.name,
            }));
            if (!this.state.selectedPackerUserId && this.state.packerUsers.length) {
                this.state.selectedPackerUserId = this.state.packerUsers[0].id;
            }
        } catch (e) {
            console.error('Load packer users failed:', e);
            this.notification.add('Không tải được danh sách người đóng', { type: 'danger' });
        } finally {
            this.state.packerUsersLoading = false;
        }
    }

    formatPackDuration(seconds) {
        seconds = Math.round(seconds || 0);
        if (!seconds) return '-';
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        if (hours) return `${hours}h ${minutes}m`;
        return `${minutes}m`;
    }

    async loadPackingProgress() {
        if (this.state.packingProgressLoading) return;
        this.state.packingProgressLoading = true;
        try {
            const today = new Date().toISOString().slice(0, 10);
            const result = await this.orm.call('stock.picking', 'get_packing_kpi_dashboard', [], {
                date_from: today,
                date_to: today,
                packer_user_id: 'all',
            });
            this.state.packingProgress = result || { summary: {}, groups: [] };
        } catch (e) {
            console.warn('Load packing progress failed:', e);
        } finally {
            this.state.packingProgressLoading = false;
        }
    }

    async togglePackingProgressDrawer() {
        this.state.isPackingProgressDrawerOpen = !this.state.isPackingProgressDrawerOpen;
        if (this.state.isPackingProgressDrawerOpen) {
            await this._ensurePackerUsers();
            await this.loadPackingProgress();
        }
    }

    async reassignDrawerPacker(pickId, newPackerUserId) {
        const uid = parseInt(newPackerUserId, 10);
        if (!uid || !pickId) return;
        try {
            await this.orm.call('stock.picking', 'action_assign_packer', [[pickId]], {
                packer_user_id: uid,
            });
            await this.loadPackingProgress();
        } catch (e) {
            this.notification.add(e.message || 'Đổi packer thất bại', { type: 'danger' });
        }
    }

    async openPackerAssignModal(reportId = null, reportType = 'qweb-pdf', pickingId = null) {
        this.state.pendingPrintReportId = reportId;
        this.state.pendingPrintReportType = reportType || 'qweb-pdf';
        this.state.pendingSinglePrintPickingId = pickingId || null;
        this.state.selectedPrintMenuPos = null;
        await this._ensurePackerUsers();
        this.state.isPackerAssignModalOpen = true;
    }

    onPackerSelectChange(ev) {
        this.state.selectedPackerUserId = parseInt(ev.target.value || '0', 10) || null;
    }

    closePackerAssignModal() {
        if (this.state.isPrintingPickingSlips) return;
        this.state.isPackerAssignModalOpen = false;
        this.state.pendingPrintReportId = null;
        this.state.pendingPrintReportType = 'qweb-pdf';
        this.state.pendingSinglePrintPickingId = null;
        this.state.changePackerPickingId = null;
    }

    async openChangePackerModal(pickingId) {
        this.state.changePackerPickingId = pickingId;
        this.state.pendingPrintReportId = null;
        this.state.pendingSinglePrintPickingId = null;
        // Pre-select current packer if known
        const allPickings = this.state.saleOrders.flatMap(so => so.pickings || []);
        const picking = allPickings.find(p => p.id === pickingId);
        if (picking && picking.packer_user && picking.packer_user[0]) {
            this.state.selectedPackerUserId = picking.packer_user[0];
        } else {
            this.state.selectedPackerUserId = null;
        }
        await this._ensurePackerUsers();
        this.state.isPackerAssignModalOpen = true;
    }

    async confirmPackerAssignAndPrint() {
        if (!this.state.selectedPackerUserId) {
            this.notification.add('Vui lòng chọn người đóng', { type: 'warning' });
            return;
        }
        const packerUserId = this.state.selectedPackerUserId;
        const changePickingId = this.state.changePackerPickingId;
        const reportId = this.state.pendingPrintReportId;
        const reportType = this.state.pendingPrintReportType || 'qweb-pdf';
        const pickingId = this.state.pendingSinglePrintPickingId;
        this.state.isPackerAssignModalOpen = false;

        if (changePickingId) {
            // Change packer only mode (no print)
            this.state.changePackerPickingId = null;
            try {
                await this.orm.call('stock.picking', 'action_assign_packer', [[changePickingId]], { packer_user_id: packerUserId });
                const packer = this.state.packerUsers.find(u => u.id === packerUserId);
                const packerLabel = packer ? (packer.packer_name || packer.name || '') : '';
                for (const so of this.state.saleOrders) {
                    const pk = (so.pickings || []).find(p => p.id === changePickingId);
                    if (pk) { pk.packer_user = [packerUserId, packerLabel]; break; }
                }
                if (this.state.selectedOrder) {
                    const pk = (this.state.selectedOrder.pickings || []).find(p => p.id === changePickingId);
                    if (pk) pk.packer_user = [packerUserId, packerLabel];
                }
                this.notification.add('Đã đổi người đóng thành công', { type: 'success' });
            } catch (e) {
                console.error('Change packer failed:', e);
                this.notification.add('Không thể đổi người đóng', { type: 'danger' });
            }
            return;
        }

        if (pickingId) {
            await this.doPrintPickingReport(null, pickingId, reportId, packerUserId, true);
        } else {
            await this.printSelectedPickingSlips(reportId, reportType, packerUserId, true);
        }
    }

    async printSelectedPickingSlips(reportId = null, reportType = 'qweb-pdf', packerUserId = null, skipPackerModal = false) {
        if (this.selectedCount === 0) return;
        if (this.state.isPrintingPickingSlips) return;

        const selectedIds = Array.from(this.state.selectedSOIds);
        const pickingIds = this.getSelectedPickingIds().filter((id) => {
            const picking = this.state.saleOrders
                .flatMap((so) => so.pickings || [])
                .find((p) => p.id === id);
            return picking && picking.state === 'assigned';
        });

        if (!pickingIds.length) {
            alert('Không có phiếu lấy hàng nào ở trạng thái sẵn sàng để in');
            return;
        }
        if (!skipPackerModal) {
            await this.openPackerAssignModal(reportId, reportType);
            return;
        }
        if (!packerUserId) {
            this.notification.add('Vui lòng chọn người đóng trước khi in', { type: 'warning' });
            await this.openPackerAssignModal(reportId, reportType);
            return;
        }
        this.state.selectedPrintMenuPos = null;

        try {
            // Local flag — KHÔNG dùng state.isLoading để tránh triệu hồi full-screen overlay
            // / re-render kanban. Bus event sẽ tự động triệu hồi subset refresh.
            this.state.isPrintingPickingSlips = true;

            // Luôn gọi giữ hàng (check availability) trước khi in
            // Backend sẽ tự xác định picking nào chưa assigned để reserve
            try {
                const reserveResponse = await fetch('/hlv_sale_delivery_planning/reserve_stock', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest',
                    },
                    body: JSON.stringify({
                        jsonrpc: '2.0',
                        method: 'call',
                        params: { sale_order_ids: selectedIds },
                    }),
                });
                const reserveResult = await reserveResponse.json();
                if (reserveResult.result) {
                    console.log('Giữ hàng:', reserveResult.result.message);
                }
            } catch (reserveErr) {
                console.warn('Giữ hàng thất bại, tiếp tục in:', reserveErr);
            }

            if (reportId && reportType !== 'qweb-pdf') {
                if (!pickingIds.length) {
                    alert('Không có phiếu lấy hàng hợp lệ để in');
                    return;
                }
                await this.actionService.doAction(reportId, {
                    additionalContext: {
                        active_ids: pickingIds,
                        active_id: pickingIds[0],
                        active_model: 'stock.picking',
                    },
                });
                this.clearAllSelections();
            } else {
                const url = `/hlv_sale_delivery_planning/print_picking_slips`;
                const response = await fetch(url, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest',
                    },
                    body: JSON.stringify({
                        jsonrpc: '2.0',
                        method: 'call',
                        params: {
                            sale_order_ids: selectedIds,
                            report_id: reportId,
                            packer_user_id: packerUserId,
                        },
                    }),
                });

                const result = await response.json();
                if (result.error) {
                    console.error('Error printing picking slips:', result.error);
                    alert('Lỗi khi in phiếu lấy hàng: ' + (result.error.data?.message || result.error.message));
                    return;
                }

                if (result.result && result.result.success === false) {
                    alert(result.result.message || 'Không thể in phiếu lấy hàng');
                    return;
                }

                if (result.result && result.result.url) {
                    window.open(result.result.url, '_blank');
                    for (const so of this.state.saleOrders) {
                        if (selectedIds.includes(so.id)) {
                            so.has_active_pick_printed = true;
                            for (const pk of (so.pickings || [])) {
                                if (pickingIds.includes(pk.id)) {
                                    pk.printed = true;
                                    pk.packer_user = [result.result.packer_user_id, result.result.packer_name];
                                }
                            }
                        }
                    }
                    this.clearAllSelections();
                }
            }
        } catch (error) {
            console.error('Error printing picking slips:', error);
            alert('Lỗi khi in phiếu lấy hàng');
        } finally {
            this.state.isPrintingPickingSlips = false;
        }
    }

    // --- Drag & Drop Handlers ---
    onDragStart(ev, soId) {
        this.state.draggedSoId = soId;
        ev.dataTransfer.effectAllowed = 'move';
        ev.dataTransfer.setData('text/plain', String(soId));
    }

    onDragOver(ev, colValue) {
        ev.preventDefault();
        ev.dataTransfer.dropEffect = 'move';
        if (this.state.dragOverColumn !== colValue) {
            this.state.dragOverColumn = colValue;
        }
    }

    onDragLeave(ev) {
        // Chỉ xóa highlight khi thực sự rời khỏi column (không phải trượt qua child)
        if (!ev.currentTarget.contains(ev.relatedTarget)) {
            this.state.dragOverColumn = null;
        }
    }

    onDrop(ev, colValue) {
        ev.preventDefault();
        const soId = parseInt(ev.dataTransfer.getData('text/plain'), 10);
        if (!soId) return;

        const dim = this.state.kanbanGroupBy;
        const fieldMap = {
            delivery_status: 'real_delivery_status',
            stock_status: 'stock_status',
            packing_status: 'packing_status',
        };
        const field = fieldMap[dim];

        // Cập nhật state cục bộ (optimistic update)
        const so = this.state.saleOrders.find(s => s.id === soId);
        if (so) {
            so[field] = colValue;
        }

        // Đưa card lên đầu cột đích
        const existingOrder = (this.state.kanbanColumnOrder[colValue] || []).filter(id => id !== soId);
        this.state.kanbanColumnOrder[colValue] = [soId, ...existingOrder];

        this.state.draggedSoId = null;
        this.state.dragOverColumn = null;
    }

    onDragEnd() {
        this.state.draggedSoId = null;
        this.state.dragOverColumn = null;
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
            this.state.selectedSOIds = new Set();
            await this.fetchData();
        }
    }

    async onTagFilterChange(ev) {
        this.state.filterTagIds = Array.from(ev.target.selectedOptions)
            .map(o => parseInt(o.value))
            .filter(v => !isNaN(v));
        this.state.currentPage = 1;
        this.state.selectedSOIds = new Set();
        await this.fetchData();
    }

    // ── Inline edit: Ghi Chú Odoo ──────────────────────────────────────
    startGhiChuEdit(ev, so) {
        ev.stopPropagation();
        this.state.inlineEditSOId = so.id;
        this.state.inlineEditGhiChu = so.x_studio_ghi_ch_odoo || '';
    }

    cancelGhiChuEdit() {
        this.state.inlineEditSOId = null;
        this.state.inlineEditGhiChu = '';
    }

    async saveGhiChu(so) {
        // Guard against double-save: Enter triggers keydown→save→cancelGhiChuEdit,
        // then the resulting blur fires save again with inlineEditGhiChu already ''.
        if (this.state.inlineEditSOId !== so.id) return;
        const val = (this.state.inlineEditGhiChu || '').trim();
        if (val === (so.x_studio_ghi_ch_odoo || '')) {
            this.cancelGhiChuEdit();
            return;
        }
        try {
            await this.orm.write('sale.order', [so.id], { x_studio_ghi_ch_odoo: val });
            so.x_studio_ghi_ch_odoo = val;
            // sync drawer if open
            if (this.state.selectedOrder && this.state.selectedOrder.id === so.id) {
                this.state.selectedOrder.x_studio_ghi_ch_odoo = val;
            }
            this.notification.add('Đã lưu Ghi Chú Odoo', { type: 'success', sticky: false });
        } catch (e) {
            this.notification.add('Lỗi khi lưu: ' + e.message, { type: 'danger' });
        }
        this.cancelGhiChuEdit();
    }

    onGhiChuKeydown(ev, so) {
        if (ev.key === 'Enter' && !ev.shiftKey) {
            ev.preventDefault();
            this.saveGhiChu(so);
        } else if (ev.key === 'Escape') {
            this.cancelGhiChuEdit();
        }
    }

    // ── Inline edit: Tag picker ────────────────────────────────────────
    openTagPicker(ev, so) {
        ev.stopPropagation();
        if (this.state.tagPickerSOId === so.id) {
            this.state.tagPickerSOId = null;
            this.state.tagPickerPos = null;
            return;
        }
        const rect = ev.currentTarget.getBoundingClientRect();
        this.state.tagPickerSOId = so.id;
        this.state.tagPickerPos = {
            top: rect.bottom + window.scrollY + 4,
            left: rect.left + window.scrollX,
        };
    }

    closeTagPicker() {
        this.state.tagPickerSOId = null;
        this.state.tagPickerPos = null;
    }

    isTagOnSO(so, tagId) {
        return (so.tag_ids || []).some(t => t[0] === tagId);
    }

    async toggleTagOnSO(ev, so, tagId) {
        ev.stopPropagation();
        const has = this.isTagOnSO(so, tagId);
        const tag = this.state.tags.find(t => t.id === tagId);
        if (!tag) return;
        let newTagIds;
        if (has) {
            newTagIds = (so.tag_ids || []).filter(t => t[0] !== tagId);
        } else {
            newTagIds = [...(so.tag_ids || []), [tagId, tag.name, tag.color || 0]];
        }
        try {
            const ids = newTagIds.map(t => t[0]);
            await this.orm.write('sale.order', [so.id], { tag_ids: [[6, 0, ids]] });
            so.tag_ids = newTagIds;
            if (this.state.selectedOrder && this.state.selectedOrder.id === so.id) {
                this.state.selectedOrder.tag_ids = newTagIds;
            }
        } catch (e) {
            this.notification.add('Lỗi khi cập nhật tag: ' + e.message, { type: 'danger' });
        }
    }

    async removeTagFromSO(ev, so, tagId) {
        ev.stopPropagation();
        const newTagIds = (so.tag_ids || []).filter(t => t[0] !== tagId);
        try {
            await this.orm.write('sale.order', [so.id], { tag_ids: [[6, 0, newTagIds.map(t => t[0])]] });
            so.tag_ids = newTagIds;
            if (this.state.selectedOrder && this.state.selectedOrder.id === so.id) {
                this.state.selectedOrder.tag_ids = newTagIds;
            }
        } catch (e) {
            this.notification.add('Lỗi khi xóa tag: ' + e.message, { type: 'danger' });
        }
    }

    // Odoo crm.tag color integer → background color
    getTagColor(colorInt) {
        const COLORS = [
            '#adb5bd', // 0 grey
            '#dc3545', // 1 red
            '#fd7e14', // 2 orange
            '#ffc107', // 3 yellow
            '#20c997', // 4 teal
            '#6610f2', // 5 indigo
            '#d63384', // 6 pink
            '#0d6efd', // 7 blue
            '#6f42c1', // 8 purple
            '#e91e63', // 9 fuchsia
            '#198754', // 10 green
            '#0dcaf0', // 11 cyan
        ];
        return COLORS[colorInt] || COLORS[0];
    }

    getTagTextColor(colorInt) {
        // Dark text for light backgrounds (yellow, teal, cyan), white for others
        return [3, 4, 11].includes(colorInt) ? '#000' : '#fff';
    }

    openSaleOrder(soId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "sale.order",
            res_id: soId,
            views: [[false, "form"]],
            target: "new",
        });
    }

    openPurchaseOrder(poId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "purchase.order",
            res_id: poId,
            views: [[false, "form"]],
            target: "new",
        });
    }

    openPicking(pickingId) {
        this.state.printMenuPickingId = null;
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "stock.picking",
            res_id: pickingId,
            views: [[false, "form"]],
            target: "new",
        });
    }

    async togglePickingPrintMenu(ev, pickingId) {
        ev.stopPropagation();
        if (this.state.printMenuPickingId === pickingId) {
            this.state.printMenuPickingId = null;
            this.state.printMenuPos = null;
            return;
        }
        const rect = ev.currentTarget.getBoundingClientRect();
        this.state.printMenuPickingId = pickingId;
        this.state.printMenuPos = {
            top: rect.bottom + window.scrollY,
            right: window.innerWidth - rect.right,
        };

        const allowedIds = await this.orm.call(
            'ir.actions.actions',
            'get_allowed_picking_reports',
            [],
            {
                context: {
                    active_ids: [pickingId],
                    active_id: pickingId,
                    active_model: 'stock.picking',
                }
            }
        );
        const allowedSet = new Set(allowedIds);
        this.state.printMenuReports = this.state.pickingReports.filter((r) =>
            allowedSet.has(r.id)
        );
    }

    _isPickingSlipReport(reportId) {
        const report = (this.state.pickingReports || []).find((r) => r.id === reportId);
        const name = ((report && report.name) || '').toLowerCase();
        const reportName = ((report && report.report_name) || '').toLowerCase();
        return name.includes('lấy hàng') || name.includes('hoạt động lấy hàng') || reportName.startsWith('stock.report_picking');
    }

    _isPickPickingId(pickingId) {
        for (const so of this.state.saleOrders || []) {
            const picking = (so.pickings || []).find((p) => p.id === pickingId);
            if (picking) {
                return (picking.sequence_code || '').toUpperCase().includes('PICK') && !picking.return_of_id && picking.state !== 'cancel';
            }
        }
        return false;
    }

    async doPrintPickingReport(ev, pickingId, reportId, packerUserId = null, skipPackerModal = false) {
        if (ev && ev.stopPropagation) ev.stopPropagation();
        this.state.printMenuPickingId = null;
        if (!skipPackerModal && this._isPickPickingId(pickingId) && this._isPickingSlipReport(reportId)) {
            await this.openPackerAssignModal(reportId, 'qweb-pdf', pickingId);
            return;
        }
        if (packerUserId && this._isPickPickingId(pickingId) && this._isPickingSlipReport(reportId)) {
            const result = await this.orm.call('stock.picking', 'assign_picking_print_packer', [], {
                picking_ids: [pickingId],
                packer_user_id: packerUserId,
            });
            if (!result.success) {
                this.notification.add(result.message || 'Không assign được người đóng', { type: 'danger' });
                return;
            }
        }
        await this.actionService.doAction(reportId, {
            additionalContext: {
                active_ids: [pickingId],
                active_id: pickingId,
                active_model: 'stock.picking',
                hlv_skip_packer_assignment_dialog: true,
            }
        });
    }

    openVideo(url) {
        window.open(url, '_blank');
    }

    // --- PO Status Formatting (Receipt Based) ---
    getPOStatusClass(receiptStatus) {
        switch (receiptStatus) {
            case "pending": return "bg-secondary";
            case "partial": return "bg-warning text-dark";
            case "full": return "bg-success";
            default: return "bg-light text-muted border";
        }
    }

    // --- Translations (delegate to utils) ---
    translatePOStatus(s) { return translatePOStatus(s); }
    translateDeliveryStatus(s) { return translateDeliveryStatus(s); }
    translatePickingState(s) { return translatePickingState(s); }
    translatePickingStatus(s) { return translatePickingStatus(s); }
    translateStockStatus(s) { return translateStockStatus(s); }
    translatePackingStatus(s) { return translatePackingStatus(s); }
    translateSOStatus(s) { return translateSOStatus(s); }

    formatPackageGroupStatus(so, group) {
        if (group.picking_state !== 'done') {
            return this.translatePickingState(group.picking_state);
        }

        // Logic: Nếu có bất kỳ kiện nào trong group đã đến 'Partners/Customers' -> "Đã giao khách"
        const hasDeliveredPack = (group.packages || []).some(p =>
            (p.location_name || "").includes("Partners/Customers")
        );

        if (hasDeliveredPack) {
            return "Đã giao khách";
        }

        // Nếu là phiếu đóng gói xong or phiếu OUT xong mà chưa giao đến khách -> "Đã đóng gói" 
        const lowerName = (group.picking_name || "").toLowerCase();
        if (lowerName.includes("pack") || lowerName.includes("đóng gói") || lowerName.includes("đầu ra")) {
            return "Đã đóng gói";
        }

        return "Hoàn thành";
    }

    getPackageGroupBadgeClass(so, group) {
        if (group.picking_state !== 'done') {
            return this.getPickingStateBadgeClass(group.picking_state);
        }

        const status = this.formatPackageGroupStatus(so, group);
        if (status === "Đã giao khách") {
            return "bg-success text-bg-success"; // Green
        }
        if (status === "Đã đóng gói") {
            return "bg-info text-bg-info"; // Blue
        }
        return "bg-primary text-bg-primary"; // Hoàn thành default
    }

    toggleSection(sectionKey) {
        if (this.state.collapsedSections.has(sectionKey)) {
            this.state.collapsedSections.delete(sectionKey);
        } else {
            this.state.collapsedSections.add(sectionKey);
        }
    }

    isSectionCollapsed(sectionKey) {
        return this.state.collapsedSections.has(sectionKey);
    }

    /**
     * Lazy-load flows for a given SO when the user expands the
     * "Luồng Xử Lý Kho" section. The default dashboard payload no longer
     * contains flows (heavy recursive picking-graph walk → ~40-60% CPU per
     * page). We fetch them on demand and cache on so.flows.
     */
    async toggleFlowSection(so) {
        // Mirror the global section toggle (used by other so cards too)
        this.toggleSection('flows');
        const expanded = !this.isSectionCollapsed('flows');
        if (!expanded) return;
        if (!so || !so.has_flow) return;
        if (Array.isArray(so.flows) && so.flows.length > 0) return; // already loaded
        if (so.flows_loading) return;
        so.flows_loading = true;
        try {
            const res = await this.orm.call(
                "sale.order", "get_delivery_so_flow", [], { so_id: so.id }
            );
            const flows = (res && res.flows) || [];
            so.flows = flows;
            this._applyFlowColors(so);
        } catch (e) {
            console.error("get_delivery_so_flow failed:", e);
            so.flows = [];
        } finally {
            so.flows_loading = false;
        }
    }

    // --- Badge Classes (delegate to utils) ---
    getPickingStateBadgeClass(s) { return getPickingStateBadgeClass(s); }
    getPickingStatusBadgeClass(s) { return getPickingStatusBadgeClass(s); }
    getDeliveryStatusBadgeClass(s) { return getDeliveryStatusBadgeClass(s); }
    getStockStatusBadgeClass(s) { return getStockStatusBadgeClass(s); }
    getPackingStatusBadgeClass(s) { return getPackingStatusBadgeClass(s); }
    getPOStatusBadgeClass(state, receipt) { return getPOStatusBadgeClass(state, receipt); }
    getSOCardColorClass(so) { return getSOCardColorClass(so); }

    // --- Formatting (delegate to utils) ---
    formatCurrency(v) { return formatCurrency(v); }
    formatQty(v) { return formatQty(v); }
    getDatesComparisonClass(soDate, poDate) { return getDatesComparisonClass(soDate, poDate); }

    // --- Group duplicate product lines ---
    groupedLines(lines) {
        if (!lines || !lines.length) return [];
        const map = {};
        const order = [];
        for (const l of lines) {
            const pid = l.product_id ? l.product_id[0] : 0;
            if (map[pid]) {
                map[pid].product_uom_qty += (l.product_uom_qty || 0);
                map[pid].qty_delivered += (l.qty_delivered || 0);
                map[pid].qty_reserved_here += (l.qty_reserved_here || 0); // sum across lines
                // qty_warehouse_free: keep first (product-level, same for all lines of same product/wh)
                map[pid].delivered_subtotal += (l.delivered_subtotal || 0);
                map[pid].delivered_tax += (l.delivered_tax || 0);
                map[pid].delivered_total += (l.delivered_total || 0);
            } else {
                map[pid] = {
                    ...l, product_uom_qty: l.product_uom_qty || 0,
                    qty_delivered: l.qty_delivered || 0, qty_packed: l.qty_packed || 0,
                    qty_available: l.qty_available || 0, qty_warehouse_free: l.qty_warehouse_free || 0,
                    qty_reserved_here: l.qty_reserved_here || 0,
                    delivered_subtotal: l.delivered_subtotal || 0,
                    delivered_tax: l.delivered_tax || 0,
                    delivered_total: l.delivered_total || 0
                };
                order.push(pid);
            }
        }
        return order.map(pid => map[pid]);
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
        this.state.drawerMessages = [];
        this.state.drawerMessageText = '';
        this.state.drawerMessageFiles = [];
        this.loadDrawerMessages(so.id);
    }

    async loadDrawerMessages(orderId) {
        this.state.drawerMessagesLoading = true;
        try {
            const result = await this.orm.call(
                'hlv.delivery.planner.service', 'get_order_messages',
                [orderId]
            );
            this.state.drawerMessages = (result || []).map(msg => {
                if (msg.body) {
                    msg.body = markup(msg.body);
                }
                return msg;
            });
        } catch (e) {
            console.error('loadDrawerMessages error', e);
            this.state.drawerMessages = [];
        }
        this.state.drawerMessagesLoading = false;
    }

    async sendDrawerMessage() {
        const body = (this.state.drawerMessageText || '').trim();
        const attachments = this.state.drawerMessageFiles.map((file) => ({
            name: file.name,
            mimetype: file.mimetype,
            datas: file.datas,
        }));
        if ((!body && !attachments.length) || !this.state.selectedOrder || this.state.drawerMessageSending) return;

        try {
            this.state.drawerMessageSending = true;
            await this.orm.call(
                'hlv.delivery.planner.service', 'post_order_message',
                [this.state.selectedOrder.id, body, attachments]
            );
            this.state.drawerMessageText = '';
            this.state.drawerMessageFiles = [];
            await this.loadDrawerMessages(this.state.selectedOrder.id);
        } catch (e) {
            console.error('sendDrawerMessage error', e);
        } finally {
            this.state.drawerMessageSending = false;
        }
    }

    onMessageKeydown(ev) {
        if (ev.key === 'Enter' && !ev.shiftKey) {
            ev.preventDefault();
            this.sendDrawerMessage();
        }
    }

    async onDrawerMessagePaste(ev) {
        const items = ev.clipboardData && ev.clipboardData.items;
        if (!items) return;
        const imageItems = Array.from(items).filter(it => it.type.startsWith('image/'));
        if (!imageItems.length) return;
        ev.preventDefault();
        const maxFileSize = 20 * 1024 * 1024;
        const nextFiles = [...this.state.drawerMessageFiles];
        for (const item of imageItems) {
            const file = item.getAsFile();
            if (!file) continue;
            if (file.size > maxFileSize) {
                this.notification.add('Ảnh dán quá 20MB.', { type: 'warning' });
                continue;
            }
            const extMap = { 'image/png': '.png', 'image/jpeg': '.jpg', 'image/gif': '.gif', 'image/webp': '.webp', 'image/bmp': '.bmp' };
            const ext = extMap[file.type] || '.png';
            const name = `paste_${Date.now()}${ext}`;
            try {
                const datas = await this._readFileAsBase64(file);
                nextFiles.push({
                    uid: `${Date.now()}_${Math.random().toString(36).slice(2)}`,
                    name,
                    mimetype: file.type,
                    size: file.size || 0,
                    datas,
                });
            } catch (e) {
                this.notification.add('Không thể đọc ảnh dán.', { type: 'danger' });
            }
        }
        this.state.drawerMessageFiles = nextFiles;
    }

    triggerDrawerFilePicker() {
        const picker = document.getElementById('drawer-message-file-input');
        if (picker) {
            picker.click();
        }
    }

    async onDrawerFilesSelected(ev) {
        const picker = ev.target;
        const files = Array.from((picker && picker.files) || []);
        if (!files.length) {
            return;
        }

        const allowedExt = ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.csv'];
        const maxFileSize = 20 * 1024 * 1024;
        const nextFiles = [...this.state.drawerMessageFiles];

        for (const file of files) {
            const lowerName = (file.name || '').toLowerCase();
            const ext = lowerName.includes('.') ? lowerName.slice(lowerName.lastIndexOf('.')) : '';
            const isImage = (file.type || '').startsWith('image/');
            const isVideo = (file.type || '').startsWith('video/');
            const isPdf = (file.type || '') === 'application/pdf' || ext === '.pdf';
            const isDoc = allowedExt.includes(ext);

            if (!isImage && !isVideo && !isDoc && !isPdf) {
                this.notification.add(`File ${file.name} không thuộc định dạng hỗ trợ.`, { type: 'warning' });
                continue;
            }
            if (file.size > maxFileSize) {
                this.notification.add(`File ${file.name} vượt quá 20MB.`, { type: 'warning' });
                continue;
            }

            try {
                const datas = await this._readFileAsBase64(file);
                nextFiles.push({
                    uid: `${Date.now()}_${Math.random().toString(36).slice(2)}`,
                    name: file.name,
                    mimetype: file.type || 'application/octet-stream',
                    size: file.size || 0,
                    datas,
                });
            } catch (readErr) {
                this.notification.add(`Không thể đọc file ${file.name}.`, { type: 'danger' });
                console.error('read file error', readErr);
            }
        }

        this.state.drawerMessageFiles = nextFiles;
        picker.value = '';
    }

    _readFileAsBase64(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => {
                const result = String(reader.result || '');
                const commaIndex = result.indexOf(',');
                resolve(commaIndex >= 0 ? result.slice(commaIndex + 1) : result);
            };
            reader.onerror = reject;
            reader.readAsDataURL(file);
        });
    }

    removeDrawerMessageFile(uid) {
        this.state.drawerMessageFiles = this.state.drawerMessageFiles.filter((f) => f.uid !== uid);
    }

    formatFileSize(size) {
        const value = Number(size || 0);
        if (value >= 1024 * 1024) {
            return `${(value / (1024 * 1024)).toFixed(1)} MB`;
        }
        if (value >= 1024) {
            return `${Math.round(value / 1024)} KB`;
        }
        return `${value} B`;
    }

    isVideoAttachment(att) {
        return !!(att && att.mimetype && att.mimetype.indexOf('video/') === 0);
    }

    closeOverviewDrawer() {
        this.state.isDrawerOpen = false;
    }

    // --- Package Modal Actions
    openPackageDetails(pack) {
        this.state.selectedPackage = pack;
        this.state.isPackageModalOpen = true;
    }

    closePackageDetails() {
        this.state.isPackageModalOpen = false;
        this.state.selectedPackage = null;
    }

    // ── Transfer Modal ────────────────────────────────────────────────────

    async openTransferModal() {
        if (this.selectedCount === 0) {
            alert('Vui lòng chọn ít nhất 1 đơn hàng.');
            return;
        }
        this.state.isTransferModalOpen = true;
        this.state.transferModalLoading = true;
        this.state.transferModalData = null;
        this.state.transferSelections = {};

        try {
            const selectedIds = Array.from(this.state.selectedSOIds);
            const data = await this.orm.call(
                'sale.order',
                'prepare_transfer_modal_data',
                [],
                { sale_order_ids: selectedIds }
            );
            this.state.transferModalData = data;

            // Init selections for each warehouse (partner auto-applied from wh.partner_id)
            const selections = {};
            for (const wh of (data.warehouses || [])) {
                const prodSel = {};
                for (const prod of (wh.products || [])) {
                    prodSel[prod.product_id] = { include: true, qty: prod.total_qty };
                }
                selections[wh.warehouse_id] = {
                    selected: true,
                    partner_id: wh.partner_id || false,
                    products: prodSel,
                };
            }
            this.state.transferSelections = selections;
        } catch (err) {
            console.error('Lỗi khi tải dữ liệu luân chuyển:', err);
            alert('Lỗi khi phân tích dữ liệu luân chuyển: ' + (err.message || ''));
            this.state.isTransferModalOpen = false;
        } finally {
            this.state.transferModalLoading = false;
        }
    }

    closeTransferModal() {
        this.state.isTransferModalOpen = false;
        this.state.transferModalData = null;
        this.state.transferSelections = {};
    }

    toggleWarehouseSelection(whId, checked) {
        if (!this.state.transferSelections[whId]) return;
        this.state.transferSelections[whId].selected = checked;
        // Force OWL reactivity
        this.state.transferSelections = { ...this.state.transferSelections };
    }

    setTransferPartner(whId, partnerId) {
        if (!this.state.transferSelections[whId]) return;
        this.state.transferSelections[whId].partner_id = partnerId ? parseInt(partnerId) : '';
    }

    getProductSelection(whId, productId) {
        const whSel = this.state.transferSelections[whId];
        if (!whSel || !whSel.products) return null;
        return whSel.products[productId] || null;
    }

    toggleProductSelection(whId, productId, checked) {
        const whSel = this.state.transferSelections[whId];
        if (!whSel) return;
        if (!whSel.products[productId]) return;
        whSel.products[productId].include = checked;
        this.state.transferSelections = { ...this.state.transferSelections };
    }

    toggleAllProducts(whId, checked) {
        const whSel = this.state.transferSelections[whId];
        if (!whSel) return;
        for (const pid of Object.keys(whSel.products)) {
            whSel.products[pid].include = checked;
        }
        this.state.transferSelections = { ...this.state.transferSelections };
    }

    areAllProductsSelected(whId) {
        const whSel = this.state.transferSelections[whId];
        if (!whSel || !whSel.products) return false;
        return Object.values(whSel.products).every(p => p.include);
    }

    setProductQty(whId, productId, qty) {
        const whSel = this.state.transferSelections[whId];
        if (!whSel || !whSel.products[productId]) return;
        whSel.products[productId].qty = qty;
    }

    countSelectedProducts(whId) {
        const whSel = this.state.transferSelections[whId];
        if (!whSel) return 0;
        return Object.values(whSel.products || {}).filter(p => p.include).length;
    }

    sumSelectedQty(whId) {
        const whSel = this.state.transferSelections[whId];
        if (!whSel) return 0;
        return Object.values(whSel.products || {})
            .filter(p => p.include)
            .reduce((s, p) => s + (p.qty || 0), 0);
    }

    exportTransferExcel() {
        const selectedIds = Array.from(this.state.selectedSOIds);
        if (!selectedIds.length) return;
        const params = new URLSearchParams();
        params.set('sale_order_ids', JSON.stringify(selectedIds));
        window.open(`/hlv_sale_delivery_planning/export_transfer_excel?${params.toString()}`, '_blank');
    }

    async confirmCreateTransferPickings() {
        const data = this.state.transferModalData;
        if (!data || !data.warehouses) return;

        const warehouseSelections = [];
        for (const wh of data.warehouses) {
            const sel = this.state.transferSelections[wh.warehouse_id];
            if (!sel || !sel.selected) continue;

            const products = (wh.products || [])
                .filter(prod => {
                    const ps = sel.products[prod.product_id];
                    return ps && ps.include && ps.qty > 0;
                })
                .map(prod => ({
                    product_id: prod.product_id,
                    total_qty: sel.products[prod.product_id].qty,
                }));

            if (!products.length) continue;

            warehouseSelections.push({
                warehouse_id: wh.warehouse_id,
                picking_type_id: wh.picking_type_id,
                lot_stock_id: wh.lot_stock_id,
                transit_location_id: wh.transit_location_id,
                partner_id: sel.partner_id || false,
                products,
            });
        }

        if (!warehouseSelections.length) {
            alert('Vui lòng chọn ít nhất 1 kho và 1 sản phẩm.');
            return;
        }

        this.state.isCreatingTransfer = true;
        try {
            const result = await this.orm.call(
                'sale.order',
                'create_transfer_pickings',
                [],
                { warehouse_selections: warehouseSelections }
            );

            const created = result.created || [];
            const errors = result.errors || [];

            if (created.length) {
                const names = created.map(c => c.picking_name).join(', ');
                const msg = `Đã tạo ${created.length} phiếu luân chuyển: ${names}`;
                alert(msg);
                this.closeTransferModal();
                await this.fetchData();
            }

            if (errors.length) {
                const errMsg = errors.map(e => `Kho ${e.warehouse_id}: ${e.error}`).join('\n');
                alert('Lỗi khi tạo phiếu:\n' + errMsg);
            }
        } catch (err) {
            console.error('Lỗi tạo phiếu luân chuyển:', err);
            alert('Lỗi: ' + (err.message || ''));
        } finally {
            this.state.isCreatingTransfer = false;
        }
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
        if (locationName.includes("/OUT") || locationName.includes("Đầu ra")) {
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
            this.state.filterDoneDateFrom ||
            this.state.filterDoneDateTo ||
            this.state.filterPODateFrom ||
            this.state.filterPODateTo ||
            this.state.filterPOStatus !== "all" ||
            this.state.filterPackingStatus !== "all" ||
            this.state.filterSalerCode ||
            this.state.filterHtgh ||
            this.state.filterDeliveryType !== "all" ||
            this.state.filterTagIds.length > 0 ||
            this.state.showCompleted;
    }

    saveHtghPreset() {
        const val = this.state.filterHtgh.trim();
        if (!val) return;
        const label = prompt('Tên gợi ý:', val.slice(0, 30));
        if (!label) return;
        this.state.htghPresets = [...this.state.htghPresets, { label, value: val }];
        localStorage.setItem('hlv_htgh_presets', JSON.stringify(this.state.htghPresets));
    }

    removeHtghPreset(idx) {
        this.state.htghPresets = this.state.htghPresets.filter((_, i) => i !== idx);
        localStorage.setItem('hlv_htgh_presets', JSON.stringify(this.state.htghPresets));
    }

    countTransferWarehouses(so) {
        if (!so.transfer_suggestions) return 0;
        const whIds = {};
        so.transfer_suggestions.forEach(s => (s.sources || []).forEach(src => { whIds[src.from_warehouse_id] = 1; }));
        return Object.keys(whIds).length;
    }

    resetFilters() {
        this.state.searchQuery = "";
        this.state.filterWarehouseId = "all";
        this.state.filterDeliveryStatus = "all";
        this.state.filterStockStatus = "all";
        this.state.filterDateFrom = "";
        this.state.filterDateTo = null;
        this.state.filterDoneDateFrom = "";
        this.state.filterDoneDateTo = "";
        this.state.filterPODateFrom = null;
        this.state.filterPODateTo = null;
        this.state.filterPOStatus = "all";
        this.state.filterPackingStatus = "all";
        this.state.filterSalerCode = "";
        this.state.filterHtgh = "";
        this.state.filterDeliveryType = "all";
        this.state.filterTagIds = [];
        this.state.filterNeedTransfer = false;
        this.state.filterNewOrders = false;
        this.state.showCompleted = false;
        this.state.currentPage = 1;
        this.fetchData();
    }

    exportExcel() {
        const params = new URLSearchParams({
            search_query: this.state.searchQuery.trim(),
            filter_warehouse_id: this.state.filterWarehouseId,
            filter_delivery_status: this.state.filterDeliveryStatus,
            filter_stock_status: this.state.filterStockStatus,
            filter_packing_status: this.state.filterPackingStatus,
            filter_date_from: this.state.filterDateFrom || '',
            filter_date_to: this.state.filterDateTo || '',
            filter_done_date_from: this.state.filterDoneDateFrom || '',
            filter_done_date_to: this.state.filterDoneDateTo || '',
            filter_po_date_from: this.state.filterPODateFrom || '',
            filter_po_date_to: this.state.filterPODateTo || '',
            filter_po_status: this.state.filterPOStatus,
            filter_saler_code: this.state.filterSalerCode.trim(),
            filter_htgh: this.state.filterHtgh.trim(),
            filter_delivery_type: this.state.filterDeliveryType,
            filter_tag_ids: this.state.filterTagIds.join(','),
            show_completed: this.state.showCompleted ? '1' : '',
        });

        const selectedIds = Array.from(this.state.selectedSOIds);
        if (selectedIds.length > 0) {
            params.set('selected_ids', selectedIds.join(','));
        }

        window.open(`/hlv_sale_delivery_planning/export_excel?${params.toString()}`, '_blank');
    }

    // ── Relocation Modal (Chuyển vị trí) ────────────────────────────────

    async openRelocationModal() {
        if (this.selectedCount === 0) {
            alert('Vui lòng chọn ít nhất 1 đơn hàng.');
            return;
        }
        this.state.isRelocationModalOpen = true;
        this.state.relocationModalLoading = true;
        this.state.relocationModalData = null;
        this.state.relocationOrderSelections = {};
        this.state.relocationSaveDefault = false;

        try {
            const selectedIds = Array.from(this.state.selectedSOIds);

            // Giữ hàng (reserve) trước khi lấy dữ liệu chuyển vị trí — giống luồng in phiếu
            try {
                const reserveResponse = await fetch('/hlv_sale_delivery_planning/reserve_stock', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest',
                    },
                    body: JSON.stringify({
                        jsonrpc: '2.0',
                        method: 'call',
                        params: { sale_order_ids: selectedIds },
                    }),
                });
                const reserveResult = await reserveResponse.json();
                if (reserveResult.result) {
                    console.log('Giữ hàng trước chuyển vị trí:', reserveResult.result.message);
                }
            } catch (reserveErr) {
                console.warn('Giữ hàng thất bại, tiếp tục:', reserveErr);
            }
            const data = await this.orm.call(
                'sale.order',
                'prepare_relocation_data',
                [],
                { sale_order_ids: selectedIds }
            );
            this.state.relocationModalData = data;
            this.state.relocationDestLocationId = data.default_dest_location_id || null;

            // Init selections cho mỗi đơn
            const selections = {};
            for (const order of (data.orders || [])) {
                const prodSel = {};
                for (const prod of (order.products || [])) {
                    prodSel[prod.product_id] = { include: true, qty: prod.pending_qty };
                }
                selections[order.sale_order_id] = {
                    selected: true,
                    products: prodSel,
                };
            }
            this.state.relocationOrderSelections = selections;
        } catch (err) {
            console.error('Lỗi khi tải dữ liệu chuyển vị trí:', err);
            alert('Lỗi: ' + (err.message || ''));
            this.state.isRelocationModalOpen = false;
        } finally {
            this.state.relocationModalLoading = false;
        }
    }

    closeRelocationModal() {
        this.state.isRelocationModalOpen = false;
        this.state.relocationModalData = null;
        this.state.relocationOrderSelections = {};
    }

    toggleRelocationOrder(soId, checked) {
        if (!this.state.relocationOrderSelections[soId]) return;
        this.state.relocationOrderSelections[soId].selected = checked;
        this.state.relocationOrderSelections = { ...this.state.relocationOrderSelections };
    }

    getRelocationProductSel(soId, productId) {
        const oSel = this.state.relocationOrderSelections[soId];
        if (!oSel || !oSel.products) return null;
        return oSel.products[productId] || null;
    }

    toggleRelocationProduct(soId, productId, checked) {
        const oSel = this.state.relocationOrderSelections[soId];
        if (!oSel || !oSel.products[productId]) return;
        oSel.products[productId].include = checked;
        this.state.relocationOrderSelections = { ...this.state.relocationOrderSelections };
    }

    setRelocationProductQty(soId, productId, qty) {
        const oSel = this.state.relocationOrderSelections[soId];
        if (!oSel || !oSel.products[productId]) return;
        oSel.products[productId].qty = parseFloat(qty) || 0;
    }

    async confirmCreateRelocationPickings() {
        const destLocId = parseInt(this.state.relocationDestLocationId);
        if (!destLocId) {
            alert('Vui lòng chọn vị trí đích.');
            return;
        }

        const orders = [];
        for (const order of (this.state.relocationModalData?.orders || [])) {
            const oSel = this.state.relocationOrderSelections[order.sale_order_id];
            if (!oSel || !oSel.selected) continue;

            const products = (order.products || [])
                .filter(p => {
                    const ps = oSel.products[p.product_id];
                    return ps && ps.include && ps.qty > 0;
                })
                .map(p => ({
                    product_id: p.product_id,
                    qty: oSel.products[p.product_id].qty,
                }));

            if (!products.length) continue;
            orders.push({
                sale_order_id: order.sale_order_id,
                products,
            });
        }

        if (!orders.length) {
            alert('Vui lòng chọn ít nhất 1 đơn hàng và sản phẩm.');
            return;
        }

        this.state.isCreatingRelocation = true;
        try {
            const result = await this.orm.call(
                'sale.order',
                'create_relocation_pickings',
                [],
                {
                    relocation_data: {
                        dest_location_id: destLocId,
                        save_as_default: this.state.relocationSaveDefault,
                        orders,
                    },
                }
            );

            const created = result.created || [];
            const errors = result.errors || [];

            if (created.length) {
                const names = created.map(c => `${c.sale_order_name}: ${c.picking_name}`).join('\n');
                alert(`Đã tạo ${created.length} phiếu chuyển vị trí:\n${names}`);
                // Mở PDF phiếu chuyển vị trí (nếu có)
                if (result.pdf_url) {
                    window.open(result.pdf_url, '_blank');
                }
                this.closeRelocationModal();
                await this.fetchData();
            }

            if (errors.length) {
                const errMsg = errors.map(e => e.error).join('\n');
                alert('Lỗi:\n' + errMsg);
            }
        } catch (err) {
            console.error('Lỗi tạo phiếu chuyển vị trí:', err);
            alert('Lỗi: ' + (err.message || ''));
        } finally {
            this.state.isCreatingRelocation = false;
        }
    }
}

registry.category("actions").add("hlv_sale_delivery_planning.dashboard", DeliveryPlannerDashboard);

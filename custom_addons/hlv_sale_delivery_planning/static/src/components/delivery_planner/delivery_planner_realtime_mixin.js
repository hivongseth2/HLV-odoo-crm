/** @odoo-module **/
// Purpose: Delivery planner mixin for bus notifications, polling, and subset refresh.

export class DeliveryPlannerRealtimeMixin {
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
}

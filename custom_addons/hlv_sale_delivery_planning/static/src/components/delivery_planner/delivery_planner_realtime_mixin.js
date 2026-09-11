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

            if (!isInitial) {
                for (const notification of notifications.filter((n) => !n.is_read)) {
                    const orderId = notification.sale_order_id ? notification.sale_order_id[0] : false;
                    if (!orderId) {
                        continue;
                    }
                    const prev = prevByOrderId.get(orderId);
                    if (!prev || prev._isRead) {
                        const so = this.state.saleOrders.find(o => o.id === orderId);
                        if (so) so.has_unread_message = true;
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

    openMessageDrawer() {
        this.state.isMessageDrawerOpen = true;
        // Danh sách alias cho bộ lọc — nạp 1 lần, dùng chung với ô soạn tin của drawer đơn.
        if (!(this.state.drawerMentionAliases || []).length) {
            this.loadDrawerMentionAliases();
        }
    }

    closeMessageDrawer() {
        this.state.isMessageDrawerOpen = false;
    }

    /**
     * Bỏ dấu tiếng Việt để gõ không dấu vẫn tìm được ("nhan" khớp "Nhàn").
     */
    _searchNormalize(value) {
        return String(value || '')
            .toLowerCase()
            .normalize('NFD')
            .replace(/\p{Diacritic}/gu, '')
            .replace(/đ/g, 'd')
            .replace(/\s+/g, ' ')
            .trim();
    }

    /**
     * Regex nhận diện @alias — giữ đúng luật của backend
     * (_extract_configured_mentions trong services/delivery_planner_messages.py):
     * alias phải đứng sau đầu dòng/khoảng trắng và kết thúc bằng ranh giới.
     * Alias có thể chứa khoảng trắng ("nhàn bc") nên không dùng \b được.
     */
    _mentionRegexFor(alias) {
        if (!this._mentionRegexCache) this._mentionRegexCache = new Map();
        let regex = this._mentionRegexCache.get(alias);
        if (!regex) {
            const escaped = alias.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
            regex = new RegExp('(^|\\s)@' + escaped + '(?=$|[\\s,;:!?()\\[\\]{}<>])', 'i');
            this._mentionRegexCache.set(alias, regex);
        }
        return regex;
    }

    /**
     * Các alias được nhắc trong 1 đoạn text (preview tin nhắn).
     * Cache theo nội dung text vì mỗi lần poll lại tạo object item mới.
     */
    _mentionsInText(text) {
        const key = String(text || '');
        if (!key) return [];
        if (!this._mentionsTextCache) this._mentionsTextCache = new Map();
        const cached = this._mentionsTextCache.get(key);
        if (cached) return cached;

        const found = [];
        for (const row of this.state.drawerMentionAliases || []) {
            const alias = this._normalizeMentionAlias(row.alias || row.display_alias);
            if (!alias || found.some((f) => f.alias === alias)) continue;
            if (this._mentionRegexFor(alias).test(key)) {
                found.push({
                    alias,
                    display_alias: row.display_alias || row.alias || alias,
                    user_name: row.user_name || '',
                });
            }
        }
        if (this._mentionsTextCache.size > 500) this._mentionsTextCache.clear();
        this._mentionsTextCache.set(key, found);
        return found;
    }

    /**
     * Alias đang thực sự xuất hiện trong danh sách tin nhắn, kèm số tin của từng alias.
     * Alias đang chọn luôn được giữ lại (kể cả còn 0 tin) để người dùng bỏ chọn được.
     */
    get messageDrawerAliasOptions() {
        const counts = new Map();
        for (const item of this.state.globalUnreadOrders || []) {
            for (const mention of this._mentionsInText(item._preview)) {
                const row = counts.get(mention.alias) || { ...mention, count: 0 };
                row.count += 1;
                counts.set(mention.alias, row);
            }
        }
        for (const alias of this.state.messageDrawerAliasFilter || []) {
            if (counts.has(alias)) continue;
            const known = (this.state.drawerMentionAliases || []).find(
                (row) => this._normalizeMentionAlias(row.alias) === alias
            );
            counts.set(alias, {
                alias,
                display_alias: (known && known.display_alias) || alias,
                user_name: (known && known.user_name) || '',
                count: 0,
            });
        }
        return [...counts.values()].sort(
            (a, b) => b.count - a.count || a.alias.localeCompare(b.alias)
        );
    }

    get filteredUnreadOrders() {
        let items = this.state.globalUnreadOrders || [];
        const aliases = this.state.messageDrawerAliasFilter || [];
        if (aliases.length) {
            items = items.filter((item) => this._mentionsInText(item._preview)
                .some((mention) => aliases.includes(mention.alias)));
        }
        const term = this._searchNormalize(this.state.messageDrawerSearch);
        if (term) {
            items = items.filter((item) => this._searchNormalize(
                `${item.name || ''} ${item.last_message_author || ''} ${item._preview || ''}`
            ).includes(term));
        }
        return items;
    }

    get messageDrawerHasFilters() {
        return !!(this.state.messageDrawerSearch || '').trim()
            || !!(this.state.messageDrawerAliasFilter || []).length;
    }

    isMessageAliasSelected(alias) {
        return (this.state.messageDrawerAliasFilter || []).includes(alias);
    }

    toggleMessageAliasFilter(alias) {
        const current = this.state.messageDrawerAliasFilter || [];
        this.state.messageDrawerAliasFilter = current.includes(alias)
            ? current.filter((a) => a !== alias)
            : [...current, alias];
    }

    clearMessageDrawerFilters() {
        this.state.messageDrawerSearch = '';
        this.state.messageDrawerAliasFilter = [];
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
        // payload: {so_id, so_name, author_name, body, message_id}
        if (!payload) return;
        if (!this._seenPortalMessageKeys) {
            this._seenPortalMessageKeys = new Map();
        }
        const now = Date.now();
        for (const [key, ts] of this._seenPortalMessageKeys.entries()) {
            if (now - ts > 30000) this._seenPortalMessageKeys.delete(key);
        }
        const messageKey = payload.message_id
            ? `mail:${payload.message_id}`
            : `fallback:${payload.so_id || ''}:${payload.author_name || ''}:${payload.body || ''}`;
        if (this._seenPortalMessageKeys.has(messageKey)) {
            return;
        }
        this._seenPortalMessageKeys.set(messageKey, now);

        // Cập nhật danh sách drawer realtime: có tin mới thì đưa lên đầu và bật trạng thái chưa đọc.
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

        const so = this.state.saleOrders.find(o => o.id === payload.so_id);
        if (so) {
            so.has_unread_message = true;
        }
    }

    _browserNotificationsSupported() {
        return typeof window !== "undefined" && "Notification" in window && "serviceWorker" in navigator && "PushManager" in window && window.isSecureContext;
    }

    _urlBase64ToUint8Array(base64String) {
        const padding = "=".repeat((4 - base64String.length % 4) % 4);
        const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
        const rawData = window.atob(base64);
        const output = new Uint8Array(rawData.length);
        for (let i = 0; i < rawData.length; ++i) output[i] = rawData.charCodeAt(i);
        return output;
    }

    async _subscribeWebPush(publicKey, forceReset = false) {
        const appKey = this._urlBase64ToUint8Array(publicKey);
        if (appKey.length !== 65) {
            throw new Error(`invalid_vapid_public_key_${appKey.length}`);
        }
        const reg = await navigator.serviceWorker.register('/sale_plan_webpush_sw.js', { scope: '/' });
        await navigator.serviceWorker.ready;
        let sub = await reg.pushManager.getSubscription();
        if (sub && forceReset) {
            await sub.unsubscribe();
            sub = null;
        }
        return sub || await reg.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: appKey,
        });
    }

    _syncDesktopNotificationPermission() {
        this.state.desktopNotificationPermission = this._browserNotificationsSupported() ? Notification.permission : "unsupported";
    }

    async requestDesktopNotifications() {
        if (!this._browserNotificationsSupported()) {
            this.state.desktopNotificationPermission = "unsupported";
            this.notification.add("Trình duyệt không hỗ trợ Web Push hoặc trang chưa chạy HTTPS. Chrome, Edge và Opera bản chính thức đều hỗ trợ.", { type: "warning" });
            return;
        }
        if (Notification.permission === "denied") {
            this.state.desktopNotificationPermission = "denied";
            this.notification.add("Notification đang bị chặn. Bấm icon ổ khóa bên trái URL -> Site settings -> Notifications -> Allow, rồi reload trang.", { type: "warning" });
            return;
        }
        try {
            const configResp = await fetch('/api/sale_plan/webpush_config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ jsonrpc: '2.0', method: 'call', params: {} }),
            });
            const configJson = await configResp.json();
            const config = configJson.result || {};
            if (!config.enabled || !config.public_key) {
                this.notification.add("Web Push chưa cấu hình được VAPID key.", { type: "warning" });
                return;
            }
            const permission = Notification.permission === "granted" ? "granted" : await Notification.requestPermission();
            this.state.desktopNotificationPermission = permission;
            if (permission !== "granted") {
                this.notification.add(permission === "denied" ? "Notification đang bị chặn. Bật lại trong site settings của trình duyệt." : "Chưa bật thông báo trình duyệt", { type: "warning" });
                return;
            }
            let sub;
            try {
                sub = await this._subscribeWebPush(config.public_key, false);
            } catch (firstErr) {
                console.warn('web push first subscribe failed, retrying clean', firstErr);
                sub = await this._subscribeWebPush(config.public_key, true);
            }
            await fetch('/api/sale_plan/webpush_subscribe', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    jsonrpc: '2.0',
                    method: 'call',
                    params: { subscription: sub.toJSON(), backend_messages: true },
                }),
            });
            this.notification.add("Đã bật Web Push", { type: "success" });
        } catch (e) {
            console.warn('web push subscribe failed', e);
            const message = e && e.name === "AbortError"
                ? "Khong ket noi duoc push service cua trinh duyet. Thu Chrome/Edge khac, tat VPN/proxy/adblock, hoac kiem tra quyen notification cua site."
                : `Khong bat duoc Web Push${e && e.message ? `: ${e.message}` : ""}`;
            this.notification.add(message, { type: "warning" });
        }
    }

    // --- Real-time data refresh via bus ---
    _dataChangedDebounce = null;
    _pendingChangedSoIds = null;
    _pendingFallbackFull = false;

    _onDataChanged(payload) {
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
            } else {
                // Fallback: full silent refresh (filters may have caused new matches)
                await this._silentRefresh();
            }
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

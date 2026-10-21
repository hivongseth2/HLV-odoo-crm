/** @odoo-module **/
// Purpose: Bộ lọc của drawer "Tin nhắn mới từ saler" — từ khoá, alias được nhắc,
// thời gian, chỉ chưa đọc — và tìm tin nhắn dưới backend (search_plan_messages).

// Lựa chọn "Thời gian". Quy đổi ra ngày nằm ở backend (message_period_utils.py)
// để drawer này và trang /sale_plan hiểu "7 ngày qua" giống nhau.
const MESSAGE_PERIOD_OPTIONS = [
    { value: '', label: 'Mọi lúc' },
    { value: 'today', label: 'Hôm nay' },
    { value: 'yesterday', label: 'Hôm qua' },
    { value: '7d', label: '7 ngày qua' },
    { value: '30d', label: '30 ngày qua' },
    { value: 'custom', label: 'Chọn ngày...' },
];

export class DeliveryPlannerMessageSearchMixin {
    get messageDrawerPeriodOptions() {
        return MESSAGE_PERIOD_OPTIONS;
    }

    /**
     * Alias = TOÀN BỘ alias đã cấu hình, vì chọn alias là tìm dưới backend trên
     * mọi tin nhắn chứ không lọc trong danh sách 100 tin đã nạp.
     */
    get messageDrawerAliasOptions() {
        const selected = this.state.messageDrawerAliasFilter || [];
        const rows = (this.state.drawerMentionAliases || []).map((row) => ({
            alias: this._normalizeMentionAlias(row.alias || row.display_alias),
            display_alias: row.display_alias || row.alias || '',
            user_name: row.user_name || '',
        })).filter((row) => row.alias);
        for (const alias of selected) {
            if (!rows.some((row) => row.alias === alias)) {
                rows.push({ alias, display_alias: alias, user_name: '' });
            }
        }
        return rows.sort((a, b) => a.alias.localeCompare(b.alias));
    }

    /** Alias đang chọn — hiện thành chip có nút bỏ, dưới dropdown. */
    get selectedMessageAliases() {
        const selected = this.state.messageDrawerAliasFilter || [];
        return this.messageDrawerAliasOptions.filter((row) => selected.includes(row.alias));
    }

    /**
     * Tham số thời gian gửi backend. "Chọn ngày..." mà chưa gõ ngày nào thì coi
     * như chưa lọc — tránh bật chế độ tìm với một bộ lọc rỗng.
     */
    _messageDrawerPeriodParams() {
        const period = this.state.messageDrawerPeriod || '';
        const dateFrom = this.state.messageDrawerDateFrom || '';
        const dateTo = this.state.messageDrawerDateTo || '';
        if (period === 'custom' && !dateFrom && !dateTo) {
            return { period: '', date_from: '', date_to: '' };
        }
        return {
            period,
            date_from: period === 'custom' ? dateFrom : '',
            date_to: period === 'custom' ? dateTo : '',
        };
    }

    /**
     * Có từ khoá / alias / thời gian → chuyển sang danh sách kết quả từ backend.
     * Riêng "chỉ chưa đọc" thì lọc ngay trên danh sách mặc định (đã có sẵn cờ đọc),
     * khỏi phải gọi server.
     */
    get messageDrawerServerMode() {
        return !!(this.state.messageDrawerSearch || '').trim()
            || !!(this.state.messageDrawerAliasFilter || []).length
            || !!this._messageDrawerPeriodParams().period;
    }

    get messageDrawerHasFilters() {
        return this.messageDrawerServerMode || !!this.state.messageDrawerUnreadOnly;
    }

    /** Danh sách mặc định (tin cuối mỗi đơn) sau khi áp bộ lọc "chỉ chưa đọc". */
    get visibleUnreadOrders() {
        const items = this.state.globalUnreadOrders || [];
        return this.state.messageDrawerUnreadOnly ? items.filter((o) => !o._isRead) : items;
    }

    isMessageAliasSelected(alias) {
        return (this.state.messageDrawerAliasFilter || []).includes(alias);
    }

    toggleMessageUnreadOnly() {
        this.state.messageDrawerUnreadOnly = !this.state.messageDrawerUnreadOnly;
        if (this.messageDrawerServerMode) {
            this.runMessageSearch(true);
        }
    }

    onMessageDrawerSearchInput(ev) {
        this.state.messageDrawerSearch = ev.target.value;
        if (this._messageSearchDebounce) clearTimeout(this._messageSearchDebounce);
        this._messageSearchDebounce = setTimeout(() => {
            this._messageSearchDebounce = null;
            this.runMessageSearch(true);
        }, 400);
    }

    toggleMessageAliasFilter(alias) {
        const current = this.state.messageDrawerAliasFilter || [];
        this.state.messageDrawerAliasFilter = current.includes(alias)
            ? current.filter((a) => a !== alias)
            : [...current, alias];
        this.runMessageSearch(true);
    }

    /** Dropdown alias: chọn 1 dòng là thêm/bỏ alias đó, rồi trả dropdown về ô trống. */
    onMessageAliasSelect(ev) {
        const alias = ev.target.value;
        ev.target.value = '';
        if (alias) this.toggleMessageAliasFilter(alias);
    }

    onMessagePeriodChange(ev) {
        this.state.messageDrawerPeriod = ev.target.value;
        if (this.state.messageDrawerPeriod !== 'custom') {
            this.state.messageDrawerDateFrom = '';
            this.state.messageDrawerDateTo = '';
        }
        this.runMessageSearch(true);
    }

    onMessageDateChange(field, ev) {
        this.state[field] = ev.target.value || '';
        this.runMessageSearch(true);
    }

    /** Nút "x" trong ô tìm: chỉ xoá từ khoá, giữ nguyên các bộ lọc khác. */
    clearMessageDrawerSearchText() {
        if (this._messageSearchDebounce) clearTimeout(this._messageSearchDebounce);
        this._messageSearchDebounce = null;
        this.state.messageDrawerSearch = '';
        this.runMessageSearch(true);
    }

    clearMessageDrawerFilters() {
        if (this._messageSearchDebounce) clearTimeout(this._messageSearchDebounce);
        this._messageSearchDebounce = null;
        this.state.messageDrawerSearch = '';
        this.state.messageDrawerAliasFilter = [];
        this.state.messageDrawerUnreadOnly = false;
        this.state.messageDrawerPeriod = '';
        this.state.messageDrawerDateFrom = '';
        this.state.messageDrawerDateTo = '';
        this.state.messageSearchResults = [];
        this.state.messageSearchHasMore = false;
        this.state.messageSearchLoading = false;
        this.state.messageSearchOffset = 0;
    }

    /**
     * Tìm tin nhắn dưới backend (search_plan_messages): quét từng mail.message của
     * đơn bán nên ra được cả tin cũ trong một đơn, không chỉ tin cuối như polling.
     * reset = true: tìm lại từ đầu; false: nối thêm trang kế (nút "Tải thêm").
     */
    async runMessageSearch(reset = true) {
        const search = (this.state.messageDrawerSearch || '').trim();
        const aliases = [...(this.state.messageDrawerAliasFilter || [])];
        const periodParams = this._messageDrawerPeriodParams();
        if (!search && !aliases.length && !periodParams.period) {
            this.state.messageSearchResults = [];
            this.state.messageSearchHasMore = false;
            this.state.messageSearchLoading = false;
            this.state.messageSearchOffset = 0;
            return;
        }

        // Chống race: chỉ nhận kết quả của lần tìm mới nhất.
        this._messageSearchSeq = (this._messageSearchSeq || 0) + 1;
        const seq = this._messageSearchSeq;
        // Offset do backend trả về (đếm theo dòng đã quét, không phải số dòng hiển thị).
        const offset = reset ? 0 : (this.state.messageSearchOffset || 0);
        this.state.messageSearchLoading = true;
        try {
            const result = await this.orm.call(
                'hlv.delivery.planner.service', 'search_plan_messages', [],
                {
                    search,
                    aliases,
                    limit: this.state.messageSearchLimit || 50,
                    offset,
                    unread_only: !!this.state.messageDrawerUnreadOnly,
                    ...periodParams,
                }
            );
            if (seq !== this._messageSearchSeq) return;
            const rows = (result && result.messages) || [];
            if (!rows.length && result && result.scanned) {
                // Backend quét được dòng nhưng không giữ lại tin nào — in số liệu ra
                // console để soi nhanh thay vì phải mò log server.
                console.debug('searchPlanMessages: không giữ lại tin nào', result);
            }
            this.state.messageSearchResults = reset
                ? rows
                : [...(this.state.messageSearchResults || []), ...rows];
            this.state.messageSearchHasMore = !!(result && result.has_more);
            this.state.messageSearchOffset = (result && result.next_offset) || 0;
        } catch (e) {
            if (seq !== this._messageSearchSeq) return;
            console.error('searchPlanMessages error', e);
            this.notification.add('Không tìm được tin nhắn.', { type: 'danger' });
            if (reset) this.state.messageSearchResults = [];
            this.state.messageSearchHasMore = false;
        } finally {
            if (seq === this._messageSearchSeq) {
                this.state.messageSearchLoading = false;
            }
        }
    }

    async loadMoreMessageSearch() {
        if (this.state.messageSearchLoading || !this.state.messageSearchHasMore) return;
        await this.runMessageSearch(false);
    }

    /** Mô tả bộ lọc thời gian cho hộp xác nhận, VD "7 ngày qua" hoặc "01/10 → 15/10". */
    _messageDrawerPeriodLabel(periodParams) {
        if (periodParams.period !== 'custom') {
            const option = MESSAGE_PERIOD_OPTIONS.find((o) => o.value === periodParams.period);
            return option ? option.label.toLowerCase() : '';
        }
        const fmt = (value) => (value ? value.split('-').reverse().join('/') : '…');
        return `${fmt(periodParams.date_from)} → ${fmt(periodParams.date_to)}`;
    }

    /**
     * Đánh dấu đã đọc mọi đơn có tin khớp bộ lọc hiện tại — kể cả tin chưa kéo
     * về màn hình (backend dùng lại đúng domain của ô tìm kiếm / alias / thời gian).
     * Trạng thái đã đọc lưu theo ĐƠN nên đây là đánh dấu cả đơn, không phải từng tin.
     */
    async markFilteredMessagesRead() {
        const search = (this.state.messageDrawerSearch || '').trim();
        const aliases = [...(this.state.messageDrawerAliasFilter || [])];
        const unreadOnly = !!this.state.messageDrawerUnreadOnly;
        const periodParams = this._messageDrawerPeriodParams();
        if ((!search && !aliases.length && !unreadOnly && !periodParams.period)
            || this.state.messageMarkingRead) return;

        const parts = [];
        if (aliases.length) parts.push(`alias ${aliases.map((a) => '@' + a).join(', ')}`);
        if (search) parts.push(`từ khoá "${search}"`);
        if (periodParams.period) parts.push(`thời gian ${this._messageDrawerPeriodLabel(periodParams)}`);
        const what = parts.length
            ? `khớp ${parts.join(' + ')}`
            : 'chưa đọc (toàn bộ, không lọc alias/từ khoá/thời gian)';
        if (!window.confirm(`Đánh dấu ĐÃ ĐỌC tất cả đơn có tin nhắn ${what}?\nGồm cả tin chưa hiện trên màn hình.`)) {
            return;
        }

        this.state.messageMarkingRead = true;
        try {
            const res = await this.orm.call(
                'hlv.delivery.planner.service', 'mark_plan_messages_read', [],
                { search, aliases, unread_only: unreadOnly, ...periodParams }
            );
            const markedIds = new Set((res && res.sale_order_ids) || []);
            this.state.globalUnreadOrders = this.state.globalUnreadOrders.map((o) => {
                const soId = o.sale_order_id ? o.sale_order_id[0] : o.id;
                return markedIds.has(soId) ? { ...o, _isRead: true } : o;
            });
            this.state.messageSearchResults = (this.state.messageSearchResults || []).map(
                (msg) => markedIds.has(msg.sale_order_id) ? { ...msg, is_read: true } : msg
            );
            for (const so of this.state.saleOrders) {
                if (markedIds.has(so.id)) so.has_unread_message = false;
            }
            const marked = (res && res.marked) || 0;
            this.notification.add(
                marked ? `Đã đánh dấu đã đọc ${marked} đơn.` : 'Không còn đơn chưa đọc nào khớp bộ lọc.',
                { type: marked ? 'success' : 'info' }
            );
            if (res && res.truncated) {
                this.notification.add(
                    'Quá nhiều đơn khớp — mới xử lý phần đầu, bấm lại để chạy tiếp.',
                    { type: 'warning' }
                );
            }
        } catch (e) {
            console.error('markPlanMessagesRead error', e);
            this.notification.add('Không đánh dấu đã đọc được.', { type: 'danger' });
        } finally {
            this.state.messageMarkingRead = false;
        }
    }
}

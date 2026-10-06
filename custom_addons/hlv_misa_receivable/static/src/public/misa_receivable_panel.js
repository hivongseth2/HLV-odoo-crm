/* Tab "Công nợ phải thu" trên trang /misa_sale_status: ô tổng nợ + nhóm quá hạn (bấm để lọc),
 * mỗi hàng 1 hóa đơn còn phần chưa thu, mở ra xem theo dòng đơn bán, tra lại MISA cho riêng hóa
 * đơn đó, sale ghi ngày hẹn thu / xác suất thu / ghi chú.
 * Không tự có rpc/định dạng tiền/toast — dùng chung bản của trang qua window.MsuSaleStatus. */
(function () {
    'use strict';

    var PAGE_SIZE = 50;
    var COLS = 10;
    var msu = window.MsuSaleStatus;
    var state = {search: '', bucket: '', page: 1, total: 0, rows: [], loadedFor: null, editing: null, open: {}};

    function el(id) { return document.getElementById(id); }

    // Màu trạng thái: quá hạn đỏ, đến hạn hôm nay vàng, chưa đến hạn xanh.
    function badgeClass(row) {
        if (row.overdue_days > 0) { return 'msr-badge-overdue'; }
        if (row.overdue_days === 0) { return 'msr-badge-due'; }
        return 'msr-badge-ok';
    }

    function renderSummary(summary) {
        var cards = [
            {key: '', label: 'Tổng còn phải thu', amount: summary.total_amount, count: summary.total_count, cls: 'msr-card-total'},
            {key: 'overdue', label: 'Đã quá hạn', amount: summary.overdue_amount, count: summary.overdue_count, cls: 'msr-card-overdue'},
        ].concat(summary.buckets.map(function (b) {
            return {key: b.key, label: b.label, amount: b.amount, count: b.count, cls: 'msr-card-bucket'};
        }));
        el('msr-summary').innerHTML = cards.map(function (c) {
            var active = state.bucket === c.key ? ' msr-card-active' : '';
            return '<button type="button" class="msr-card ' + c.cls + active + '" data-bucket="' + msu.esc(c.key) + '">' +
                '<span class="msr-card-label">' + msu.esc(c.label) + '</span>' +
                '<span class="msr-card-amount">' + msu.fmtMoney(c.amount) + '</span>' +
                '<span class="msr-card-count">' + c.count + ' hóa đơn</span>' +
                '</button>';
        }).join('');
    }

    function renderFollowup(row) {
        var parts = [];
        if (row.promise_date) { parts.push('<b>' + msu.fmtDate(row.promise_date) + '</b>'); }
        if (row.collect_rate) { parts.push(row.collect_rate + '%'); }
        var head = parts.length ? parts.join(' · ') : '<span class="msu-muted">Chưa hẹn</span>';
        var note = row.followup_note ? '<div class="msr-note">' + msu.esc(row.followup_note) + '</div>' : '';
        return '<button type="button" class="msr-followup-btn" data-invoice="' + msu.esc(row.invoice_no) + '" title="Ghi ngày hẹn thu / xác suất thu">' +
            head + ' <i class="fa fa-pencil"></i></button>' + note;
    }

    function renderDetail(lines) {
        if (!lines) { return '<span class="msu-muted"><i class="fa fa-spinner fa-spin"></i> Đang tải...</span>'; }
        return '<table class="msu-table msu-table-compact"><thead><tr>' +
            '<th>Đơn</th><th>Sản phẩm</th><th>Mã hàng MISA</th><th class="msu-col-num">SL (MISA)</th>' +
            '<th class="msu-col-num">Tiền có VAT</th><th>Chứng từ</th><th>Thu tiền</th></tr></thead><tbody>' +
            lines.map(function (l) {
                var cls = l.paid_state === 'paid' ? 'msr-badge-ok' : (l.paid_state === 'unknown' ? 'msr-badge-muted' : 'msr-badge-overdue');
                return '<tr><td>' + msu.esc(l.order) + '</td>' +
                    '<td>' + msu.esc(l.product) + (l.is_component ? ' <span class="msu-muted" title="Hóa đơn ghi mã sản phẩm con của combo này">(mã con)</span>' : '') + '</td>' +
                    '<td>' + msu.esc(l.item_code) + '</td>' +
                    '<td class="msu-col-num">' + l.quantity + ' ' + msu.esc(l.unit_name) + '</td>' +
                    '<td class="msu-col-num">' + msu.fmtMoney(l.amount) + '</td>' +
                    '<td>' + msu.esc(l.voucher_refno) + '</td>' +
                    '<td><span class="msr-badge ' + cls + '">' + msu.esc(l.paid_label) + '</span></td></tr>';
            }).join('') + '</tbody></table>';
    }

    function renderRow(row, index) {
        var orders = row.orders.length ? '<div class="msu-muted msr-sub">' + msu.esc(row.orders.join(', ')) + '</div>' : '';
        var vouchers = row.voucher_refnos.length ? '<div class="msr-sub">' + msu.esc(row.voucher_refnos.join(', ')) + '</div>' : '';
        var unknown = row.has_unknown
            ? ' <span class="msr-badge msr-badge-muted" title="MISA trả tình trạng thu tiền lạ — kiểm lại trên MISA">Chưa rõ đã thu</span>'
            : '';
        var isOpen = state.open.hasOwnProperty(row.invoice_no);
        var html = '<tr class="' + (row.overdue_days > 0 ? 'msr-row-overdue' : '') + '">' +
            '<td class="msu-col-num">' + ((state.page - 1) * PAGE_SIZE + index + 1) + '</td>' +
            '<td><b>' + msu.esc(row.partner_name) + '</b><div class="msu-muted msr-sub">' + msu.esc(row.partner_code) + '</div></td>' +
            '<td><b>HĐ ' + msu.esc(row.invoice_no) + '</b>' + vouchers + orders + '</td>' +
            '<td>' + msu.fmtDate(row.invoice_date) + '</td>' +
            '<td title="' + msu.esc(row.due_source) + '">' + msu.fmtDate(row.due_date) + '</td>' +
            '<td class="msu-col-num"><b>' + msu.fmtMoney(row.amount) + '</b></td>' +
            '<td><span class="msr-badge ' + badgeClass(row) + '">' + msu.esc(row.status_label) + '</span>' + unknown + '</td>' +
            '<td>' + renderFollowup(row) + '</td>' +
            '<td>' + (row.saler_codes.length ? msu.esc(row.saler_codes.join(', ')) : '<span class="msu-muted">—</span>') + '</td>' +
            '<td class="msr-actions">' +
                '<button type="button" class="msu-btn msu-btn-outline-muted msu-btn-xs msr-detail-btn" data-invoice="' + msu.esc(row.invoice_no) + '" title="Xem theo dòng đơn bán">' +
                    '<i class="fa fa-' + (isOpen ? 'chevron-up' : 'list') + '"></i></button>' +
                '<button type="button" class="msu-btn msu-btn-outline-primary msu-btn-xs msr-recheck-btn" data-invoice="' + msu.esc(row.invoice_no) + '" title="Tra lại MISA ngay cho hóa đơn này">' +
                    '<i class="fa fa-refresh"></i></button>' +
            '</td></tr>';
        if (isOpen) {
            html += '<tr class="msr-detail-row"><td colspan="' + COLS + '">' + renderDetail(state.open[row.invoice_no]) + '</td></tr>';
        }
        return html;
    }

    function renderRows() {
        el('msr-tbody').innerHTML = state.rows.map(renderRow).join('');
        el('msr-empty').style.display = state.rows.length ? 'none' : '';
        var pages = Math.max(1, Math.ceil(state.total / PAGE_SIZE));
        el('msr-pagination').style.display = pages > 1 ? '' : 'none';
        el('msr-page-label').textContent = 'Trang ' + state.page + '/' + pages + ' · ' + state.total + ' hóa đơn';
        el('msr-prev').disabled = state.page <= 1;
        el('msr-next').disabled = state.page >= pages;
    }

    function load(pageNo) {
        var salerCode = msu.getSalerCode();
        if (!salerCode) { return; }
        state.page = pageNo || 1;
        state.loadedFor = salerCode;
        state.open = {};
        el('msr-tbody').innerHTML = '<tr><td colspan="' + COLS + '" class="msu-muted"><i class="fa fa-spinner fa-spin"></i> Đang tải...</td></tr>';
        el('msr-sync-btn').style.display = msu.isAdmin() ? '' : 'none';
        msu.rpc('/misa_sale_status/api/receivable/list', {
            saler_code: salerCode, search: state.search, bucket: state.bucket,
            limit: PAGE_SIZE, offset: (state.page - 1) * PAGE_SIZE,
        }).then(function (res) {
            var data = res.data;
            state.rows = data.rows;
            state.total = data.total;
            el('msr-last-sync').textContent = data.last_scan_at
                ? 'Tra MISA lần cuối lúc ' + data.last_scan_at
                : 'Chưa tra MISA lần nào';
            renderSummary(data.summary);
            renderRows();
        }).catch(function (e) {
            el('msr-tbody').innerHTML = '';
            msu.toast('Lỗi tải công nợ: ' + e.message, 'error');
        });
    }

    function toggleDetail(invoiceNo) {
        if (state.open.hasOwnProperty(invoiceNo)) {
            delete state.open[invoiceNo];
            renderRows();
            return;
        }
        state.open[invoiceNo] = null;
        renderRows();
        msu.rpc('/misa_sale_status/api/receivable/lines', {saler_code: msu.getSalerCode(), invoice_no: invoiceNo}).then(function (res) {
            if (state.open.hasOwnProperty(invoiceNo)) {
                state.open[invoiceNo] = res.data;
                renderRows();
            }
        }).catch(function (e) {
            delete state.open[invoiceNo];
            renderRows();
            msu.toast('Lỗi tải chi tiết: ' + e.message, 'error');
        });
    }

    function recheck(btn) {
        var invoiceNo = btn.dataset.invoice;
        msu.setBtnLoading(btn, true);
        msu.rpc('/misa_sale_status/api/receivable/recheck', {saler_code: msu.getSalerCode(), invoice_no: invoiceNo}).then(function (res) {
            var r = res.data;
            msu.toast('HĐ ' + invoiceNo + ': ' + (r.done ? 'đã thu đủ.' : 'vẫn còn phần chưa thu.') +
                (r.unmatched ? ' ' + r.unmatched + ' dòng chứng từ không gắn được dòng đơn bán.' : ''), 'success');
            load(state.page);
        }).catch(function (e) {
            msu.setBtnLoading(btn, false);
            msu.toast(e.message, 'error');
        });
    }

    function applySearch(value) {
        state.search = value.trim();
        el('msr-search').value = state.search;
        el('msr-search-clear').style.display = state.search ? '' : 'none';
        load(1);
    }

    function openFollowup(invoiceNo) {
        var row = state.rows.find(function (r) { return r.invoice_no === invoiceNo; });
        if (!row) { return; }
        state.editing = row;
        el('msr-followup-target').textContent = 'HĐ ' + row.invoice_no + ' — ' + row.partner_name + ' — ' + msu.fmtMoney(row.amount);
        el('msr-followup-date').value = row.promise_date;
        el('msr-followup-rate').value = row.collect_rate || '';
        el('msr-followup-note').value = row.followup_note;
        el('msr-followup-error').textContent = '';
        el('msr-followup-modal').style.display = '';
    }

    function saveFollowup(btn) {
        var row = state.editing;
        var values = {
            promise_date: el('msr-followup-date').value,
            collect_rate: el('msr-followup-rate').value,
            note: el('msr-followup-note').value.trim(),
        };
        msu.setBtnLoading(btn, true);
        msu.rpc('/misa_sale_status/api/receivable/followup', {
            saler_code: msu.getSalerCode(), invoice_no: row.invoice_no,
            promise_date: values.promise_date, collect_rate: values.collect_rate, note: values.note,
        }).then(function () {
            row.promise_date = values.promise_date;
            row.collect_rate = parseInt(values.collect_rate, 10) || 0;
            row.followup_note = values.note;
            renderRows();
            el('msr-followup-modal').style.display = 'none';
            msu.toast('Đã lưu lịch hẹn thu HĐ ' + row.invoice_no + '.', 'success');
        }).catch(function (e) {
            el('msr-followup-error').textContent = e.message;
        }).finally(function () { msu.setBtnLoading(btn, false); });
    }

    function bindEvents() {
        document.addEventListener('msu:tab-shown', function (ev) {
            if (ev.detail.tab === 'receivable' && state.loadedFor !== msu.getSalerCode()) { load(1); }
        });
        document.addEventListener('msu:saler-chosen', function () {
            if (msu.getActiveTab() === 'receivable') { load(1); }
        });
        el('msr-summary').addEventListener('click', function (ev) {
            var card = ev.target.closest('.msr-card');
            if (!card) { return; }
            state.bucket = card.dataset.bucket;
            load(1);
        });
        el('msr-search-btn').addEventListener('click', function () { applySearch(el('msr-search').value); });
        el('msr-search').addEventListener('keydown', function (ev) {
            if (ev.key === 'Enter') { applySearch(this.value); }
        });
        el('msr-search-clear').addEventListener('click', function () { applySearch(''); });
        el('msr-refresh-btn').addEventListener('click', function () { load(state.page); });
        el('msr-prev').addEventListener('click', function () { load(state.page - 1); });
        el('msr-next').addEventListener('click', function () { load(state.page + 1); });
        el('msr-tbody').addEventListener('click', function (ev) {
            var btn = ev.target.closest('.msr-followup-btn, .msr-detail-btn, .msr-recheck-btn');
            if (!btn) { return; }
            if (btn.classList.contains('msr-followup-btn')) { openFollowup(btn.dataset.invoice); }
            if (btn.classList.contains('msr-detail-btn')) { toggleDetail(btn.dataset.invoice); }
            if (btn.classList.contains('msr-recheck-btn')) { recheck(btn); }
        });
        el('msr-followup-cancel').addEventListener('click', function () { el('msr-followup-modal').style.display = 'none'; });
        el('msr-followup-save').addEventListener('click', function () { saveFollowup(this); });
        el('msr-sync-btn').addEventListener('click', function () {
            var btn = this;
            msu.setBtnLoading(btn, true);
            msu.rpc('/misa_sale_status/api/receivable/sync').then(function () {
                msu.toast('Đã xếp lịch tra thu tiền MISA — vài phút nữa bấm "Làm mới".', 'success');
            }).catch(function (e) {
                msu.toast('Lỗi: ' + e.message, 'error');
            }).finally(function () { msu.setBtnLoading(btn, false); });
        });
    }

    if (msu && el('msu-tab-receivable')) { bindEvents(); }
})();

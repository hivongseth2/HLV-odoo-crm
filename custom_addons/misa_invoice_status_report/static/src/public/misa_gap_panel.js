/* Khung "Vì sao còn lệch" trên trang /misa_sale_status: tách phần "Còn lại chưa xuất HĐ" theo
 * lý do, theo tháng xuất kho, và liệt kê từng phiếu. Không tự có rpc/định dạng tiền/drawer —
 * trang chính truyền vào qua MsuGapPanel.init(deps) để dùng chung đúng 1 bản. */
(function () {
    'use strict';

    var deps = null;
    var filter = {category: '', month: ''};
    var data = null;

    function el(id) { return document.getElementById(id); }

    function signedClass(amount) {
        if (amount > 0) { return 'msu-gap-pos'; }
        if (amount < 0) { return 'msu-gap-neg'; }
        return '';
    }

    function renderCategories() {
        return '<div class="msu-gap-cats">' + data.categories.map(function (cat) {
            var active = filter.category === cat.key ? ' msu-gap-active' : '';
            var muted = cat.counted ? '' : ' msu-gap-muted';
            var clickable = cat.key === 'customs' || cat.key === 'rounding' ? '' : ' msu-gap-clickable';
            return '<div class="msu-gap-cat' + active + muted + clickable + '" data-cat="' + deps.esc(cat.key) + '">' +
                '<div class="msu-gap-cat-head"><b>' + deps.esc(cat.label) + '</b>' +
                (cat.count ? '<span class="msu-muted">' + cat.count + (cat.key === 'customs' ? ' dòng' : ' phiếu') + '</span>' : '') +
                '</div>' +
                '<div class="msu-gap-cat-amount ' + (cat.counted ? signedClass(cat.amount) : '') + '">' +
                (cat.counted ? '' : '(không tính) ') + deps.fmtMoney(cat.amount) + '</div>' +
                '<div class="msu-gap-cat-hint">' + deps.esc(cat.hint) + '</div>' +
                '<div class="msu-gap-cat-action"><i class="fa fa-hand-o-right"></i> ' + deps.esc(cat.action) + '</div>' +
                '</div>';
        }).join('') + '</div>';
    }

    function categoryLabel() {
        var cat = data.categories.find(function (c) { return c.key === filter.category; });
        return cat ? cat.label : '';
    }

    function monthLabel() {
        var m = data.months.find(function (x) { return x.key === filter.month; });
        // Tháng đang chọn có thể không còn chip khi đổi sang nhóm không có phiếu nào trong tháng đó.
        return m ? m.label : filter.month.slice(5, 7) + '/' + filter.month.slice(0, 4);
    }

    function renderMonths() {
        if (!data.months.length) { return ''; }
        var scope = filter.category ? ' — nhóm "' + deps.esc(categoryLabel()) + '"' : ' — các phiếu cần xử lý';
        return '<div class="msu-gap-section-title">Theo tháng xuất kho' + scope + '</div><div class="msu-gap-months">' +
            data.months.map(function (m) {
                var active = filter.month === m.key ? ' msu-gap-active' : '';
                return '<button class="msu-gap-month' + active + '" data-month="' + deps.esc(m.key) + '">' +
                    '<span>' + deps.esc(m.label) + '</span>' +
                    '<b class="' + signedClass(m.amount) + '">' + deps.fmtMoney(m.amount) + '</b>' +
                    '<span class="msu-muted">' + m.count + ' phiếu</span></button>';
            }).join('') + '</div>';
    }

    function renderRowNote(row) {
        var notes = [];
        (row.order_notes || []).forEach(function (o) {
            notes.push('Theo MISA, đơn ' + deps.esc(o.order) + ' đã xuất HĐ ' + deps.fmtMoney(o.invoiced) + ' qua đề nghị' +
                (o.customs ? ' + ' + deps.fmtMoney(o.customs) + ' HĐ hải quan' : '') +
                (o.pending ? ' (còn ' + deps.fmtMoney(o.pending) + ' đề nghị chưa phát hành)' : '') +
                (o.sources ? ': ' + deps.esc(o.sources.split('\n').join('; ')) : ''));
        });
        if (!row.order_based && row.group_picking_names && row.group_picking_names.length > 1) {
            notes.push('Đề nghị gộp ' + row.group_picking_names.length + ' phiếu (' + deps.esc(row.group_picking_names.join(', ')) +
                ') — HĐ của đề nghị ' + deps.fmtMoney(row.request_invoice_amount) + ', đã chia ' +
                deps.fmtMoney(row.passed_to_others_amount) + ' cho các phiếu đi kèm.');
        }
        if (row.exception) { notes.push('Đang đánh dấu ngoại lệ: ' + deps.esc(row.exception_reason)); }
        if (row.gap_summary) { notes.push(deps.esc(row.gap_summary)); }
        return notes.map(function (n) { return '<div class="msu-gap-note">' + n + '</div>'; }).join('');
    }

    function renderRows() {
        var parts = [];
        if (filter.category) { parts.push('nhóm "' + deps.esc(categoryLabel()) + '"'); }
        if (filter.month) { parts.push('tháng ' + deps.esc(monthLabel())); }
        var title = 'Phiếu đang lệch' + (parts.length ? ' — ' + parts.join(', ') : '') +
            ': ' + data.row_total + ' phiếu' + (data.rows.length < data.row_total ? ', hiện ' + data.rows.length + ' phiếu lệch nhiều nhất' : '');
        var clear = filter.category || filter.month ? ' <button class="msu-btn msu-btn-outline-muted msu-btn-sm" id="msu-gap-clear">Bỏ lọc</button>' : '';
        if (!data.rows.length) {
            return '<div class="msu-gap-section-title">' + title + clear + '</div><div class="msu-muted">Không có phiếu nào.</div>';
        }
        return '<div class="msu-gap-section-title">' + title + clear + '</div>' +
            '<table class="msu-table"><thead><tr>' +
            '<th>Phiếu</th><th>Ngày xuất kho</th><th>Lý do</th>' +
            '<th class="msu-col-num">Tiền xuất kho</th><th class="msu-col-num">Tiền HĐ của phiếu</th><th class="msu-col-num">Lệch</th>' +
            '</tr></thead><tbody>' +
            data.rows.map(function (row, idx) {
                return '<tr class="msu-gap-row" data-idx="' + idx + '">' +
                    '<td><b>' + deps.esc(row.name) + '</b><div class="msu-muted">' + deps.esc(row.partner_name || '') +
                    (row.sale_order_name ? ' · ' + deps.esc(row.sale_order_name) : '') + '</div>' + renderRowNote(row) + '</td>' +
                    '<td>' + deps.esc(deps.fmtDate(row.date_done)) + '</td>' +
                    '<td>' + deps.esc(row.category_label) + '</td>' +
                    '<td class="msu-col-num">' + deps.fmtMoney(row.actual_amount) + '</td>' +
                    '<td class="msu-col-num">' + deps.fmtMoney(row.allocated_amount) + '</td>' +
                    '<td class="msu-col-num ' + (row.gap_resolved ? '' : signedClass(row.diff)) + '"><b>' + deps.fmtMoney(row.diff) + '</b></td>' +
                    '</tr>';
            }).join('') + '</tbody></table>';
    }

    function render() {
        var body = el('msu-gap-body');
        el('msu-gap-total').textContent = deps.fmtMoney(data.outstanding_amount);
        body.innerHTML = renderCategories() + renderMonths() + renderRows();
        body.querySelectorAll('.msu-gap-cat.msu-gap-clickable').forEach(function (node) {
            node.addEventListener('click', function () {
                filter.category = filter.category === node.dataset.cat ? '' : node.dataset.cat;
                load();
            });
        });
        body.querySelectorAll('.msu-gap-month').forEach(function (node) {
            node.addEventListener('click', function () {
                filter.month = filter.month === node.dataset.month ? '' : node.dataset.month;
                load();
            });
        });
        var clearBtn = el('msu-gap-clear');
        if (clearBtn) {
            clearBtn.addEventListener('click', function () { filter = {category: '', month: ''}; load(); });
        }
        body.querySelectorAll('.msu-gap-row').forEach(function (node) {
            node.addEventListener('click', function () {
                var row = data.rows[Number(node.dataset.idx)];
                close();
                if (row.source === 'shopee') { deps.openShopeeTab(row.name); } else { deps.openPicking(row.id); }
            });
        });
    }

    function load() {
        el('msu-gap-body').innerHTML = '<span class="msu-muted">Đang phân tích...</span>';
        var scope = deps.getScope();
        deps.rpc('/misa_sale_status/api/gap_analysis', {
            saler_code: scope.saler_code, date_from: scope.date_from, date_to: scope.date_to,
            category: filter.category, month: filter.month,
        }).then(function (res) {
            data = res.data;
            render();
        }).catch(function (e) {
            el('msu-gap-body').innerHTML = '<div class="msu-modal-error">Lỗi phân tích: ' + deps.esc(e.message) + '</div>';
        });
    }

    /* Soát từng lô 10 đơn cho tới hết — mỗi lô là 1 request ngắn, trang không bị treo và
     * thấy được tiến độ. Dừng khi 1 lô không soát được đơn nào (MISA đang lỗi). */
    function refreshOrders() {
        var btn = el('msu-gap-refresh');
        var status = el('msu-gap-refresh-status');
        var scope = deps.getScope();
        var total = 0;
        var failed = 0;
        btn.disabled = true;
        function step(startedAt) {
            status.textContent = 'Đang hỏi MISA... đã soát ' + total + ' đơn';
            return deps.rpc('/misa_sale_status/api/gap_refresh_orders', {
                saler_code: scope.saler_code, date_from: scope.date_from, date_to: scope.date_to,
                started_at: startedAt || '',
            }).then(function (res) {
                var d = res.data;
                total += d.done;
                failed = d.failed;
                if (d.remaining > 0 && d.done > 0) { return step(d.started_at); }
                status.textContent = 'Đã soát ' + total + ' đơn với MISA' +
                    (failed ? ', ' + failed + ' đơn MISA chưa trả lời được — thử lại sau' : '') + '.';
            });
        }
        step('').catch(function (e) {
            status.textContent = 'Lỗi: ' + e.message;
        }).finally(function () {
            btn.disabled = false;
            load();
            deps.onDataChanged();
        });
    }

    function open() {
        filter = {category: '', month: ''};
        el('msu-gap-refresh-status').textContent = '';
        el('msu-gap-modal').style.display = 'flex';
        load();
    }

    function close() { el('msu-gap-modal').style.display = 'none'; }

    window.MsuGapPanel = {
        /* deps: {rpc, esc, fmtMoney, fmtDate, getScope() -> {saler_code, date_from, date_to},
         *        openPicking(id), openShopeeTab(pickingName), onDataChanged()} */
        init: function (d) {
            deps = d;
            el('msu-gap-open').addEventListener('click', open);
            el('msu-gap-close').addEventListener('click', close);
            el('msu-gap-close-x').addEventListener('click', close);
            el('msu-gap-refresh').addEventListener('click', refreshOrders);
            el('msu-gap-modal').addEventListener('click', function (ev) {
                if (ev.target === el('msu-gap-modal')) { close(); }
            });
        },
    };
})();

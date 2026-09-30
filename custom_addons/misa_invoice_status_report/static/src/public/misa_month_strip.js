/* Dải cột "Theo tháng xuất kho" trên trang /misa_sale_status: mỗi tháng 1 cột (tiền xuất kho, đã
 * xuất HĐ, còn lệch, số phiếu/đơn chưa xuất HĐ). Bấm 1 cột = lọc CẢ TRANG về đúng tháng đó (dùng
 * chung ô ngày xuất kho), bấm lại cột đang chọn = bỏ lọc. Luôn tải toàn bộ các tháng (không theo
 * ô ngày) để chuyển tháng được bất cứ lúc nào. Không tự có rpc/định dạng tiền — trang chính truyền
 * vào qua MsuMonthStrip.init(deps). */
(function () {
    'use strict';

    var deps = null;
    var months = [];

    function el(id) { return document.getElementById(id); }

    function isActive(m) {
        var range = deps.getRange();
        return range.date_from === m.date_from && range.date_to === m.date_to;
    }

    function renderColumn(m) {
        var gap = (m.actual_amount || 0) - (m.invoice_amount || 0);
        var pct = m.actual_amount > 0 ? Math.min(100, Math.round(m.invoice_amount / m.actual_amount * 100)) : 100;
        var pending = m.pending_count
            ? '<b>' + m.pending_count + '</b> phiếu · <b>' + m.pending_order_count + '</b> đơn chưa xuất HĐ'
            : '<span class="msu-month-done"><i class="fa fa-check"></i> Đã xuất HĐ hết</span>';
        return '<button type="button" class="msu-month-col' + (isActive(m) ? ' msu-month-active' : '') + '"' +
            ' data-from="' + deps.esc(m.date_from) + '" data-to="' + deps.esc(m.date_to) + '">' +
            '<span class="msu-month-name">' + deps.esc(m.label) + '</span>' +
            '<span class="msu-month-line"><span>Xuất kho</span><b>' + deps.fmtMoney(m.actual_amount) + '</b></span>' +
            '<span class="msu-month-line"><span>Đã xuất HĐ</span><b class="msu-month-good">' + deps.fmtMoney(m.invoice_amount) + '</b></span>' +
            '<span class="msu-month-line"><span>Còn lệch</span><b class="' + (Math.abs(gap) >= 1 ? 'msu-month-gap' : '') + '">' +
            deps.fmtMoney(gap) + '</b></span>' +
            '<span class="msu-month-bar" title="' + pct + '% tiền xuất kho đã có HĐ"><i style="width:' + pct + '%"></i></span>' +
            '<span class="msu-month-pending">' + pending + '</span>' +
            '</button>';
    }

    function render() {
        var box = el('msu-month-strip');
        if (!box || !deps) { return; }
        if (!months.length) {
            box.innerHTML = '<span class="msu-muted">Chưa có phiếu xuất kho nào.</span>';
            return;
        }
        // Tháng mới nhất bên trái — tháng đang cần xử lý thường là tháng gần đây.
        box.innerHTML = months.slice().reverse().map(renderColumn).join('');
    }

    function load() {
        var box = el('msu-month-strip');
        var salerCode = deps && deps.getSalerCode();
        if (!box || !salerCode) { return; }
        box.innerHTML = '<span class="msu-muted"><i class="fa fa-spinner fa-spin"></i> Đang tải...</span>';
        deps.rpc('/misa_sale_status/api/daily_stats', {saler_code: salerCode, monthly: true}).then(function (res) {
            months = res.buckets || [];
            render();
        }).catch(function (e) {
            box.innerHTML = '<span class="msu-muted">Lỗi tải số liệu theo tháng: ' + deps.esc(e.message) + '</span>';
        });
    }

    function init(d) {
        deps = d;
        var box = el('msu-month-strip');
        if (!box) { return; }
        box.addEventListener('click', function (ev) {
            var col = ev.target.closest('.msu-month-col');
            if (!col) { return; }
            if (col.classList.contains('msu-month-active')) {
                deps.setRange('', '');
            } else {
                deps.setRange(col.dataset.from, col.dataset.to);
            }
        });
    }

    window.MsuMonthStrip = {init: init, load: load, render: render};
})();

/* Nút "Xem phiếu xuất kho" trong drawer trang /sale_plan (chỉ xem).
 *
 * Toàn bộ UI của tính năng nằm trong file này: CSS, nút, modal, gọi API. Không
 * đụng vào state/DOM sẵn có của trang, chỉ nghe sự kiện 'sale_plan:drawer_open'
 * và chèn thêm một nút vào đầu #dr-body. Gỡ tính năng = xoá file này + thẻ
 * <script src> + dòng dispatchEvent cuối openDrawer + controller cùng tên.
 *
 * Trang /sale_plan chạy trong IIFE nên không có hàm nào expose ra global —
 * đó là lý do phải bắt tay bằng CustomEvent thay vì patch window.openDrawer.
 */
(function () {
"use strict";

var LIST_URL = '/api/sale_plan/out_pickings';
var DETAIL_URL = '/api/sale_plan/out_picking_detail';

var STATE_CLASS = {
    done: 'spop-badge-done',
    assigned: 'spop-badge-ready',
    confirmed: 'spop-badge-wait',
    waiting: 'spop-badge-wait',
    draft: 'spop-badge-draft',
    cancel: 'spop-badge-cancel',
};

var current = { orderId: null, orderName: '' };

/* ── Tiện ích nhỏ (trang gốc có sẵn nhưng nằm trong IIFE khác) ────────────── */

function esc(value) {
    return String(value === null || value === undefined ? '' : value)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function fq(value) {
    var num = Number(value || 0);
    return num.toLocaleString('vi-VN', { maximumFractionDigits: 2 });
}

function callJson(url, params) {
    return fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', method: 'call', params: params || {} }),
    }).then(function (res) {
        return res.json();
    }).then(function (payload) {
        return (payload && payload.result) || { status: 'error', message: 'Không đọc được phản hồi.' };
    });
}

/* ── CSS (nhúng 1 lần, prefix spop- để không đụng style của trang) ────────── */

function injectStyles() {
    if (document.getElementById('spop-styles')) return;
    var style = document.createElement('style');
    style.id = 'spop-styles';
    style.textContent = [
        '.spop-open-btn{display:inline-flex;align-items:center;gap:6px;font-size:.78rem;font-weight:600;',
        'padding:6px 12px;border:1px solid #bfdbfe;border-radius:6px;background:#eff6ff;color:#1d4ed8;cursor:pointer}',
        '.spop-open-btn:hover{background:#dbeafe;border-color:#3b82f6}',
        '.spop-modal{display:none;position:fixed;inset:0;z-index:2150;background:rgba(15,23,42,.45);',
        'align-items:center;justify-content:center;padding:16px}',
        '.spop-modal.open{display:flex}',
        '.spop-dialog{background:#fff;border-radius:10px;width:min(920px,100%);max-height:88vh;display:flex;',
        'flex-direction:column;box-shadow:0 24px 60px rgba(15,23,42,.28);overflow:hidden}',
        '.spop-header{display:flex;align-items:center;gap:10px;padding:12px 16px;border-bottom:1px solid #e2e8f0;background:#f8fafc}',
        '.spop-title{font-weight:700;font-size:.95rem;color:#0f172a;flex:1;line-height:1.3}',
        '.spop-title small{display:block;font-weight:500;font-size:.72rem;color:#64748b}',
        '.spop-hbtn{border:1px solid #e2e8f0;background:#fff;border-radius:6px;padding:4px 10px;font-size:.75rem;cursor:pointer;color:#475569}',
        '.spop-hbtn:hover{background:#f1f5f9}',
        '.spop-body{padding:14px 16px;overflow-y:auto}',
        '.spop-row{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center;width:100%;text-align:left;',
        'border:1px solid #e2e8f0;border-radius:8px;padding:10px 12px;margin-bottom:8px;background:#fff;cursor:pointer}',
        '.spop-row:hover{border-color:#3b82f6;background:#f8fafc}',
        '.spop-row-name{font-weight:700;color:#1d4ed8;font-size:.85rem}',
        '.spop-meta{font-size:.74rem;color:#64748b}',
        '.spop-badge{font-size:.68rem;font-weight:700;padding:2px 8px;border-radius:999px}',
        '.spop-badge-done{background:#dcfce7;color:#15803d}',
        '.spop-badge-ready{background:#dbeafe;color:#1d4ed8}',
        '.spop-badge-wait{background:#fef3c7;color:#b45309}',
        '.spop-badge-draft{background:#f1f5f9;color:#475569}',
        '.spop-badge-cancel{background:#fee2e2;color:#b91c1c}',
        '.spop-info{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px 16px;',
        'background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:12px;margin-bottom:12px}',
        '.spop-info div{font-size:.78rem;color:#334155}',
        '.spop-info b{color:#0f172a}',
        '.spop-table{width:100%;border-collapse:collapse;font-size:.78rem}',
        '.spop-table th,.spop-table td{border:1px solid #e2e8f0;padding:6px 8px;vertical-align:top}',
        '.spop-table th{background:#f1f5f9;color:#475569;font-size:.72rem;text-transform:uppercase;letter-spacing:.3px}',
        '.spop-table td.num{text-align:right;white-space:nowrap}',
        '.spop-sub{font-size:.7rem;color:#64748b}',
        '.spop-empty{padding:28px 12px;text-align:center;color:#64748b;font-size:.85rem}',
        '@media(max-width:640px){.spop-dialog{max-height:94vh}}',
    ].join('');
    document.head.appendChild(style);
}

/* ── Modal ───────────────────────────────────────────────────────────────── */

function ensureModal() {
    var modal = document.getElementById('spop-modal');
    if (modal) return modal;

    modal = document.createElement('div');
    modal.id = 'spop-modal';
    modal.className = 'spop-modal';
    modal.innerHTML =
        '<div class="spop-dialog">'
        + '<div class="spop-header">'
        + '<button type="button" class="spop-hbtn" id="spop-back" style="display:none">&#8592; Danh sách</button>'
        + '<div class="spop-title" id="spop-title"></div>'
        + '<button type="button" class="spop-hbtn" id="spop-close">&times;</button>'
        + '</div>'
        + '<div class="spop-body" id="spop-body"></div>'
        + '</div>';
    document.body.appendChild(modal);

    modal.addEventListener('click', function (ev) {
        if (ev.target === modal) closeModal();
    });
    modal.querySelector('#spop-close').addEventListener('click', closeModal);
    modal.querySelector('#spop-back').addEventListener('click', function () {
        showList();
    });
    // Bắt ở capture để ESC đóng modal này trước khi trang gốc đóng drawer.
    document.addEventListener('keydown', function (ev) {
        if (ev.key === 'Escape' && modal.classList.contains('open')) {
            ev.stopPropagation();
            closeModal();
        }
    }, true);
    return modal;
}

function setTitle(main, sub) {
    var el = document.getElementById('spop-title');
    if (!el) return;
    el.innerHTML = esc(main) + (sub ? '<small>' + esc(sub) + '</small>' : '');
}

function setBody(html) {
    var el = document.getElementById('spop-body');
    if (el) el.innerHTML = html;
}

function setBackVisible(visible) {
    var el = document.getElementById('spop-back');
    if (el) el.style.display = visible ? '' : 'none';
}

function openModal() {
    ensureModal().classList.add('open');
}

function closeModal() {
    var modal = document.getElementById('spop-modal');
    if (modal) modal.classList.remove('open');
}

function loadingHtml(text) {
    return '<div class="spop-empty"><i class="fa fa-spinner fa-spin me-1"></i>' + esc(text) + '</div>';
}

function errorHtml(message) {
    return '<div class="spop-empty" style="color:#b91c1c">'
        + '<i class="fa fa-exclamation-triangle me-1"></i>' + esc(message) + '</div>';
}

function badgeHtml(picking) {
    var cls = STATE_CLASS[picking.state] || 'spop-badge-draft';
    return '<span class="spop-badge ' + cls + '">' + esc(picking.state_label) + '</span>';
}

/* ── Màn hình 1: danh sách phiếu ─────────────────────────────────────────── */

function showList() {
    setBackVisible(false);
    setTitle('Phiếu xuất kho', current.orderName);
    setBody(loadingHtml('Đang tải danh sách phiếu...'));
    openModal();

    var requestedOrderId = current.orderId;
    callJson(LIST_URL, { order_id: requestedOrderId }).then(function (result) {
        // Người dùng có thể đã mở đơn khác trong lúc chờ.
        if (requestedOrderId !== current.orderId) return;
        if (result.status !== 'success') {
            setBody(errorHtml(result.message || 'Không tải được danh sách phiếu.'));
            return;
        }
        var pickings = result.pickings || [];
        if (!pickings.length) {
            setBody('<div class="spop-empty"><i class="fa fa-inbox fa-2x d-block mb-2 opacity-50"></i>'
                + 'Đơn này chưa có phiếu xuất kho nào.</div>');
            return;
        }
        setBody(pickings.map(rowHtml).join(''));
        Array.prototype.forEach.call(
            document.querySelectorAll('#spop-body .spop-row'),
            function (row) {
                row.addEventListener('click', function () {
                    showDetail(parseInt(row.dataset.pickingId, 10));
                });
            }
        );
    }).catch(function () {
        setBody(errorHtml('Lỗi kết nối khi tải danh sách phiếu.'));
    });
}

function rowHtml(picking) {
    var when = picking.date_done
        ? '<i class="fa fa-check-circle me-1"></i>Đã giao: ' + esc(picking.date_done)
        : (picking.scheduled_date
            ? '<i class="fa fa-clock-o me-1"></i>Dự kiến: ' + esc(picking.scheduled_date)
            : '');
    return '<button type="button" class="spop-row" data-picking-id="' + picking.id + '">'
        + '<span class="spop-row-name">' + esc(picking.name) + '</span>'
        + badgeHtml(picking)
        + (when ? '<span class="spop-meta">' + when + '</span>' : '')
        + '<span class="spop-meta"><i class="fa fa-cubes me-1"></i>'
        + fq(picking.qty_done) + '/' + fq(picking.qty_demand) + ' (' + picking.line_count + ' SP)</span>'
        + (picking.warehouse_name
            ? '<span class="spop-meta"><i class="fa fa-building me-1"></i>' + esc(picking.warehouse_name) + '</span>'
            : '')
        + (picking.backorder_of
            ? '<span class="spop-meta"><i class="fa fa-link me-1"></i>Tách từ ' + esc(picking.backorder_of) + '</span>'
            : '')
        + '</button>';
}

/* ── Màn hình 2: chi tiết một phiếu ──────────────────────────────────────── */

function showDetail(pickingId) {
    if (!pickingId) return;
    setBackVisible(true);
    setTitle('Chi tiết phiếu xuất kho', current.orderName);
    setBody(loadingHtml('Đang tải chi tiết phiếu...'));

    var requestedOrderId = current.orderId;
    callJson(DETAIL_URL, { order_id: requestedOrderId, picking_id: pickingId }).then(function (result) {
        if (requestedOrderId !== current.orderId) return;
        if (result.status !== 'success' || !result.picking) {
            setBody(errorHtml(result.message || 'Không tải được chi tiết phiếu.'));
            return;
        }
        var picking = result.picking;
        setTitle(picking.name, current.orderName);
        setBody(detailHtml(picking));
    }).catch(function () {
        setBody(errorHtml('Lỗi kết nối khi tải chi tiết phiếu.'));
    });
}

function infoItem(label, value, icon) {
    if (!value) return '';
    return '<div><i class="fa ' + icon + ' me-1 text-muted"></i><b>' + esc(label) + ':</b> ' + esc(value) + '</div>';
}

function detailHtml(picking) {
    var html = '<div class="spop-info">'
        + '<div><i class="fa fa-info-circle me-1 text-muted"></i><b>Trạng thái:</b> ' + badgeHtml(picking) + '</div>'
        + infoItem('Đơn hàng', picking.order_name, 'fa-shopping-cart')
        + infoItem('Loại phiếu', picking.type_name, 'fa-file-text-o')
        + infoItem('Kho xuất', picking.warehouse_name, 'fa-building')
        + infoItem('Khách nhận', picking.partner_name, 'fa-user')
        + infoItem('Dự kiến giao', picking.scheduled_date, 'fa-clock-o')
        + infoItem('Đã giao lúc', picking.date_done, 'fa-check-circle')
        + infoItem('Tạo phiếu', picking.create_date, 'fa-calendar')
        + infoItem('Hình thức giao', picking.delivery_type, 'fa-truck')
        + infoItem('HTGH', picking.htgh, 'fa-info-circle')
        + infoItem('Tài xế', picking.shipper_name
            ? picking.shipper_name + (picking.shipper_received ? ' (đã nhận hàng)' : '')
            : '', 'fa-motorcycle')
        + infoItem('Người phụ trách', picking.responsible, 'fa-user-circle-o')
        + infoItem('Tách từ phiếu', picking.backorder_of, 'fa-link')
        + infoItem('Nguồn', picking.origin, 'fa-sticky-note-o')
        + infoItem('Địa chỉ giao', picking.shipping_address, 'fa-map-marker')
        + infoItem('Ghi chú', picking.note, 'fa-pencil')
        + '</div>';

    var lines = picking.lines || [];
    if (!lines.length) {
        return html + '<div class="spop-empty">Phiếu không có dòng sản phẩm.</div>';
    }
    html += '<table class="spop-table"><thead><tr>'
        + '<th>Sản phẩm</th><th>ĐVT</th><th class="num">Yêu cầu</th><th class="num">Thực giao</th>'
        + '</tr></thead><tbody>';
    lines.forEach(function (line) {
        var breakdown = (line.breakdown || []).map(function (item) {
            var parts = [];
            if (item.package) parts.push('Kiện ' + esc(item.package));
            if (item.lot) parts.push('Lô ' + esc(item.lot));
            parts.push(fq(item.qty));
            return '<div class="spop-sub"><i class="fa fa-cube me-1"></i>' + parts.join(' · ') + '</div>';
        }).join('');
        var shortage = Number(line.qty_demand || 0) - Number(line.qty_done || 0);
        html += '<tr>'
            + '<td>' + esc(line.product_name) + breakdown + '</td>'
            + '<td>' + esc(line.uom_name) + '</td>'
            + '<td class="num">' + fq(line.qty_demand) + '</td>'
            + '<td class="num"><b>' + fq(line.qty_done) + '</b>'
            + (shortage > 0 ? '<div class="spop-sub" style="color:#b91c1c">thiếu ' + fq(shortage) + '</div>' : '')
            + '</td></tr>';
    });
    html += '</tbody></table>';
    html += '<div class="spop-sub mt-2"><i class="fa fa-lock me-1"></i>Màn hình chỉ xem — '
        + 'mọi thay đổi phiếu thực hiện trong Odoo.</div>';
    return html;
}

/* ── Chèn nút vào drawer mỗi lần drawer mở ───────────────────────────────── */

function injectButton(detail) {
    var body = document.getElementById('dr-body');
    if (!body || !detail || !detail.order_id) return;

    current.orderId = detail.order_id;
    current.orderName = detail.order_name || '';
    // Drawer render lại #dr-body mỗi lần mở nên nút cũ (nếu còn) phải bỏ đi.
    var old = document.getElementById('spop-open-wrap');
    if (old && old.parentNode) old.parentNode.removeChild(old);

    var wrap = document.createElement('div');
    wrap.id = 'spop-open-wrap';
    wrap.style.marginBottom = '12px';
    wrap.innerHTML = '<button type="button" class="spop-open-btn" id="spop-open-btn">'
        + '<i class="fa fa-truck"></i> Xem phiếu xuất kho</button>';
    body.insertBefore(wrap, body.firstChild);
    wrap.querySelector('#spop-open-btn').addEventListener('click', function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        showList();
    });
}

injectStyles();
document.addEventListener('sale_plan:drawer_open', function (ev) {
    injectButton(ev.detail || {});
});
})();

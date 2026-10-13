/**
 * Trang đơn mua của NCC: đang sửa dòng (bút chì) thì cột "Thành tiền sau VAT" và footer tổng tính lại theo số lượng /
 * đơn giá mới ngay khi gõ — tô màu vì là số dự kiến, bên mua duyệt mới áp. Bỏ sửa dòng thì trả lại số trên đơn.
 * Footer = tổng trên đơn + phần chênh của các dòng đang sửa, để dòng không sửa giữ đúng số Odoo đã tính.
 *
 * Trang này không qua asset bundle của Odoo nên viết JS thường.
 */
(function () {
    "use strict";

    const form = document.querySelector(".vq-revise-form");
    if (!form) {
        return;
    }
    const { parseVnNumber, formatVnNumber, lineAmounts } = window.hlvVendorQuote;
    const rows = Array.from(form.querySelectorAll("tr[data-vq-pair]"));
    const footCells = Array.from(form.querySelectorAll("[data-vq-foot]"));
    const shown = new Map();  // ô → chữ server in ra (số trên đơn)
    for (const cell of footCells.concat(rows.map((row) => row.querySelector("[data-vq-subtotal]")))) {
        if (cell) {
            shown.set(cell, cell.textContent);
        }
    }

    function show(cell, value) {
        if (!cell) {
            return;
        }
        const draft = value != null;
        cell.textContent = draft ? formatVnNumber(Math.round(value)) : shown.get(cell);
        cell.classList.toggle("is-draft-amount", draft);
    }

    /** Tiền dòng theo đơn và theo số đang gõ; null khi dòng không đang sửa. Ô trống = giữ số trên đơn (như server). */
    function rowChange(row) {
        const toggle = row.querySelector(".vq-edit-toggle");
        if (!toggle || !toggle.checked) {
            return null;
        }
        const rate = parseFloat(row.dataset.vqVatRate) || 0;
        const oldQty = parseFloat(row.dataset.vqQty) || 0;
        const oldNet = parseFloat(row.dataset.vqPrice) || 0;
        const qtyInput = row.querySelector('input[name^="qty_"]');
        const netInput = row.querySelector("[data-vq-net]");
        const qty = qtyInput ? parseVnNumber(qtyInput.value) : null;
        const net = netInput ? parseVnNumber(netInput.value) : null;
        return {
            before: lineAmounts(oldNet, oldQty, rate),
            after: lineAmounts(net == null ? oldNet : net, qty == null ? oldQty : qty, rate),
        };
    }

    function refresh() {
        const delta = { untaxed: 0, tax: 0, total: 0 };
        let editing = false;
        for (const row of rows) {
            const change = rowChange(row);
            show(row.querySelector("[data-vq-subtotal]"), change && change.after.total);
            if (change) {
                editing = true;
                for (const key of Object.keys(delta)) {
                    delta[key] += change.after[key] - change.before[key];
                }
            }
        }
        for (const cell of footCells) {
            const key = cell.dataset.vqFoot;
            show(cell, editing ? (parseVnNumber(shown.get(cell)) || 0) + delta[key] : null);
        }
    }

    form.addEventListener("input", refresh);
    form.addEventListener("change", refresh);
})();

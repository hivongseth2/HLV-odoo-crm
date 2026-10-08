/**
 * Bảng nhập giá của NCC dùng như bảng tính:
 *  - Enter: xuống ô cùng cột ở dòng dưới (Shift+Enter: lên) — không gửi form giữa chừng.
 *  - Dán nhiều dòng (copy một cột trong Excel / phần mềm bán hàng): điền xuống các dòng dưới theo
 *    đúng thứ tự mặt hàng — dòng đã khoá vẫn tính là một dòng (bỏ qua giá trị của nó); dòng có
 *    nhiều cột (cách nhau bằng tab): điền sang các ô nhập bên phải.
 * Ô nào được điền cũng phát sự kiện "input" để vendor_quote_form.js tính lại giá, thành tiền.
 * Trang không qua asset bundle của Odoo nên viết JS thường.
 */
(function () {
    "use strict";

    const grid = document.querySelector("[data-vq-grid]");
    if (!grid) {
        return;
    }
    const form = grid.closest("form");
    const FIELD = "input.vq-cell-input, select.vq-cell-input";

    function rows() {
        return Array.from(grid.querySelectorAll("tbody tr[data-vq-line]"));
    }

    /** Ô đang dùng được: không khoá, không nằm trong cột chiết khấu khi đang tắt chiết khấu. */
    function usable(field) {
        if (field.disabled || field.readOnly) {
            return false;
        }
        return !field.closest(".vq-disc-only") || (form && form.classList.contains("vq-disc-on"));
    }

    /** Các ô gõ chữ / số của một dòng từ cột `fromIndex` sang phải, theo thứ tự cột. */
    function fieldsFrom(row, fromIndex) {
        return Array.from(row.querySelectorAll("input.vq-cell-input"))
            .filter((field) => usable(field) && field.closest("td").cellIndex >= fromIndex)
            .sort((a, b) => a.closest("td").cellIndex - b.closest("td").cellIndex);
    }

    function fieldAt(row, cellIndex) {
        const cell = row && row.cells[cellIndex];
        const field = cell && cell.querySelector(FIELD);
        return field && usable(field) ? field : null;
    }

    function assign(field, raw) {
        field.value = raw.trim();
        field.dispatchEvent(new Event("input", { bubbles: true }));
    }

    grid.addEventListener("keydown", (ev) => {
        const field = ev.target;
        if (ev.key !== "Enter" || !field.matches(FIELD)) {
            return;
        }
        ev.preventDefault();
        const list = rows();
        const step = ev.shiftKey ? -1 : 1;
        const cellIndex = field.closest("td").cellIndex;
        for (let i = list.indexOf(field.closest("tr")) + step; i >= 0 && i < list.length; i += step) {
            const next = fieldAt(list[i], cellIndex);
            if (next) {
                next.focus();
                if (next.select) {
                    next.select();
                }
                return;
            }
        }
    });

    grid.addEventListener("paste", (ev) => {
        const field = ev.target;
        if (!field.matches("input.vq-cell-input") || !ev.clipboardData) {
            return;
        }
        const text = ev.clipboardData.getData("text/plain") || ev.clipboardData.getData("text") || "";
        if (!/[\n\t]/.test(text.replace(/\r?\n$/, ""))) {
            return;  // một giá trị: để trình duyệt dán như thường
        }
        ev.preventDefault();
        const lines = text.replace(/\r/g, "").replace(/\n$/, "").split("\n");
        const list = rows();
        const start = list.indexOf(field.closest("tr"));
        const cellIndex = field.closest("td").cellIndex;
        lines.forEach((line, offset) => {
            const row = list[start + offset];
            if (!row) {
                return;
            }
            const targets = fieldsFrom(row, cellIndex);
            line.split("\t").forEach((value, column) => {
                if (targets[column]) {
                    assign(targets[column], value);
                }
            });
        });
    });
})();

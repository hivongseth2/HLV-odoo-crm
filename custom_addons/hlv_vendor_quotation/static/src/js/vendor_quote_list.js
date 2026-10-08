/**
 * Danh sách báo giá của NCC: bấm vào một dòng (hoặc nút mũi tên) để xem nhanh danh sách hàng
 * ngay bên dưới; bấm lại để thu. Bấm vào link / nút trong dòng thì đi như thường.
 * Trang không qua asset bundle của Odoo nên viết JS thường.
 */
(function () {
    "use strict";

    const body = document.querySelector('tbody[data-live="rows"]');
    if (!body) {
        return;
    }
    const open = new Set();

    function apply() {
        for (const row of body.querySelectorAll("[data-quick-row]")) {
            const id = row.dataset.quickRow;
            const isOpen = open.has(id);
            row.hidden = !isOpen;
            const quoteRow = body.querySelector(`[data-quote-row="${id}"]`);
            if (quoteRow) {
                quoteRow.classList.toggle("vq-row-open", isOpen);
                const toggle = quoteRow.querySelector("[data-quick-toggle]");
                if (toggle) {
                    toggle.setAttribute("aria-expanded", String(isOpen));
                }
            }
        }
    }

    body.addEventListener("click", (ev) => {
        const toggle = ev.target.closest("[data-quick-toggle]");
        let id = toggle && toggle.dataset.quickToggle;
        if (!id) {
            if (ev.target.closest("a, button, input, select, label, [data-quick-row]")) {
                return;
            }
            const row = ev.target.closest("[data-quote-row]");
            if (!row) {
                return;
            }
            id = row.dataset.quoteRow;
        }
        if (open.has(id)) {
            open.delete(id);
        } else {
            open.add(id);
        }
        apply();
    });

    // vendor_live.js thay cả nội dung tbody khi có tin mới — mở lại các báo giá đang xem.
    new MutationObserver(apply).observe(body, { childList: true });
})();

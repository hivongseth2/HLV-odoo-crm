/**
 * Trang nhập giá của NCC: tính thành tiền tạm, định dạng lại số khi rời ô, chọn VAT
 * cho tất cả dòng. Trang vẫn gửi được khi JS hỏng — server tự đọc và kiểm lại số.
 */
(function () {
    "use strict";

    const form = document.querySelector(".vq-quote-form");
    if (!form) {
        return;
    }
    const { parseVnNumber, formatVnNumber } = window.hlvVendorQuote;
    const lines = Array.from(form.querySelectorAll("[data-vq-line]"));

    function vatRate(select) {
        const value = select ? select.value : "";
        return value && value !== "kct" ? parseFloat(value) : 0;
    }

    function refreshTotals() {
        let untaxed = 0;
        let total = 0;
        for (const line of lines) {
            const unavailable = line.querySelector("[data-vq-na]").checked;
            const price = parseVnNumber(line.querySelector("[data-vq-price]").value);
            const qty = parseFloat(line.dataset.qty) || 0;
            const subtotal = unavailable || price == null ? null : price * qty;
            line.classList.toggle("vq-line-na", unavailable);
            line.querySelector("[data-vq-subtotal]").textContent =
                subtotal == null ? "—" : formatVnNumber(Math.round(subtotal));
            if (subtotal != null) {
                untaxed += subtotal;
                total += subtotal * (1 + vatRate(line.querySelector("[data-vq-vat]")) / 100);
            }
        }
        form.querySelector("[data-vq-total-untaxed]").textContent = formatVnNumber(Math.round(untaxed));
        form.querySelector("[data-vq-total]").textContent = formatVnNumber(Math.round(total));
    }

    form.addEventListener("input", refreshTotals);
    form.addEventListener("change", refreshTotals);

    form.addEventListener("focusout", (ev) => {
        if (!ev.target.matches("[data-vq-price]")) {
            return;
        }
        const value = parseVnNumber(ev.target.value);
        if (value != null) {
            ev.target.value = formatVnNumber(value);
        }
    });

    const vatAll = form.querySelector("[data-vq-vat-all]");
    if (vatAll) {
        vatAll.addEventListener("change", () => {
            if (!vatAll.value) {
                return;
            }
            for (const select of form.querySelectorAll("[data-vq-vat]")) {
                select.value = vatAll.value;
            }
            refreshTotals();
        });
    }

    refreshTotals();
})();

/**
 * Trang nhập giá của NCC: tính thành tiền tạm, đếm số dòng đã điền, định dạng lại số khi
 * rời ô, chọn VAT cho tất cả dòng. Trang vẫn gửi được khi JS hỏng — server tự đọc và kiểm
 * lại số. Báo giá đã đóng không có ô nhập: giá / VAT đọc từ data-price, data-vat của dòng.
 */
(function () {
    "use strict";

    const form = document.querySelector(".vq-quote-form");
    if (!form) {
        return;
    }
    const { parseVnNumber, formatVnNumber } = window.hlvVendorQuote;
    const lines = Array.from(form.querySelectorAll("[data-vq-line]"));

    function vatRate(value) {
        return value && value !== "kct" ? parseFloat(value) : 0;
    }

    function readLine(line) {
        const priceInput = line.querySelector("[data-vq-price]");
        const vatSelect = line.querySelector("[data-vq-vat]");
        const price = priceInput ? parseVnNumber(priceInput.value) : parseFloat(line.dataset.price) || null;
        return {
            unavailable: line.querySelector("[data-vq-na]").checked,
            price: price || null,
            vat: vatSelect ? vatSelect.value : line.dataset.vat,
            qty: parseFloat(line.dataset.qty) || 0,
        };
    }

    function setText(selector, text) {
        const el = form.querySelector(selector);
        if (el) {
            el.textContent = text;
        }
    }

    function refresh() {
        let untaxed = 0;
        let total = 0;
        let done = 0;
        for (const line of lines) {
            const { unavailable, price, vat, qty } = readLine(line);
            const subtotal = unavailable || price == null ? null : price * qty;
            line.classList.toggle("vq-line-na", unavailable);
            line.querySelector("[data-vq-subtotal]").textContent = unavailable
                ? "Không có hàng"
                : subtotal == null ? "—" : formatVnNumber(Math.round(subtotal));
            // "Đã điền" khớp điều kiện server nhận: có giá + VAT, hoặc báo không có hàng.
            if (unavailable || (price && vat)) {
                done += 1;
            }
            if (subtotal != null) {
                untaxed += subtotal;
                total += subtotal * (1 + vatRate(vat) / 100);
            }
        }
        setText("[data-vq-total-untaxed]", formatVnNumber(Math.round(untaxed)));
        setText("[data-vq-total]", formatVnNumber(Math.round(total)));
        setText("[data-vq-progress]", `Đã điền ${done}/${lines.length} mặt hàng`);
        const bar = form.querySelector("[data-vq-progress-bar]");
        if (bar) {
            bar.style.width = `${lines.length ? Math.round((100 * done) / lines.length) : 0}%`;
            bar.classList.toggle("vq-progress-done", done === lines.length);
        }
    }

    form.addEventListener("input", refresh);
    form.addEventListener("change", refresh);

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
            refresh();
        });
    }

    refresh();
})();

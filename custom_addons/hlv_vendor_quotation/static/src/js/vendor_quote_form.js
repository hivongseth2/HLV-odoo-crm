/**
 * Trang nhập giá của NCC: quy đổi 2 chiều giá trước chiết khấu ↔ đơn giá chưa VAT ↔ đơn giá
 * sau VAT (vendor_quote_price.js), tính thành tiền tạm, đếm số dòng đã điền, định dạng lại
 * số khi rời ô, chọn VAT / % chiết khấu cho tất cả dòng. Trang vẫn gửi được khi JS hỏng —
 * server tự suy đơn giá từ ô có số (resolve_net_price). Báo giá đã đóng không có ô nhập:
 * giá / VAT đọc từ data-price, data-vat của dòng.
 */
(function () {
    "use strict";

    const form = document.querySelector(".vq-quote-form");
    if (!form) {
        return;
    }
    const { parseVnNumber, formatVnNumber, derivePrices } = window.hlvVendorQuote;
    const lines = Array.from(form.querySelectorAll("[data-vq-line]"));
    const discountToggle = form.querySelector("[data-vq-disc-toggle]");
    // Báo giá đã đóng không có ô bật/tắt: server tự gắn vq-disc-on nếu NCC từng nhập chiết khấu.
    const discountShownByServer = form.classList.contains("vq-disc-on");
    // Ô giá theo "mốc": NCC gõ ô nào thì ô đó là mốc, hai ô kia tính lại theo nó.
    const PRICE_INPUTS = { list: "[data-vq-list]", net: "[data-vq-price]", gross: "[data-vq-gross]" };
    // Số cột sau cột STT — hàng phụ (ngày giao, tên HĐ, ghi chú) trải hết chừng ấy cột.
    const EXTRA_SPAN = { off: 6, on: 8 };

    function vatRate(value) {
        return value && value !== "kct" ? parseFloat(value) : 0;
    }

    function discountOn() {
        return discountToggle ? discountToggle.checked : discountShownByServer;
    }

    function lineDiscount(line) {
        const input = line.querySelector("[data-vq-disc]");
        if (!discountOn() || !input) {
            return 0;
        }
        const value = parseVnNumber(input.value);
        return value == null ? 0 : value;
    }

    function priceInputs(line) {
        const inputs = {};
        for (const [key, selector] of Object.entries(PRICE_INPUTS)) {
            inputs[key] = line.querySelector(selector);
        }
        return inputs;
    }

    /** Tính lại các ô giá của dòng theo ô mốc; ô `typing` (đang gõ) không bị ghi đè. */
    function recompute(line, typing) {
        const inputs = priceInputs(line);
        const vatSelect = line.querySelector("[data-vq-vat]");
        if (!inputs.net || !vatSelect) {
            return;  // dòng không sửa được
        }
        const values = {};
        for (const [key, input] of Object.entries(inputs)) {
            values[key] = input ? parseVnNumber(input.value) : null;
        }
        const result = derivePrices(line.dataset.anchor || "net", values, vatRate(vatSelect.value), lineDiscount(line));
        const discInput = line.querySelector("[data-vq-disc]");
        if (discInput) {
            discInput.classList.toggle("vq-input-error", discountOn() && result === null);
        }
        if (!result) {
            return;
        }
        for (const [key, input] of Object.entries(inputs)) {
            if (!input || input === typing || key === line.dataset.anchor || (key === "list" && !discountOn())) {
                continue;
            }
            input.value = result[key] == null ? "" : formatVnNumber(result[key]);
        }
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
    }

    /** Bật / tắt cột "giá trước chiết khấu" + "% CK". Tắt thì đơn giá chưa VAT là mốc. */
    function applyDiscountMode() {
        const on = discountOn();
        form.classList.toggle("vq-disc-on", on);
        for (const cell of form.querySelectorAll("[data-vq-extra-cell]")) {
            cell.colSpan = on ? EXTRA_SPAN.on : EXTRA_SPAN.off;
        }
        for (const line of lines) {
            if (!on && line.dataset.anchor === "list") {
                line.dataset.anchor = "net";
            }
            recompute(line);
        }
    }

    form.addEventListener("input", (ev) => {
        const target = ev.target;
        const line = target.closest("[data-vq-line]");
        if (line) {
            const anchor = Object.keys(PRICE_INPUTS).find((key) => target.matches(PRICE_INPUTS[key]));
            if (anchor) {
                line.dataset.anchor = anchor;
                recompute(line, target);
            } else if (target.matches("[data-vq-disc], [data-vq-vat]")) {
                recompute(line, target);
            }
        }
        refresh();
    });

    form.addEventListener("change", (ev) => {
        if (ev.target === discountToggle) {
            applyDiscountMode();
        }
        refresh();
    });

    form.addEventListener("focusout", (ev) => {
        if (!ev.target.matches("[data-vq-list], [data-vq-price], [data-vq-gross], [data-vq-disc]")) {
            return;
        }
        const value = parseVnNumber(ev.target.value);
        if (value != null) {
            ev.target.value = formatVnNumber(value);
        }
    });

    function applyToAll(sourceSelector, targetSelector) {
        const source = form.querySelector(sourceSelector);
        if (!source) {
            return;
        }
        source.addEventListener("change", () => {
            if (!source.value) {
                return;
            }
            for (const line of lines) {
                const target = line.querySelector(targetSelector);
                if (target) {
                    target.value = source.value;
                    recompute(line);
                }
            }
            refresh();
        });
    }
    applyToAll("[data-vq-vat-all]", "[data-vq-vat]");
    applyToAll("[data-vq-disc-all]", "[data-vq-disc]");

    // Mốc ban đầu: dòng đã lưu giá trước chiết khấu thì giữ đúng số đó, còn lại theo đơn giá chưa VAT.
    for (const line of lines) {
        const list = line.querySelector("[data-vq-list]");
        line.dataset.anchor = discountOn() && list && parseVnNumber(list.value) != null ? "list" : "net";
    }
    applyDiscountMode();
    refresh();
})();

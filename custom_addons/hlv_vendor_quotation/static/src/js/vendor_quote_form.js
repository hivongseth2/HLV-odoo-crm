/**
 * Trang nhập giá của NCC. NCC chỉ gõ MỘT ô giá: đơn giá sau VAT, đã trừ chiết khấu (thói quen
 * báo giá). Đơn giá chưa VAT — giá được lưu — và giá trước chiết khấu (khi có % CK) tự tính vào ô
 * ẩn và ghi nhỏ dưới ô giá (vendor_quote_price.js). Thành tiền / tổng hiện theo giá sau VAT, đếm số
 * dòng đã điền, định dạng lại số khi rời ô, chọn VAT / % CK cho tất cả dòng.
 * Trang vẫn gửi được khi JS hỏng — server tự tính từ ô sau VAT (resolve_net_price). Báo giá đã
 * đóng không có ô nhập: giá / VAT đọc từ data-price, data-vat của dòng.
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
    const PRICE_INPUTS = { list: "[data-vq-list]", net: "[data-vq-price]", gross: "[data-vq-gross]" };

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

    function setLineText(line, selector, value) {
        const el = line.querySelector(selector);
        if (el) {
            el.textContent = value == null ? "—" : formatVnNumber(value);
        }
    }

    /**
     * Tính lại các mức giá của dòng từ ô mốc (dataset.anchor): "gross" khi NCC đã gõ / sau khi mở
     * trang, "net" lúc mở trang (lấy giá đã lưu điền ra ô sau VAT). Ô mốc không bị ghi đè.
     */
    function recompute(line) {
        const vatSelect = line.querySelector("[data-vq-vat]");
        const inputs = {};
        for (const [key, selector] of Object.entries(PRICE_INPUTS)) {
            inputs[key] = line.querySelector(selector);
        }
        if (!inputs.net || !vatSelect) {
            return;  // dòng không sửa được
        }
        const anchor = line.dataset.anchor || "gross";
        const values = {};
        for (const [key, input] of Object.entries(inputs)) {
            values[key] = input ? parseVnNumber(input.value) : null;
        }
        const result = derivePrices(anchor, values, vatRate(vatSelect.value), lineDiscount(line));
        const discInput = line.querySelector("[data-vq-disc]");
        if (discInput) {
            discInput.classList.toggle("vq-input-error", discountOn() && result === null);
        }
        if (!result) {
            return;
        }
        for (const [key, input] of Object.entries(inputs)) {
            if (!input || key === anchor || (key === "list" && !discountOn())) {
                continue;
            }
            // Giá sau VAT tự tính (lúc mở trang): làm tròn tới đồng cho gọn ô.
            const value = key === "gross" && result[key] != null ? Math.round(result[key]) : result[key];
            input.value = value == null ? "" : formatVnNumber(value);
        }
        setLineText(line, "[data-vq-net-text]", result.net);
        setLineText(line, "[data-vq-list-text]", discountOn() ? result.list : null);
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
            const withVat = subtotal == null ? null : subtotal * (1 + vatRate(vat) / 100);
            line.classList.toggle("vq-line-na", unavailable);
            line.querySelector("[data-vq-subtotal]").textContent = unavailable
                ? "Không có hàng"
                : withVat == null ? "—" : formatVnNumber(Math.round(withVat));
            // "Đã điền" khớp điều kiện server nhận: có giá + VAT, hoặc báo không có hàng.
            if (unavailable || (price && vat)) {
                done += 1;
            }
            if (subtotal != null) {
                untaxed += subtotal;
                total += withVat;
            }
        }
        setText("[data-vq-total-untaxed]", formatVnNumber(Math.round(untaxed)));
        setText("[data-vq-total]", formatVnNumber(Math.round(total)));
        setText("[data-vq-progress]", `Đã điền ${done}/${lines.length} mặt hàng`);
    }

    /** Bật / tắt cột % CK và dòng "trước CK"; giá sau VAT NCC đã gõ giữ nguyên. */
    function applyDiscountMode() {
        form.classList.toggle("vq-disc-on", discountOn());
        lines.forEach(recompute);
    }

    form.addEventListener("input", (ev) => {
        const target = ev.target;
        const line = target.closest("[data-vq-line]");
        if (line && target.matches("[data-vq-gross], [data-vq-disc], [data-vq-vat]")) {
            line.dataset.anchor = "gross";
            recompute(line);
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
        if (!ev.target.matches("[data-vq-gross], [data-vq-disc]")) {
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
                    line.dataset.anchor = "gross";
                    recompute(line);
                }
            }
            refresh();
        });
    }
    applyToAll("[data-vq-vat-all]", "[data-vq-vat]");
    applyToAll("[data-vq-disc-all]", "[data-vq-disc]");

    // Mở trang: điền ô sau VAT từ giá chưa VAT đã lưu, rồi lấy ô sau VAT làm mốc — đổi VAT / % CK
    // là tính lại giá chưa VAT (và giá trước CK), số NCC nhìn thấy giữ nguyên.
    for (const line of lines) {
        line.dataset.anchor = "net";
    }
    applyDiscountMode();
    for (const line of lines) {
        line.dataset.anchor = "gross";
    }
    refresh();
})();

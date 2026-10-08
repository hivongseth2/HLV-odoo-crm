/**
 * Trang nhập giá của NCC. NCC gõ "Đơn giá" (đã gồm VAT; bật chiết khấu thì là giá trước CK) và
 * %CK; trang hiện giá sau CK, thành tiền, tổng trước VAT / VAT / thành tiền, đếm số dòng đã
 * điền, định dạng lại số khi rời ô, chọn VAT / %CK cho tất cả dòng. Server tự tính giá chưa VAT
 * từ đúng con số NCC gõ (split_unit_price) — trang vẫn gửi được khi JS hỏng.
 * Báo giá đã đóng không có ô nhập: giá chưa VAT / VAT đọc từ data-price, data-vat của dòng.
 */
(function () {
    "use strict";

    const form = document.querySelector(".vq-quote-form");
    if (!form) {
        return;
    }
    const { parseVnNumber, formatVnNumber, splitUnitPrice } = window.hlvVendorQuote;
    const lines = Array.from(form.querySelectorAll("[data-vq-line]"));
    const discountToggle = form.querySelector("[data-vq-disc-toggle]");
    // Báo giá đã đóng không có ô bật/tắt: server tự gắn vq-disc-on nếu NCC từng nhập chiết khấu.
    const discountShownByServer = form.classList.contains("vq-disc-on");

    function vatRate(value) {
        return value && value !== "kct" ? parseFloat(value) : 0;
    }

    function round2(value) {
        return Math.round(value * 100) / 100;
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

    /** Giá của một dòng: {unavailable, vat, qty, prices: {after, net} hoặc null}. */
    function readLine(line) {
        const unitInput = line.querySelector("[data-vq-unit]");
        const vatSelect = line.querySelector("[data-vq-vat]");
        const vat = vatSelect ? vatSelect.value : line.dataset.vat;
        let prices;
        if (unitInput) {
            prices = splitUnitPrice(parseVnNumber(unitInput.value), vatRate(vat), lineDiscount(line));
        } else {
            // Dòng khoá: server đã ghi giá chưa VAT sau CK vào data-price.
            const net = parseFloat(line.dataset.price) || 0;
            prices = net ? { net: net, after: round2(net * (1 + vatRate(vat) / 100)) } : null;
        }
        return {
            unavailable: line.querySelector("[data-vq-na]").checked,
            vat: vat,
            qty: parseFloat(line.dataset.qty) || 0,
            prices: prices,
        };
    }

    function setText(root, selector, text) {
        const el = root.querySelector(selector);
        if (el) {
            el.textContent = text;
        }
    }

    function refresh() {
        let untaxed = 0;
        let total = 0;
        let done = 0;
        for (const line of lines) {
            const { unavailable, vat, qty, prices } = readLine(line);
            const discInput = line.querySelector("[data-vq-disc]");
            if (discInput) {
                const disc = parseVnNumber(discInput.value);
                discInput.classList.toggle("vq-input-error", discountOn() && disc != null && disc >= 100);
            }
            line.classList.toggle("vq-line-na", unavailable);
            const after = prices && !unavailable ? prices.after : null;
            setText(line, "[data-vq-subtotal]", unavailable ? "Không có hàng"
                : after == null ? "—" : formatVnNumber(Math.round(after * qty)));
            setText(line, "[data-vq-after-text]", after == null ? "—" : formatVnNumber(after));
            const cell = line.querySelector("[data-vq-price-cell]");
            if (cell && line.querySelector("[data-vq-unit]")) {
                cell.title = after == null ? "" : `Chưa VAT ${formatVnNumber(prices.net)} · VAT ` +
                    formatVnNumber(round2(prices.after - prices.net));
            }
            // "Đã điền" khớp điều kiện server nhận: có giá + VAT, hoặc báo không có hàng.
            if (unavailable || (prices && vat)) {
                done += 1;
            }
            if (after != null) {
                untaxed += prices.net * qty;
                total += after * qty;
            }
        }
        setText(form, "[data-vq-total-untaxed]", formatVnNumber(Math.round(untaxed)));
        setText(form, "[data-vq-total-tax]", formatVnNumber(Math.round(total) - Math.round(untaxed)));
        setText(form, "[data-vq-total]", formatVnNumber(Math.round(total)));
        setText(form, "[data-vq-progress]", `Đã điền ${done}/${lines.length} mặt hàng`);
    }

    /**
     * Bật / tắt chiết khấu. Tắt khi dòng đang có %CK: ô đơn giá đang là giá trước CK — đổi sang
     * giá sau CK để giá NCC báo không đổi (cột %CK bị ẩn, server bỏ qua).
     */
    function applyDiscountMode(wasOn) {
        const on = discountOn();
        form.classList.toggle("vq-disc-on", on);
        if (!wasOn || on) {
            return;
        }
        for (const line of lines) {
            const unitInput = line.querySelector("[data-vq-unit]");
            const discInput = line.querySelector("[data-vq-disc]");
            const unit = unitInput ? parseVnNumber(unitInput.value) : null;
            const disc = discInput ? parseVnNumber(discInput.value) : null;
            if (unit && disc && disc > 0 && disc < 100) {
                unitInput.value = formatVnNumber(round2(unit * (1 - disc / 100)));
                discInput.value = "";
            }
        }
    }

    form.addEventListener("input", refresh);
    form.addEventListener("change", (ev) => {
        if (ev.target === discountToggle) {
            applyDiscountMode(!discountToggle.checked);
        }
        refresh();
    });

    form.addEventListener("focusout", (ev) => {
        if (!ev.target.matches("[data-vq-unit], [data-vq-disc]")) {
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
            for (const target of form.querySelectorAll(targetSelector)) {
                if (!target.disabled) {
                    target.value = source.value;
                }
            }
            refresh();
        });
    }
    applyToAll("[data-vq-vat-all]", "[data-vq-vat]");
    applyToAll("[data-vq-disc-all]", "[data-vq-disc]");

    applyDiscountMode(false);
    refresh();
})();

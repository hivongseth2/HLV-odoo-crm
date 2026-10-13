/**
 * Cặp ô đơn giá "chưa VAT" / "sau VAT" của NCC (bảng báo giá, sửa dòng đơn mua): NCC gõ ô nào cũng được, ô kia tự
 * tính theo VAT của dòng. Ô ẩn [data-vq-basis] ghi ô NCC gõ sau cùng ("net" / "gross") — server tính giá từ đúng ô
 * đó, ô kia chỉ để xem. Hàng chứa cặp ô có [data-vq-pair]; % VAT lấy từ select [data-vq-vat] trong hàng (báo giá),
 * không có thì từ data-vq-vat-rate của hàng (đơn mua — VAT theo dòng đơn, NCC không đổi).
 *
 * Trang này không qua asset bundle của Odoo nên viết JS thường, gắn vào window.hlvVendorQuote.
 */
(function () {
    "use strict";

    const { parseVnNumber, formatVnNumber, inclVat, exclVat } = window.hlvVendorQuote;

    function vatRateOf(row) {
        const select = row.querySelector("[data-vq-vat]");
        const value = select ? select.value : row.dataset.vqVatRate;
        return value && value !== "kct" ? parseFloat(value) || 0 : 0;
    }

    /** Tính lại ô không phải ô NCC gõ, từ ô NCC gõ và VAT hiện tại của hàng. */
    function syncPricePair(row) {
        const gross = row.querySelector("[data-vq-unit]");
        const net = row.querySelector("[data-vq-net]");
        if (!gross || !net) {
            return;
        }
        const basis = row.querySelector("[data-vq-basis]");
        const rate = vatRateOf(row);
        if (basis && basis.value === "net") {
            gross.value = formatVnNumber(inclVat(parseVnNumber(net.value), rate));
        } else {
            net.value = formatVnNumber(exclVat(parseVnNumber(gross.value), rate));
        }
    }

    // Pha capture: chạy trước các listener của form (vendor_quote_form.js tính thành tiền từ ô sau VAT).
    document.addEventListener("input", (ev) => {
        const row = ev.target.closest && ev.target.closest("[data-vq-pair]");
        if (!row || !ev.target.matches("[data-vq-unit], [data-vq-net]")) {
            return;
        }
        const basis = row.querySelector("[data-vq-basis]");
        if (basis) {
            basis.value = ev.target.matches("[data-vq-net]") ? "net" : "gross";
        }
        syncPricePair(row);
    }, true);

    window.hlvVendorQuote.syncPricePair = syncPricePair;
})();

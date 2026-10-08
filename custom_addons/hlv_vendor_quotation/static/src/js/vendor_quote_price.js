/**
 * Hàm thuần quy đổi ba mức giá của một dòng báo giá NCC:
 *   giá trước chiết khấu × (1 − %CK) = đơn giá chưa VAT;  đơn giá chưa VAT × (1 + %VAT) = đơn giá sau VAT.
 * NCC gõ vào ô nào thì ô đó là "mốc", hai ô kia tính theo mốc. Server lưu đơn giá chưa VAT
 * (resolve_net_price trong models/vendor_quote_utils.py cùng công thức, dùng khi JS hỏng).
 *
 * Trang này không qua asset bundle của Odoo nên viết JS thường, gắn vào window.hlvVendorQuote.
 */
(function () {
    "use strict";

    function round2(value) {
        return Math.round(value * 100) / 100;
    }

    /**
     * Tính lại ba mức giá từ ô mốc.
     *   anchor: "list" | "net" | "gross" — ô NCC vừa gõ (hoặc gõ gần nhất).
     *   values: {list, net, gross} — số đang có trong ba ô (null khi trống).
     *   vatRate: % VAT (0 khi không chịu thuế / chưa chọn).
     *   discount: % chiết khấu, 0 khi không dùng chiết khấu; phải 0 ≤ discount < 100.
     * Trả {list, net, gross} làm tròn 2 chữ số lẻ; ô mốc giữ nguyên số NCC gõ. Mốc trống →
     * cả ba null. discount ngoài khoảng hợp lệ → null (để trang báo lỗi, không tính bừa).
     */
    function derivePrices(anchor, values, vatRate, discount) {
        if (discount == null || discount < 0 || discount >= 100) {
            return null;
        }
        const vatFactor = 1 + (vatRate || 0) / 100;
        const discountFactor = 1 - discount / 100;
        const own = values[anchor];
        if (own == null) {
            return { list: null, net: null, gross: null };
        }
        let net = own;
        if (anchor === "list") {
            net = round2(own * discountFactor);
        } else if (anchor === "gross") {
            net = round2(own / vatFactor);
        }
        return {
            list: anchor === "list" ? own : round2(net / discountFactor),
            net: net,
            gross: anchor === "gross" ? own : round2(net * vatFactor),
        };
    }

    window.hlvVendorQuote = Object.assign(window.hlvVendorQuote || {}, { derivePrices });
})();

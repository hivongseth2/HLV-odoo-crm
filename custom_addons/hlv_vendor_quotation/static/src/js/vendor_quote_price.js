/**
 * Hàm thuần tách đơn giá NCC gõ ra các mức giá, để trang hiện giá sau CK, thành tiền, tổng.
 * Cùng công thức với split_unit_price (models/vendor_quote_utils.py) — server tính lại từ đúng
 * con số NCC gõ khi lưu; sửa một bên thì sửa bên kia, kẻo số trên trang lệch số được lưu.
 *
 * Trang này không qua asset bundle của Odoo nên viết JS thường, gắn vào window.hlvVendorQuote.
 */
(function () {
    "use strict";

    function round2(value) {
        return Math.round(value * 100) / 100;
    }

    /**
     * unit: đơn giá NCC gõ, ĐÃ GỒM VAT — có chiết khấu thì là giá TRƯỚC chiết khấu (null khi trống);
     * vatRate: % VAT (0 khi không chịu thuế / chưa chọn); discount: % chiết khấu (0 khi không dùng).
     * Trả {after: giá sau CK đã gồm VAT, net: giá sau CK chưa VAT, listNet: giá trước CK chưa VAT},
     * làm tròn 2 chữ số lẻ. unit trống / 0 → null. discount ngoài 0 ≤ d < 100 → null.
     */
    function splitUnitPrice(unit, vatRate, discount) {
        if (!unit || discount == null || discount < 0 || discount >= 100) {
            return null;
        }
        const vatFactor = 1 + (vatRate || 0) / 100;
        const after = unit * (1 - discount / 100);
        return { after: round2(after), net: round2(after / vatFactor), listNet: round2(unit / vatFactor) };
    }

    /**
     * net: đơn giá chưa VAT (null khi trống); vatRate: % VAT (0 khi không chịu thuế / chưa chọn).
     * Trả đơn giá sau VAT làm tròn 2 chữ số lẻ — như price_incl_vat (models/vendor_quote_utils.py). net trống / 0 → null.
     */
    function inclVat(net, vatRate) {
        return net ? round2(net * (1 + (vatRate || 0) / 100)) : null;
    }

    /** Ngược của inclVat: đơn giá sau VAT → chưa VAT, làm tròn 2 chữ số lẻ. gross trống / 0 → null. */
    function exclVat(gross, vatRate) {
        return gross ? round2(gross / (1 + (vatRate || 0) / 100)) : null;
    }

    /**
     * Tiền một dòng đơn mua: net = đơn giá chưa VAT, qty = số lượng, vatRate = % VAT (trống coi như 0).
     * Trả {untaxed, tax, total} làm tròn 2 chữ số lẻ — thuế tính trên tiền trước VAT của dòng, như Odoo.
     */
    function lineAmounts(net, qty, vatRate) {
        const untaxed = round2((net || 0) * (qty || 0));
        const tax = round2(untaxed * (vatRate || 0) / 100);
        return { untaxed: untaxed, tax: tax, total: round2(untaxed + tax) };
    }

    window.hlvVendorQuote = Object.assign(window.hlvVendorQuote || {}, { splitUnitPrice, inclVat, exclVat, lineAmounts });
})();

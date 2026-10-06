/**
 * Hàm thuần đọc/viết số kiểu Việt Nam cho trang báo giá NCC.
 * Cùng quy tắc với parse_vn_number / format_vn_number trong models/vendor_quote_utils.py —
 * sửa một bên thì sửa bên kia, kẻo tổng tiền hiện trên trang lệch với số server lưu.
 *
 * Trang này không qua asset bundle của Odoo nên viết JS thường, gắn vào window.hlvVendorQuote.
 */
(function () {
    "use strict";

    /**
     * Nhận chuỗi NCC gõ ("1.250.000", "1,250,000", "12,5", "150000đ").
     * Trả số >= 0, hoặc null khi rỗng / không đọc được.
     * Một dấu chấm/phẩy đứng trước đúng 3 chữ số là phân cách nghìn ("1.250" = 1250).
     */
    function parseVnNumber(text) {
        let s = String(text == null ? "" : text).trim().replace(/[\s ]/g, "");
        s = s.replace(/(vn)?[dđ]$/i, "");
        if (!s || !/^[0-9.,]+$/.test(s) || !/[0-9]/.test(s)) {
            return null;
        }
        const hasDot = s.includes(".");
        const hasComma = s.includes(",");
        if (!hasDot && !hasComma) {
            return parseFloat(s);
        }
        if (hasDot && hasComma) {
            const decimalSep = s.lastIndexOf(".") > s.lastIndexOf(",") ? "." : ",";
            if (s.split(decimalSep).length > 2) {
                return null;
            }
            const thousandSep = decimalSep === "." ? "," : ".";
            const [intPart, decPart] = s.split(thousandSep).join("").split(decimalSep);
            return parseFloat(`${intPart || 0}.${decPart || 0}`);
        }
        const parts = s.split(hasDot ? "." : ",");
        if (parts.length > 2) {
            const valid = parts[0].length >= 1 && parts[0].length <= 3 &&
                parts.slice(1).every((p) => p.length === 3);
            return valid ? parseFloat(parts.join("")) : null;
        }
        const [intPart, tail] = parts;
        if (tail.length === 3 && intPart) {
            return parseFloat(intPart + tail);
        }
        return parseFloat(`${intPart || 0}.${tail || 0}`);
    }

    /**
     * Nhận số (hoặc null). Trả chuỗi "1.250.000" / "1.250,5" (tối đa 2 chữ số lẻ).
     * null / NaN → "".
     */
    function formatVnNumber(value) {
        if (value == null || Number.isNaN(value)) {
            return "";
        }
        const [intPart, decPart] = Number(value).toFixed(2).split(".");
        const sign = intPart.startsWith("-") ? "-" : "";
        const digits = sign ? intPart.slice(1) : intPart;
        const grouped = digits.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
        const decimals = decPart.replace(/0+$/, "");
        return sign + grouped + (decimals ? `,${decimals}` : "");
    }

    window.hlvVendorQuote = Object.assign(window.hlvVendorQuote || {}, {
        parseVnNumber,
        formatVnNumber,
    });
})();

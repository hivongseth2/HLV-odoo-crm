/**
 * Hàm thuần cho nhãn "Sẵn hàng" ở đầu ghi chú dòng báo giá NCC. Cùng luật với split_stock_note /
 * stock_note (models/vendor_quote_utils.py) — server ghép lại từ ô tick + ô ghi chú khi lưu; sửa
 * một bên thì sửa bên kia, kẻo chữ trên trang lệch chữ được lưu.
 *
 * Trang này không qua asset bundle của Odoo nên viết JS thường, gắn vào window.hlvVendorQuote.
 */
(function () {
    "use strict";

    const LABEL = "Sẵn hàng";
    const SEP = "; ";
    const LABEL_TAIL = ";,.-: ";

    /**
     * Ghi chú → {inStock: có nhãn "Sẵn hàng" ở đầu không, rest: phần còn lại}.
     * "Sẵn hàng; chính hãng" → {true, "chính hãng"}; "giao 3 ngày" → {false, "giao 3 ngày"};
     * "Sẵn hàngxyz" → {false, "Sẵn hàngxyz"}; null / "" → {false, ""}.
     */
    function splitStockNote(note) {
        const text = (note || "").trim();
        if (text.slice(0, LABEL.length).toLowerCase() !== LABEL.toLowerCase()) {
            return { inStock: false, rest: text };
        }
        const tail = text.slice(LABEL.length);
        if (tail && LABEL_TAIL.indexOf(tail[0]) < 0) {
            return { inStock: false, rest: text };
        }
        let start = 0;
        while (start < tail.length && LABEL_TAIL.indexOf(tail[start]) >= 0) {
            start += 1;
        }
        return { inStock: true, rest: tail.slice(start).trim() };
    }

    /** Ghi chú có (inStock) / không có nhãn "Sẵn hàng" ở đầu; không lặp nhãn. */
    function stockNote(inStock, note) {
        const rest = splitStockNote(note).rest;
        return inStock ? LABEL + (rest ? SEP + rest : "") : rest;
    }

    window.hlvVendorQuote = Object.assign(window.hlvVendorQuote || {}, { splitStockNote, stockNote });
})();

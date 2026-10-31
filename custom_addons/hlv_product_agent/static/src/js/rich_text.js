/** @odoo-module **/
/*
 * Đọc chữ trả lời của trợ lý thành các đoạn có định dạng: đậm, tô vàng, mã, link, ảnh.
 *
 * Util thuần: vào chuỗi, ra mảng dữ liệu — không đụng DOM. Khung chat tự dựng phần tử từ kết
 * quả bằng textContent / createElement, nên chữ Claude viết không bao giờ thành HTML chạy được.
 */

// **đậm**, ==tô vàng==, `mã`, ![ảnh](url), [link](url), link trần https://...
const INLINE = /\*\*([^*\n]+)\*\*|==([^=\n]+)==|`([^`\n]+)`|!\[([^\]\n]*)\]\(([^)\s]+)\)|\[([^\]\n]+)\]\(([^)\s]+)\)|(https?:\/\/[^\s<>()]+)/g;
// Ảnh / link nội bộ được phép: ảnh sản phẩm của trang tra tồn, ảnh Odoo, trang hỏi / tra giá NCC.
const LOCAL_PATHS = ["/search_stock/image/", "/web/image/", "/search_stock?", "/hoi-gia-ncc"];

/**
 * URL dùng được cho ảnh / link, hoặc null.
 * Nhận: chuỗi. Trả: URL nguyên văn nếu là https:// / http:// hoặc đường dẫn nội bộ cho phép.
 * Biên: javascript:, data:, đường dẫn lạ -> null (hiện như chữ thường).
 */
export function safeUrl(url) {
    const value = (url || "").trim();
    if (/^https?:\/\//i.test(value)) {
        return value;
    }
    return LOCAL_PATHS.some((path) => value.startsWith(path)) ? value : null;
}

// Số phiếu kho (KBC/CKN/00004, TSN/INT/02156), đơn bán DH..., đơn mua DMH..., đơn S0....
// Mã hàng có dấu "/" như (3/4"x20Y) NANO không khớp vì phải đủ 3 khúc chữ in / chữ in / số.
const DOCUMENT_NUMBER = /^(?:[A-Z]{2,6}\/[A-Z]{2,6}\/\d{3,}|DH\d{8,}|DMH\d{4,}|S\d{5})$/;

/**
 * Chữ có phải số phiếu / số đơn chứ không phải mã hàng không.
 * Nhận: chuỗi trong `...`. Trả: true nếu khớp dạng số phiếu / số đơn của Odoo HLV.
 * Biên: chuỗi rỗng / có khoảng trắng hai đầu -> xét sau khi trim; rỗng -> false.
 * Claude vẫn hay bọc số phiếu trong `...` dù prompt dặn không: link tra tồn của nó là trang trống.
 */
export function isDocumentNumber(text) {
    return DOCUMENT_NUMBER.test((text || "").trim());
}

/**
 * Các đoạn của một dòng.
 * Trả: mảng {type: 'text'|'bold'|'mark'|'code'|'image'|'link', text, url?}.
 * Biên: URL không an toàn -> đoạn 'text' giữ nguyên chữ gốc.
 */
function parseInline(line) {
    const parts = [];
    let last = 0;
    for (const match of line.matchAll(INLINE)) {
        if (match.index > last) {
            parts.push({ type: "text", text: line.slice(last, match.index) });
        }
        const [raw, bold, mark, code, alt, imageUrl, label, linkUrl, bare] = match;
        if (bold) {
            parts.push({ type: "bold", text: bold });
        } else if (mark) {
            parts.push({ type: "mark", text: mark });
        } else if (code) {
            parts.push({ type: "code", text: code });
        } else if (imageUrl !== undefined) {
            const url = safeUrl(imageUrl);
            parts.push(url ? { type: "image", text: alt, url } : { type: "text", text: raw });
        } else if (linkUrl !== undefined) {
            const url = safeUrl(linkUrl);
            parts.push(url ? { type: "link", text: label, url } : { type: "text", text: raw });
        } else {
            parts.push({ type: "link", text: bare, url: bare });
        }
        last = match.index + raw.length;
    }
    if (last < line.length) {
        parts.push({ type: "text", text: line.slice(last) });
    }
    return parts;
}

/**
 * Cả câu trả lời thành các dòng.
 * Nhận: chuỗi nhiều dòng. Trả: mảng {bullet: bool, parts: [...]}; dòng "- " / "• " là gạch đầu dòng.
 * Biên: chuỗi rỗng -> [].
 */
export function parseRich(text) {
    if (!text) {
        return [];
    }
    return text.split("\n").map((line) => {
        const bullet = /^\s*[-•]\s+/.test(line);
        return { bullet, parts: parseInline(bullet ? line.replace(/^\s*[-•]\s+/, "") : line) };
    });
}

// Dòng chỉ gồm các lựa chọn [[...]] — trợ lý gợi ý bước tiếp theo cho sale bấm thay vì gõ.
const OPTION_LINE = /^\s*(\[\[[^\]\n]+\]\]\s*)+$/;
const OPTION = /\[\[([^\]\n]+)\]\]/g;
const MAX_OPTIONS = 6;

/**
 * Tách các lựa chọn khỏi câu trả lời.
 * Nhận: chuỗi. Trả: {body: chuỗi còn lại, options: [chữ lựa chọn]} — lựa chọn lấy từ các dòng chỉ
 * gồm [[...]], bỏ dấu `, bỏ trùng, tối đa MAX_OPTIONS. [[...]] nằm giữa câu thì để nguyên trong body.
 * Biên: chuỗi rỗng -> {body: "", options: []}.
 */
export function splitOptions(text) {
    const options = [];
    const kept = [];
    for (const line of (text || "").split("\n")) {
        if (!OPTION_LINE.test(line)) {
            kept.push(line);
            continue;
        }
        for (const match of line.matchAll(OPTION)) {
            // Claude quen bọc mã trong `...` (để bấm mở trang tra tồn) cả trong nút; nút hiện chữ
            // thô và bấm là gửi nguyên chữ, nên bỏ dấu ` đi.
            const option = match[1].replace(/`/g, "").trim();
            if (option && !options.includes(option) && options.length < MAX_OPTIONS) {
                options.push(option);
            }
        }
    }
    return { body: kept.join("\n").trim(), options };
}

/** @odoo-module **/
/*
 * Dựng phần tử và chữ hiển thị cho khung chat trợ lý: tin có định dạng, bảng, ngày giờ, dòng chờ.
 *
 * Tách khỏi product_chat.js (widget: đồng bộ với Odoo + sự kiện) cho file dưới giới hạn độ dài.
 * Chữ Claude viết chỉ đi qua createElement / textContent, không bao giờ innerHTML.
 */
import { isDocumentNumber, parseRich } from "@hlv_product_agent/js/rich_text";

// Khung HTML cho bảng trợ lý: style nền tảng để bảng Claude dựng nhìn gọn dù nó quên style.
const BOARD_BASE_CSS =
    "body{margin:0;padding:14px;font:13px/1.45 system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;" +
    "color:#1f2933;background:#fff}table{border-collapse:collapse;width:100%;margin:6px 0}" +
    "th,td{border:1px solid #d9dee3;padding:5px 8px;vertical-align:top}" +
    "th{background:#e8f1fb;color:#0d4c8c;text-align:left}h1,h2,h3{color:#0d4c8c;margin:8px 0}";

export function boardDocument(html) {
    return `<!doctype html><html><head><meta charset="utf-8"><style>${BOARD_BASE_CSS}</style>` +
        `</head><body>${html}</body></html>`;
}

/**
 * Dựng chữ có định dạng (đậm, tô vàng, mã, link, ảnh) từ parseRich — chỉ createElement /
 * textContent, không innerHTML: chữ Claude viết không bao giờ thành HTML chạy được.
 */
export function renderRich(content) {
    const fragment = document.createDocumentFragment();
    for (const line of parseRich(content)) {
        const row = document.createElement("div");
        row.className = line.bullet ? "hlv-pa-line hlv-pa-bullet" : "hlv-pa-line";
        for (const part of line.parts) {
            row.appendChild(renderPart(part));
        }
        if (!line.parts.length) {
            row.appendChild(document.createElement("br"));
        }
        fragment.appendChild(row);
    }
    return fragment;
}

function renderPart(part) {
    if (part.type === "text") {
        return document.createTextNode(part.text);
    }
    if (part.type === "image") {
        const link = document.createElement("a");
        link.href = part.url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        const img = document.createElement("img");
        img.className = "hlv-pa-rich-img";
        img.src = part.url;
        img.alt = part.text || "ảnh";
        img.loading = "lazy";
        img.referrerPolicy = "no-referrer";
        link.appendChild(img);
        return link;
    }
    if (part.type === "link") {
        const link = document.createElement("a");
        link.href = part.url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = part.text;
        return link;
    }
    if (part.type === "code") {
        return codeLink(part.text);
    }
    const tag = { bold: "strong", mark: "mark" }[part.type];
    const node = document.createElement(tag);
    node.textContent = part.text;
    return node;
}

/**
 * Mã hàng trong `...` thành link mở trang tra tồn đúng mã đó, cùng tab như lệnh mở trang của
 * trợ lý: sale bấm là thấy tồn, giá, ảnh của mã ngay, khỏi gõ lại. Khung chat nạp lại lịch sử
 * từ server nên tải lại trang không mất cuộc chat.
 */
function codeLink(code) {
    const node = document.createElement("code");
    node.textContent = code;
    const url = isDocumentNumber(code) ? null : searchUrl({ type: "search", q: code.trim() });
    if (!url) {
        return node;
    }
    const link = document.createElement("a");
    link.className = "hlv-pa-code-link";
    link.href = url;
    link.title = "Mở mã này trên trang tra tồn";
    link.appendChild(node);
    return link;
}

/**
 * Hàng nút lựa chọn dưới câu trả lời của trợ lý; bấm nút = gửi đúng chữ trên nút.
 */
export function buildOptions(options) {
    const box = document.createElement("div");
    box.className = "hlv-pa-options";
    for (const option of options) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "hlv-pa-option";
        button.dataset.option = option;
        button.textContent = option;
        box.appendChild(button);
    }
    return box;
}

/**
 * Màn chào của cuộc chat trống. Không bày sẵn danh sách việc: việc nên làm tuỳ từng mã nên để
 * trợ lý tra rồi tự đưa lựa chọn. Chỉ có một nút hỏi về từ khoá sale đang tìm trên trang.
 * Nhận: từ khoá đang tìm (có thể rỗng). Biên: rỗng / toàn khoảng trắng -> không có nút.
 */
export function buildWelcome(query) {
    const welcome = document.createElement("div");
    welcome.className = "hlv-pa-welcome";
    const intro = document.createElement("div");
    intro.className = "hlv-pa-welcome-intro";
    intro.textContent =
        "Hỏi tồn kho, ai đang giữ, giá, mã thay thế, NCC, tạo / sửa mã hàng... " +
        "Hoặc bấm ✦ cạnh mã trong bảng để hỏi nhanh về mã đó.";
    welcome.appendChild(intro);
    const q = (query || "").trim();
    if (q) {
        welcome.appendChild(buildOptions([`Hỏi về "${q}"`]));
    }
    return welcome;
}

/**
 * Gắn nút ✦ vào ô mã của từng dòng bảng tra tồn; nút mang sẵn mã (data-code) để khung chat gửi
 * hỏi về đúng mã đó. Biên: dòng không có mã thì bỏ qua.
 */
export function addRowAskButtons(table) {
    for (const row of table.querySelectorAll("tr.main-row")) {
        const codeCell = row.cells[2];
        const code = codeCell ? codeCell.textContent.trim() : "";
        if (!code) {
            continue;
        }
        const button = document.createElement("button");
        button.type = "button";
        button.className = "hlv-pa-row-ask";
        button.title = "Hỏi trợ lý về mã này";
        button.textContent = "✦";
        button.dataset.code = code;
        codeCell.appendChild(button);
    }
}

export function paneNote(text) {
    const note = document.createElement("div");
    note.className = "hlv-pa-pane-note";
    note.textContent = text;
    return note;
}

export function formatDateTime(utcString) {
    if (!utcString) {
        return "";
    }
    const date = new Date(utcString.replace(" ", "T") + "Z");
    return date.toLocaleString("vi-VN", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

/**
 * URL trang tra tồn tìm đúng từ khoá, giữ nguyên trang đang mở (vd /en/search_stock).
 * Nhận: lệnh {type: 'search', q}. Biên: lệnh lạ / thiếu q -> null.
 */
export function searchUrl(action) {
    if (!action || action.type !== "search" || !action.q) {
        return null;
    }
    const url = new URL(window.location.href);
    url.search = "";
    url.searchParams.set("q", action.q);
    return url.toString();
}

/**
 * Dòng báo trạng thái chờ dưới tin cuối.
 * Nhận: state từ server. Trả: chuỗi, hoặc "" khi không chờ gì.
 */
export function waitingText(state) {
    if (state.processing) {
        return "Trợ lý đang kiểm tra...";
    }
    if (!state.busy) {
        return "";
    }
    if (state.queue_ahead) {
        return `Đang xếp hàng: trước anh/chị còn ${state.queue_ahead} cuộc chat.`;
    }
    return "Đang chờ trợ lý nhận tin...";
}

export function readFileAsBase64(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(file);
    });
}

export function formatTime(utcString) {
    if (!utcString) {
        return "";
    }
    // Odoo trả "YYYY-MM-DD HH:MM:SS" theo UTC, không kèm múi giờ.
    const date = new Date(utcString.replace(" ", "T") + "Z");
    return date.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" });
}

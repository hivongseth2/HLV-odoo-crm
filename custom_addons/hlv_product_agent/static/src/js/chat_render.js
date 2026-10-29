/** @odoo-module **/
/*
 * Dựng phần tử và chữ hiển thị cho khung chat trợ lý: tin có định dạng, bảng, ngày giờ, dòng chờ.
 *
 * Tách khỏi product_chat.js (widget: đồng bộ với Odoo + sự kiện) cho file dưới giới hạn độ dài.
 * Chữ Claude viết chỉ đi qua createElement / textContent, không bao giờ innerHTML.
 */
import { parseRich } from "@hlv_product_agent/js/rich_text";

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
    const tag = { bold: "strong", mark: "mark", code: "code" }[part.type];
    const node = document.createElement(tag);
    node.textContent = part.text;
    return node;
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

/** @odoo-module **/
/*
 * Dựng phần tử cho trang trợ lý quản trị: tin nhắn, mục cuộc chat ở cột trái, màn chào, ảnh chờ gửi.
 *
 * Chữ trợ lý viết đi qua renderRich của trợ lý tạo mã (createElement / textContent, không bao giờ
 * innerHTML) — cùng định dạng đậm / tô vàng / mã / link / nút lựa chọn [[...]].
 */
import { buildOptions, formatDateTime, formatTime, renderRich } from "@hlv_product_agent/js/chat_render";
import { splitOptions } from "@hlv_product_agent/js/rich_text";

// Trang tra tồn của website_public_inventory_18: mã hàng trong `...` mở trang này đúng mã.
const SEARCH_PAGE = "/search_stock";

const WELCOME_OPTIONS = [
    "Tạo báo giá cho khách",
    "Tạo cơ hội cho khách",
    "Xem báo giá gần đây của một khách",
    "Tra tồn và giá một mã hàng",
];

/**
 * Mã hàng trong `...`: renderRich dựng link tới chính trang đang mở (?q=mã) — đúng với trang tra
 * tồn, sai với trang này. Trỏ lại sang trang tra tồn, mở tab mới để không rời cuộc chat.
 */
function pointCodeLinksToSearchPage(root) {
    for (const link of root.querySelectorAll("a.hlv-pa-code-link")) {
        const url = new URL(SEARCH_PAGE, window.location.origin);
        url.searchParams.set("q", link.textContent.trim());
        link.href = url.toString();
        link.target = "_blank";
        link.rel = "noopener";
    }
}

/**
 * Một tin nhắn.
 * Nhận: tin từ server ({id, role, content, image_ids, date, action}); withOptions: dựng nút lựa
 * chọn [[...]] không (chỉ câu trả lời mới nhất). Trả: phần tử .hlv-aa-msg.
 */
export function buildMessage(message, { withOptions = false } = {}) {
    const item = document.createElement("div");
    item.className = `hlv-aa-msg hlv-aa-msg-${message.role}`;
    if (message.content) {
        const text = document.createElement("div");
        text.className = "hlv-pa-text";
        let choices = [];
        if (message.role === "assistant") {
            const parsed = splitOptions(message.content);
            text.appendChild(renderRich(parsed.body));
            pointCodeLinksToSearchPage(text);
            choices = withOptions ? parsed.options : [];
        } else {
            // Chữ người dùng gõ và ghi chú hệ thống để nguyên văn.
            text.textContent = message.content;
        }
        item.appendChild(text);
        if (choices.length) {
            item.appendChild(buildOptions(choices));
        }
    }
    if (message.action && message.action.type === "panel") {
        const open = document.createElement("button");
        open.type = "button";
        open.className = "hlv-aa-msg-action";
        open.dataset.messageId = message.id;
        open.textContent = "Mở bảng";
        item.appendChild(open);
    }
    for (const imageId of message.image_ids || []) {
        const link = document.createElement("a");
        link.href = `/web/content/${imageId}`;
        link.target = "_blank";
        const img = document.createElement("img");
        img.className = "hlv-aa-attachment";
        img.src = `/web/image/${imageId}/480x480`;
        img.alt = "ảnh đính kèm";
        link.appendChild(img);
        item.appendChild(link);
    }
    const time = document.createElement("div");
    time.className = "hlv-aa-time";
    time.textContent = formatTime(message.date);
    item.appendChild(time);
    return item;
}

/**
 * Một mục ở cột trái. Nhận: {id, name, date, busy}, id cuộc đang mở. Nút sửa tên / xoá mang id.
 */
export function buildSessionItem(session, activeId) {
    const item = document.createElement("div");
    item.className = "hlv-aa-session" + (session.id === activeId ? " active" : "");
    item.dataset.id = session.id;
    item.title = `${session.name} — ${formatDateTime(session.date)}`;
    const name = document.createElement("span");
    name.className = "hlv-aa-session-name";
    name.textContent = session.name;
    item.appendChild(name);
    if (session.busy) {
        const dot = document.createElement("span");
        dot.className = "hlv-aa-session-busy";
        dot.title = "Trợ lý đang trả lời";
        item.appendChild(dot);
    }
    const tools = document.createElement("span");
    tools.className = "hlv-aa-session-tools";
    for (const [action, icon, label] of [["rename", "fa-pencil", "Đổi tên"], ["delete", "fa-trash-o", "Xoá"]]) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = `hlv-aa-session-${action}`;
        button.dataset.id = session.id;
        button.title = label;
        const i = document.createElement("i");
        i.className = `fa ${icon}`;
        button.appendChild(i);
        tools.appendChild(button);
    }
    item.appendChild(tools);
    return item;
}

export function buildWelcome(userName) {
    const welcome = document.createElement("div");
    welcome.className = "hlv-aa-welcome";
    const title = document.createElement("h2");
    title.textContent = userName ? `Chào ${userName}, cần làm gì hôm nay?` : "Cần làm gì hôm nay?";
    const intro = document.createElement("div");
    intro.textContent = "Báo giá, cơ hội trên MISA CRM · tồn kho, giá, lịch sử · tạo mã hàng · tìm trên web";
    welcome.append(title, intro, buildOptions(WELCOME_OPTIONS));
    return welcome;
}

/**
 * Ảnh chờ gửi. Nhận: {previewUrl}, vị trí trong danh sách (nút bỏ mang vị trí này).
 */
export function buildPreview(image, index) {
    const box = document.createElement("div");
    box.className = "hlv-aa-preview";
    const img = document.createElement("img");
    img.src = image.previewUrl;
    img.alt = "ảnh chờ gửi";
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "hlv-aa-preview-remove";
    remove.dataset.index = index;
    remove.textContent = "×";
    box.append(img, remove);
    return box;
}

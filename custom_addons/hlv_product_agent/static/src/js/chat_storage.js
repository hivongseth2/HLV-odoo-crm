/** @odoo-module **/
/*
 * Nhớ theo trình duyệt cho khung chat trợ lý: người đang chat (tài khoản dùng chung) và độ rộng
 * cột chat. Storage có thể bị chặn (ẩn danh) -> không nhớ được thì thôi, không lỗi.
 */

// Người đang chat trên tài khoản dùng chung. Nhớ theo trình duyệt vì mỗi sale ngồi một
// máy; storage có thể bị chặn (chế độ ẩn danh) -> không nhớ được thì hỏi lại, không lỗi.
const SALE_KEY_STORAGE = "hlv_pa_sale_key";

export function loadSaleKey() {
    try {
        return window.localStorage.getItem(SALE_KEY_STORAGE) || "";
    } catch {
        return "";
    }
}

export function saveSaleKey(key) {
    try {
        if (key) {
            window.localStorage.setItem(SALE_KEY_STORAGE, key);
        } else {
            window.localStorage.removeItem(SALE_KEY_STORAGE);
        }
    } catch {
        // Không lưu được: lần sau mở trang hỏi lại, chấp nhận được.
    }
}

// Độ rộng khung chat kéo bằng chuột, nhớ theo trình duyệt. Chặn hai đầu để không kéo mất
// ngăn kéo hay che hết bảng tra tồn.
const DRAWER_WIDTH_STORAGE = "hlv_pa_drawer_width";
const DRAWER_MIN_WIDTH = 300;
const DRAWER_MAX_RATIO = 0.38;

/**
 * Độ rộng hợp lệ (px). Nhận số bất kỳ; biên: không phải số -> null.
 */
function clampDrawerWidth(width) {
    const value = Number(width);
    if (!Number.isFinite(value) || value <= 0) {
        return null;
    }
    return Math.round(Math.min(Math.max(value, DRAWER_MIN_WIDTH), window.innerWidth * DRAWER_MAX_RATIO));
}

export function applyDrawerWidth(width) {
    const value = clampDrawerWidth(width);
    if (value) {
        document.documentElement.style.setProperty("--pa-drawer-width", value + "px");
    }
    return value;
}

export function loadDrawerWidth() {
    try {
        return window.localStorage.getItem(DRAWER_WIDTH_STORAGE);
    } catch {
        return null;
    }
}

export function saveDrawerWidth(width) {
    try {
        window.localStorage.setItem(DRAWER_WIDTH_STORAGE, String(width));
    } catch {
        // Không lưu được: lần sau về độ rộng mặc định.
    }
}

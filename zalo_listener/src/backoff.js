// Hàm thuần quyết định chờ bao lâu / làm gì khi đăng nhập hỏng hay bị rớt kết nối. Mọi con số lấy từ sự cố đã
// chạy thật (tài liệu vận hành máy nghe): đăng nhập dồn dập là kiểu Zalo dò để khoá tài khoản.
"use strict";

const MINUTE = 60 * 1000;
// Đăng nhập lại: 30 giây → 1 → 3 → 10 → 30 phút.
const LOGIN_DELAYS = [30 * 1000, MINUTE, 3 * MINUTE, 10 * MINUTE, 30 * MINUTE];
// Nối lại sau khi rớt: 5 giây → 15 giây → 60 giây → 5 phút.
const RECONNECT_DELAYS = [5 * 1000, 15 * 1000, MINUTE, 5 * MINUTE];
// Mã 3000 (tài khoản đang mở ở chỗ khác): chờ hẳn 5 phút, nối ngay là hai bên đá nhau mãi.
const DUPLICATE_WAIT = 5 * MINUTE;
// Kết nối phải đứng vững chừng này mới coi là ổn và xoá bộ đếm lỗi (sự cố kẹt 17 tiếng: xoá ngay khi nối lại).
const STABLE_MS = MINUTE;
// Rớt liên tiếp chừng này lần mới đăng nhập lại (bằng cookie cũ).
const RELOGIN_AFTER = 10;
// Hiện QR tối đa 3 lần mỗi giờ.
const QR_PER_HOUR = 3;
const HOUR = 60 * MINUTE;

const CLOSE = { MANUAL: 1000, ABNORMAL: 1006, DUPLICATE: 3000, KICKED: 3003 };

const NETWORK_CODES = new Set([
    "ENOTFOUND", "ECONNRESET", "ECONNREFUSED", "ETIMEDOUT", "EAI_AGAIN", "ENETUNREACH", "EHOSTUNREACH", "EPIPE",
    "UND_ERR_CONNECT_TIMEOUT", "UND_ERR_SOCKET", "UND_ERR_HEADERS_TIMEOUT",
]);

/** delays[attempt], quá cuối danh sách thì lấy phần tử cuối. attempt < 0 / không phải số → phần tử đầu. */
function pickDelay(delays, attempt) {
    const index = Number.isInteger(attempt) && attempt > 0 ? attempt : 0;
    return delays[Math.min(index, delays.length - 1)];
}

/** Còn được hiện QR không: số lần hiện trong 1 giờ qua (history = mốc ms) < QR_PER_HOUR. */
function qrAllowed(history, now) {
    return (history || []).filter((t) => now - t < HOUR).length < QR_PER_HOUR;
}

/** Bao lâu nữa mới được hiện QR (ms); 0 nếu được ngay. */
function qrWait(history, now) {
    const recent = (history || []).filter((t) => now - t < HOUR).sort((a, b) => a - b);
    return recent.length < QR_PER_HOUR ? 0 : recent[recent.length - QR_PER_HOUR] + HOUR - now;
}

/**
 * Lỗi mạng (mất mạng, DNS, timeout) — KHÁC lỗi xác thực. Lỗi mạng thì chỉ chờ rồi thử lại bằng cookie cũ, tuyệt
 * đối không hiện QR (sự cố cũ: mất mạng bị tưởng là phiên hết hạn → QR → thoát → pm2 bật lại → lặp).
 */
function isNetworkError(error) {
    if (!error) {
        return false;
    }
    const codes = [error.code, error.cause && error.cause.code, error.errno].filter(Boolean).map(String);
    if (codes.some((code) => NETWORK_CODES.has(code))) {
        return true;
    }
    return /fetch failed|network|socket hang up|timed? ?out|getaddrinfo|EAI_AGAIN|ECONN/i.test(String(error.message || error));
}

/**
 * Việc cần làm khi kết nối nghe bị đóng. code: mã đóng WebSocket; failures: số lần rớt liên tiếp (chưa tính lần này).
 * Trả {action: "stop" | "reconnect" | "relogin", wait: ms, reason}.
 */
function onClose(code, failures) {
    if (code === CLOSE.MANUAL) {
        return { action: "stop", wait: 0, reason: "dừng chủ động" };
    }
    if (code === CLOSE.KICKED) {
        // Đổi mật khẩu / đăng nhập thiết bị mới trên số máy nghe: phải có người xem, không tự đăng nhập lại.
        return { action: "stop", wait: 0, reason: "bị Zalo đá ra (3003)" };
    }
    if (code === CLOSE.DUPLICATE) {
        return { action: "reconnect", wait: DUPLICATE_WAIT, reason: "tài khoản đang mở ở chỗ khác (3000)" };
    }
    const next = failures + 1;
    return {
        action: next >= RELOGIN_AFTER ? "relogin" : "reconnect",
        wait: pickDelay(RECONNECT_DELAYS, failures),
        reason: `rớt kết nối (${code}), lần ${next} liên tiếp`,
    };
}

module.exports = {
    LOGIN_DELAYS, RECONNECT_DELAYS, DUPLICATE_WAIT, STABLE_MS, RELOGIN_AFTER, QR_PER_HOUR, CLOSE,
    pickDelay, qrAllowed, qrWait, isNetworkError, onClose,
};

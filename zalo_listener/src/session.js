// Đăng nhập tài khoản máy nghe: cookie đã lưu trước; chỉ hiện QR khi cookie hỏng do XÁC THỰC (không phải lỗi mạng)
// và chưa quá 3 lần QR trong 1 giờ. Mọi lần hiện QR được ghi ra file để đếm qua cả các lần khởi động lại.
"use strict";

const fs = require("fs");
const { LoginQRCallbackEventType } = require("zca-js");
const { isNetworkError, qrAllowed, qrWait } = require("./backoff");

class QrLimitError extends Error {
    constructor(waitMs) {
        super(`Đã hiện QR đủ số lần cho phép trong 1 giờ — chờ ${Math.ceil(waitMs / 60000)} phút`);
        this.waitMs = waitMs;
    }
}

function readJson(file, fallback) {
    try {
        return JSON.parse(fs.readFileSync(file, "utf8"));
    } catch {
        return fallback;
    }
}

function writePrivate(file, data) {
    fs.writeFileSync(file, JSON.stringify(data), { mode: 0o600 });
    fs.chmodSync(file, 0o600); // file đã có từ trước giữ quyền cũ — ép lại
}

/**
 * Đăng nhập; trả API của zca-js. Lỗi mạng → ném lỗi ngay (nơi gọi chờ rồi thử lại bằng cookie, không QR).
 * Quá giới hạn QR → ném QrLimitError (có waitMs).
 */
async function login(zalo, config, log) {
    const credentials = readJson(config.credentialsPath, null);
    if (credentials) {
        try {
            const api = await zalo.login(credentials);
            log.info("Đăng nhập bằng cookie đã lưu: OK");
            return api;
        } catch (error) {
            if (isNetworkError(error)) {
                throw error;
            }
            log.warn("Cookie không dùng được (lỗi xác thực) — sẽ cần quét QR:", error.message);
        }
    }
    const now = Date.now();
    const history = readJson(config.qrHistoryPath, []);
    if (!qrAllowed(history, now)) {
        throw new QrLimitError(qrWait(history, now));
    }
    writePrivate(config.qrHistoryPath, history.concat([now]).filter((t) => now - t < 24 * 3600 * 1000));
    try {
        // zca-js 2.2.0: có callback thì hết hạn / từ chối KHÔNG tự xử lý — từ chối mà không abort() là treo mãi.
        // Hết hạn (100 giây) cũng dừng, không tự tạo QR mới: mỗi QR mới là một lần đăng nhập Zalo đếm được.
        const api = await zalo.loginQR({ qrPath: config.qrPath }, async (event) => {
            if (event.type === LoginQRCallbackEventType.QRCodeGenerated) {
                await event.actions.saveToFile(config.qrPath);
                log.warn(`CẦN QUÉT QR: mở ${config.qrPath}, quét bằng app Zalo của SỐ MÁY NGHE (không dùng số chính).`);
            } else if (event.type === LoginQRCallbackEventType.QRCodeExpired) {
                log.warn("QR hết hạn — dừng lượt này, lượt đăng nhập sau mới hiện QR mới.");
                event.actions.abort();
            } else if (event.type === LoginQRCallbackEventType.QRCodeDeclined) {
                log.warn("Đã bấm từ chối trên điện thoại — dừng lượt này.");
                event.actions.abort();
            } else if (event.type === LoginQRCallbackEventType.GotLoginInfo) {
                writePrivate(config.credentialsPath, event.data);
            }
        });
        log.info("Đăng nhập bằng QR: OK, đã lưu cookie");
        return api;
    } finally {
        fs.rmSync(config.qrPath, { force: true }); // ảnh QR không để lại trên máy
    }
}

module.exports = { login, QrLimitError };

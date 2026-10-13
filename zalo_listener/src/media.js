// Tải ảnh / file đính kèm về máy NGAY khi nhận tin: link CDN của Zalo hết hạn sau một thời gian.
"use strict";

const fs = require("fs");
const path = require("path");

const MAX_BYTES = 25 * 1024 * 1024; // khớp giới hạn Odoo nhận (controllers/zalo_ingest.py)
const TIMEOUT_MS = 60 * 1000;

/** Tên file an toàn cho ổ đĩa: bỏ ký tự đường dẫn / điều khiển, giữ đuôi; trống → "file". */
function safeName(name) {
    const cleaned = String(name || "").replace(/[\\/:*?"<>|\x00-\x1f]/g, "_").trim().slice(-120);
    return cleaned || "file";
}

/** Tên file cho tin: tiêu đề Zalo nếu có (file), không thì đuôi lấy từ link (ảnh). */
function fileNameFor(msgId, attachment) {
    if (attachment.title && /\.[A-Za-z0-9]{1,8}$/.test(attachment.title)) {
        return `${msgId}_${safeName(attachment.title)}`;
    }
    const ext = (new URL(attachment.href).pathname.match(/\.([A-Za-z0-9]{1,8})$/) || [])[1] || "jpg";
    return `${msgId}.${ext.toLowerCase()}`;
}

/** Tải attachment.href về mediaDir; trả đường dẫn file. Lỗi / quá cỡ → ném lỗi (nơi gọi đánh dấu failed). */
async function download(mediaDir, msgId, attachment) {
    fs.mkdirSync(mediaDir, { recursive: true });
    const response = await fetch(attachment.href, { signal: AbortSignal.timeout(TIMEOUT_MS) });
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
    }
    const declared = Number(response.headers.get("content-length") || 0);
    if (declared > MAX_BYTES) {
        throw new Error(`file quá cỡ (${declared} byte)`);
    }
    const data = Buffer.from(await response.arrayBuffer());
    if (data.length > MAX_BYTES) {
        throw new Error(`file quá cỡ (${data.length} byte)`);
    }
    const target = path.join(mediaDir, fileNameFor(msgId, attachment));
    fs.writeFileSync(target, data, { mode: 0o600 });
    return target;
}

module.exports = { download, fileNameFor, safeName, MAX_BYTES };

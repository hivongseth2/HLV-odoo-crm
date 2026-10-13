// Máy nghe nhóm Zalo có NCC → SQLite trên máy → Odoo (hlv_vendor_zalo). CHỈ ĐỌC: không có chỗ nào gửi tin Zalo.
"use strict";

const fs = require("fs");
const { Zalo } = require("zca-js");
const { loadConfig } = require("./config");
const { createLogger } = require("./log");
const { Store } = require("./store");
const { OdooClient } = require("./odoo");
const media = require("./media");
const { login, QrLimitError } = require("./session");
const { Runner } = require("./listen");
const { LOGIN_DELAYS, pickDelay, isNetworkError } = require("./backoff");

// Không có tin mới vẫn báo trạng thái về Odoo mỗi phút — Odoo dựa vào đó biết máy nghe còn sống.
const STATUS_EVERY_MS = 60 * 1000;
const BATCH = 200; // tin + thả cảm xúc mỗi lô ≤ 400, dưới giới hạn 500 của Odoo
const DOWNLOAD_EVERY_MS = 3000;
const UPLOADS_PER_PUSH = 5;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function localDay() {
    const now = new Date();
    return `${now.getFullYear()}-${now.getMonth() + 1}-${now.getDate()}`;
}

/** Thư mục dữ liệu 700, cookie / DB / lịch sử QR 600 — làm mới cookie có thể làm file tụt về 644, nên ép mỗi lần chạy. */
function secureFiles(config, log) {
    try {
        fs.chmodSync(config.dataDir, 0o700);
        for (const file of [config.credentialsPath, config.dbPath, config.qrHistoryPath, config.failedPath]) {
            if (fs.existsSync(file)) {
                fs.chmodSync(file, 0o600);
            }
        }
    } catch (error) {
        log.warn("Không đổi được quyền file dữ liệu:", error.message);
    }
}

async function main() {
    const config = loadConfig();
    fs.mkdirSync(config.dataDir, { recursive: true, mode: 0o700 });
    const log = createLogger(config.logDir);
    secureFiles(config, log);
    const odoo = new OdooClient(config.odooUrl, config.odooKey);
    const store = new Store(config.dbPath, config.failedPath, log);
    const status = {
        state: "login_wait", connected_since: 0, last_close_code: 0, last_close_at: 0, drops_today: 0,
        last_error: "", day: localDay(),
    };
    const zalo = new Zalo({ selfListen: true, checkUpdate: false, logging: false });
    let runner = null;

    async function connect() {
        for (let attempt = 0; ; attempt += 1) {
            status.state = "login_wait";
            try {
                const api = await login(zalo, config, log);
                status.last_error = "";
                runner = new Runner({ api, store, status, config, log, relogin: connect });
                runner.start();
                return;
            } catch (error) {
                const wait = error instanceof QrLimitError ? error.waitMs : pickDelay(LOGIN_DELAYS, attempt);
                status.last_error = `${isNetworkError(error) ? "mạng" : "đăng nhập"}: ${error.message}`.slice(0, 250);
                log.warn(`Đăng nhập không được (${status.last_error}) — thử lại sau ${Math.round(wait / 1000)} giây`);
                await sleep(wait);
            }
        }
    }

    function statusPayload() {
        if (status.day !== localDay()) {
            status.day = localDay();
            status.drops_today = 0;
        }
        return {
            state: status.state,
            connected_since: status.connected_since || null,
            last_close_code: status.last_close_code || null,
            last_close_at: status.last_close_at || null,
            drops_today: status.drops_today,
            outbox: store.outboxSize(),
            version: config.version,
            last_error: status.last_error,
        };
    }

    async function uploadMedia() {
        for (const item of store.mediaToUpload(UPLOADS_PER_PUSH)) {
            if (item.state === "downloaded") {
                await odoo.uploadMedia(item.msgId, item.path);
            } else {
                await odoo.reportMediaFailed(item.msgId);
            }
            store.markMediaSent(item.msgId);
        }
    }

    let pushing = false;
    let lastPushAt = 0;
    async function pushOnce() {
        if (pushing) {
            return;
        }
        pushing = true;
        try {
            const messages = store.unpushedMessages(BATCH);
            const reactions = store.unpushedReactions(BATCH);
            if (messages.length || reactions.length || Date.now() - lastPushAt >= STATUS_EVERY_MS) {
                const result = await odoo.sendEvents({
                    listener: config.listenerName,
                    status: statusPayload(),
                    messages: messages,
                    reactions: reactions.map((item) => item.payload),
                });
                store.markPushed(messages.map((m) => m.msg_id), reactions.map((item) => item.key), result.media_wanted || []);
                lastPushAt = Date.now();
                if (messages.length) {
                    log.info(`Đã gửi Odoo ${messages.length} tin (lưu ${result.stored}, trùng ${result.duplicate}, nhóm chưa bật ${result.skipped})`);
                }
            }
            await uploadMedia();
        } catch (error) {
            log.warn("Gửi Odoo lỗi — tin vẫn giữ trên máy, lượt sau gửi lại:", error.message);
        } finally {
            pushing = false;
        }
    }

    let downloading = false;
    async function downloadPending() {
        if (downloading) {
            return;
        }
        downloading = true;
        try {
            for (const item of store.pendingDownloads(10)) {
                try {
                    store.setMedia(item.msgId, "downloaded", await media.download(config.mediaDir, item.msgId, item.payload.attachment));
                } catch (error) {
                    store.setMedia(item.msgId, "failed");
                    log.warn(`Không tải được file của tin ${item.msgId}:`, error.message);
                }
            }
        } finally {
            downloading = false;
        }
    }

    function shutdown(signal) {
        log.info(`Nhận ${signal} — dừng máy nghe`);
        if (runner) {
            runner.stop();
        }
        store.close();
        process.exit(0);
    }
    process.on("SIGINT", () => shutdown("SIGINT"));
    process.on("SIGTERM", () => shutdown("SIGTERM"));
    // Lỗi lọt ra ngoài: ghi log, KHÔNG thoát — thoát là pm2 bật lại và đăng nhập lại.
    process.on("unhandledRejection", (error) => log.error("Lỗi chưa bắt (unhandledRejection):", error));
    process.on("uncaughtException", (error) => log.error("Lỗi chưa bắt (uncaughtException):", error));

    setInterval(pushOnce, config.pushIntervalMs);
    setInterval(downloadPending, DOWNLOAD_EVERY_MS);
    log.info(`Máy nghe ${config.listenerName} v${config.version} khởi động — Odoo ${config.odooUrl}`);
    await connect();
}

main().catch((error) => {
    // Lỗi khởi động (thiếu .env, DB hỏng…): chờ 60 giây rồi mới thoát, để pm2 không bật lại tức thì thành vòng lặp.
    console.error("Không khởi động được máy nghe:", error);
    setTimeout(() => process.exit(1), 60 * 1000);
});

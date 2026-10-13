// Cấu hình đọc từ file .env (cạnh package.json) + biến môi trường (biến môi trường thắng). Không dùng thư viện
// dotenv để máy nghe ít phụ thuộc nhất có thể.
"use strict";

const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");

function readEnvFile(file) {
    const values = {};
    if (!fs.existsSync(file)) {
        return values;
    }
    for (const line of fs.readFileSync(file, "utf8").split(/\r?\n/)) {
        const match = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$/);
        if (match && !line.trim().startsWith("#")) {
            values[match[1]] = match[2].replace(/^["']|["']$/g, "");
        }
    }
    return values;
}

function loadConfig() {
    const env = Object.assign(readEnvFile(path.join(ROOT, ".env")), process.env);
    const dataDir = path.resolve(ROOT, env.DATA_DIR || "./data");
    return {
        odooUrl: (env.ODOO_URL || "").replace(/\/+$/, ""),
        odooKey: env.ODOO_KEY || "",
        listenerName: env.LISTENER_NAME || "may-nghe-1",
        pushIntervalMs: Math.max(5, parseInt(env.PUSH_INTERVAL_S || "15", 10) || 15) * 1000,
        dataDir: dataDir,
        dbPath: path.join(dataDir, "zalo.db"),
        credentialsPath: path.join(dataDir, "credentials.json"),
        qrPath: path.join(dataDir, "qr.png"),
        qrHistoryPath: path.join(dataDir, "qr_history.json"),
        mediaDir: path.join(dataDir, "media"),
        logDir: path.join(dataDir, "logs"),
        failedPath: path.join(dataDir, "failed.jsonl"),
        // Công tắc tắt nhanh: tạo file này trong DATA_DIR là thôi xin Zalo gửi lại tin cũ sau mỗi lần nối lại.
        noBackfillFlag: path.join(dataDir, "NO_BACKFILL"),
        version: require(path.join(ROOT, "package.json")).version,
    };
}

module.exports = { loadConfig };

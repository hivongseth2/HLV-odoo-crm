// Log ra màn hình + file theo ngày. KHÔNG ghi nội dung tin nhắn vào log (chỉ mã tin, độ dài) — log hay bị gửi
// đi nhờ xem lỗi, không được lộ tin của NCC.
"use strict";

const fs = require("fs");
const path = require("path");

function createLogger(logDir) {
    fs.mkdirSync(logDir, { recursive: true });
    function write(level, parts) {
        const now = new Date();
        const line = `${now.toISOString()} ${level} ${parts.map((p) => (p instanceof Error ? p.stack || p.message : typeof p === "string" ? p : JSON.stringify(p))).join(" ")}`;
        (level === "ERROR" ? console.error : console.log)(line);
        try {
            fs.appendFileSync(path.join(logDir, `listener-${now.toISOString().slice(0, 10)}.log`), line + "\n", { mode: 0o600 });
        } catch (err) {
            console.error("Không ghi được file log:", err.message);
        }
    }
    return {
        info: (...parts) => write("INFO", parts),
        warn: (...parts) => write("WARN", parts),
        error: (...parts) => write("ERROR", parts),
    };
}

module.exports = { createLogger };

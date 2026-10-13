// Gửi tin + trạng thái về Odoo (module hlv_vendor_zalo). Lỗi thì ném ra — tin vẫn nằm trong SQLite, lượt sau gửi lại.
"use strict";

const fs = require("fs");
const path = require("path");

const TIMEOUT_MS = 60 * 1000;

class OdooClient {
    constructor(baseUrl, key) {
        if (!baseUrl || !key) {
            throw new Error("Thiếu ODOO_URL / ODOO_KEY trong file .env");
        }
        this.baseUrl = baseUrl;
        this.key = key;
    }

    async _post(route, body, headers) {
        const response = await fetch(this.baseUrl + route, {
            method: "POST",
            headers: Object.assign({ "X-API-Key": this.key }, headers || {}),
            body: body,
            signal: AbortSignal.timeout(TIMEOUT_MS),
        });
        const text = await response.text();
        let data = null;
        try {
            data = JSON.parse(text);
        } catch {
            data = null;
        }
        if (!response.ok || !data || data.ok === false) {
            throw new Error(`Odoo ${route} trả ${response.status}: ${(data && data.error) || text.slice(0, 120)}`);
        }
        return data;
    }

    /** Một lô: {listener, status, messages, reactions} → {stored, duplicate, skipped, media_wanted, …}. */
    sendEvents(batch) {
        return this._post("/api/zalo-listener/events", JSON.stringify(batch), { "Content-Type": "application/json" });
    }

    /** Gửi file đã tải của tin msgId. */
    uploadMedia(msgId, filePath) {
        const form = new FormData();
        form.append("msg_id", msgId);
        form.append("file", new Blob([fs.readFileSync(filePath)]), path.basename(filePath).replace(/^[^_.]+_/, ""));
        return this._post("/api/zalo-listener/media", form);
    }

    /** Báo Odoo file của tin msgId không tải được (link hết hạn / quá cỡ). */
    reportMediaFailed(msgId) {
        const form = new FormData();
        form.append("msg_id", msgId);
        form.append("failed", "1");
        return this._post("/api/zalo-listener/media", form);
    }
}

module.exports = { OdooClient };

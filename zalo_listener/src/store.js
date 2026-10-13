// SQLite trên máy nghe = hàng đợi gửi Odoo + bản lưu gốc. Tin luôn ghi xuống đây TRƯỚC, đẩy Odoo sau: Odoo bảo trì
// / mất mạng thì tin nằm chờ, không mất. Số tin trong DB chỉ được tăng — tụt là mất dữ liệu.
"use strict";

const fs = require("fs");
const Database = require("better-sqlite3");

const SCHEMA = `
CREATE TABLE IF NOT EXISTS messages (
    msg_id      TEXT PRIMARY KEY,
    group_id    TEXT NOT NULL,
    ts          INTEGER,
    payload     TEXT NOT NULL,
    pushed      INTEGER NOT NULL DEFAULT 0,
    media_state TEXT NOT NULL DEFAULT 'none',  -- none | pending | downloaded | failed | uploaded
    media_path  TEXT,
    media_want  INTEGER NOT NULL DEFAULT 0,    -- Odoo cần file này (nhóm đang bật ghi tin)
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_pushed ON messages (pushed);
CREATE INDEX IF NOT EXISTS messages_media ON messages (media_state, media_want);
CREATE TABLE IF NOT EXISTS reactions (
    key        TEXT PRIMARY KEY,
    payload    TEXT NOT NULL,
    pushed     INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS groups (
    group_id   TEXT PRIMARY KEY,
    name       TEXT,
    updated_at INTEGER NOT NULL
);
`;

class Store {
    /** failedPath: file .jsonl hứng tin khi ghi DB lỗi cả hai lần — không mất tin. */
    constructor(dbPath, failedPath, log) {
        this.db = new Database(dbPath);
        this.db.pragma("journal_mode = WAL");
        this.db.exec(SCHEMA);
        this.failedPath = failedPath;
        this.log = log;
        try {
            fs.chmodSync(dbPath, 0o600);
        } catch (err) {
            log.warn("Không đổi được quyền file DB:", err.message);
        }
    }

    _retry(label, fn) {
        try {
            return fn();
        } catch {
            try {
                return fn();
            } catch (second) {
                this.log.error(`Ghi DB lỗi 2 lần (${label}) — đẩy ra file dự phòng:`, second.message);
                return null;
            }
        }
    }

    _spill(kind, payload) {
        fs.appendFileSync(this.failedPath, JSON.stringify({ kind, at: Date.now(), payload }) + "\n", { mode: 0o600 });
    }

    /** Ghi tin (trùng mã tin thì bỏ). Trả true nếu là tin mới. */
    saveMessage(payload) {
        const result = this._retry("message", () => this.db.prepare(
            `INSERT OR IGNORE INTO messages (msg_id, group_id, ts, payload, media_state, created_at)
             VALUES (?, ?, ?, ?, ?, ?)`,
        ).run(payload.msg_id, payload.group_id, payload.ts, JSON.stringify(payload),
            payload.attachment ? "pending" : "none", Date.now()));
        if (result === null) {
            this._spill("message", payload);
            return false;
        }
        return result.changes > 0;
    }

    saveReaction(key, payload) {
        const result = this._retry("reaction", () => this.db.prepare(
            "INSERT OR IGNORE INTO reactions (key, payload, created_at) VALUES (?, ?, ?)",
        ).run(key, JSON.stringify(payload), Date.now()));
        if (result === null) {
            this._spill("reaction", payload);
            return false;
        }
        return result.changes > 0;
    }

    groupName(groupId) {
        const row = this.db.prepare("SELECT name, updated_at FROM groups WHERE group_id = ?").get(groupId);
        return row || null;
    }

    saveGroupName(groupId, name) {
        this.db.prepare(
            `INSERT INTO groups (group_id, name, updated_at) VALUES (?, ?, ?)
             ON CONFLICT(group_id) DO UPDATE SET name = excluded.name, updated_at = excluded.updated_at`,
        ).run(groupId, name, Date.now());
    }

    unpushedMessages(limit) {
        return this.db.prepare("SELECT payload FROM messages WHERE pushed = 0 ORDER BY ts LIMIT ?").all(limit)
            .map((row) => JSON.parse(row.payload));
    }

    unpushedReactions(limit) {
        return this.db.prepare("SELECT key, payload FROM reactions WHERE pushed = 0 ORDER BY created_at LIMIT ?").all(limit)
            .map((row) => ({ key: row.key, payload: JSON.parse(row.payload) }));
    }

    /** Đánh dấu đã đẩy Odoo; wantMedia = mã tin Odoo còn chờ file (nhóm đang bật ghi tin). */
    markPushed(msgIds, reactionKeys, wantMedia) {
        const tx = this.db.transaction(() => {
            const msg = this.db.prepare("UPDATE messages SET pushed = 1 WHERE msg_id = ?");
            msgIds.forEach((id) => msg.run(id));
            const react = this.db.prepare("UPDATE reactions SET pushed = 1 WHERE key = ?");
            reactionKeys.forEach((key) => react.run(key));
            const want = this.db.prepare("UPDATE messages SET media_want = 1 WHERE msg_id = ?");
            wantMedia.forEach((id) => want.run(id));
        });
        tx();
    }

    /** Tin có file chưa tải (link Zalo hết hạn về sau — tải NGAY khi nhận). */
    pendingDownloads(limit) {
        return this.db.prepare("SELECT msg_id, payload FROM messages WHERE media_state = 'pending' ORDER BY created_at LIMIT ?")
            .all(limit).map((row) => ({ msgId: row.msg_id, payload: JSON.parse(row.payload) }));
    }

    setMedia(msgId, state, mediaPath) {
        this.db.prepare("UPDATE messages SET media_state = ?, media_path = COALESCE(?, media_path) WHERE msg_id = ?")
            .run(state, mediaPath || null, msgId);
    }

    /** File Odoo cần mà chưa gửi: đã tải xong, hoặc tải hỏng (báo Odoo là hỏng). */
    mediaToUpload(limit) {
        return this.db.prepare(
            `SELECT msg_id, media_state, media_path, payload FROM messages
             WHERE media_want = 1 AND media_state IN ('downloaded', 'failed') ORDER BY created_at LIMIT ?`,
        ).all(limit).map((row) => ({ msgId: row.msg_id, state: row.media_state, path: row.media_path,
            payload: JSON.parse(row.payload) }));
    }

    markMediaSent(msgId) {
        this.db.prepare("UPDATE messages SET media_want = 0, media_state = CASE media_state WHEN 'downloaded' THEN 'uploaded' ELSE media_state END WHERE msg_id = ?")
            .run(msgId);
    }

    outboxSize() {
        return this.db.prepare("SELECT COUNT(*) AS n FROM messages WHERE pushed = 0").get().n
            + this.db.prepare("SELECT COUNT(*) AS n FROM reactions WHERE pushed = 0").get().n;
    }

    close() {
        this.db.close();
    }
}

module.exports = { Store };

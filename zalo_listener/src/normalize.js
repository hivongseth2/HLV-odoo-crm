// Hàm thuần: tin / thả cảm xúc của zca-js → gói gửi Odoo (/api/zalo-listener/events). Không đụng mạng, không đụng DB.
// Kiểu dữ liệu theo zca-js 2.2.0 (models/Message.d.ts, models/Reaction.d.ts) — đổi bản zca-js thì kiểm lại file này.
"use strict";

const THREAD_GROUP = 1; // ThreadType.Group của zca-js

function str(value) {
    return value === undefined || value === null ? "" : String(value);
}

/** Phần đính kèm (ảnh / file / link) của tin: content là object có href. Không có → null. */
function attachmentOf(content) {
    if (!content || typeof content !== "object" || !content.href) {
        return null;
    }
    return { href: str(content.href), title: str(content.title), params: str(content.params) };
}

/** Chữ của tin: tin chữ là content dạng chuỗi; tin đính kèm lấy tiêu đề / mô tả (tên file, chú thích ảnh). */
function textOf(content) {
    if (typeof content === "string") {
        return content;
    }
    if (content && typeof content === "object") {
        return str(content.description || content.title || "");
    }
    return "";
}

/**
 * Tin nhóm → gói gửi Odoo. msg: GroupMessage của zca-js; groupName: tên nhóm đã tra (có thể "").
 * Tin 1-1 (không phải nhóm) / thiếu mã tin → null (máy nghe chỉ lưu tin nhóm).
 */
function normalizeMessage(msg, groupName) {
    if (!msg || msg.type !== THREAD_GROUP || !msg.data || !msg.data.msgId) {
        return null;
    }
    const data = msg.data;
    const quote = data.quote
        ? {
            msg_id: str(data.quote.globalMsgId),
            sender_uid: str(data.quote.ownerId),
            sender_name: str(data.quote.fromD),
            text: str(data.quote.msg),
        }
        : null;
    return {
        msg_id: str(data.msgId),
        cli_msg_id: str(data.cliMsgId),
        group_id: str(msg.threadId),
        group_name: str(groupName),
        sender_uid: str(data.uidFrom),
        sender_name: str(data.dName),
        is_self: Boolean(msg.isSelf),
        ts: Number(data.ts) || 0,
        msg_type: str(data.msgType),
        text: textOf(data.content),
        attachment: attachmentOf(data.content),
        quote: quote,
        mentions: (data.mentions || []).map((m) => str(m.uid)).filter(Boolean),
    };
}

/** Thả cảm xúc trong nhóm → gói gửi Odoo; không phải nhóm / không có tin đích → null. */
function normalizeReaction(reaction) {
    if (!reaction || !reaction.isGroup || !reaction.data || !reaction.data.content) {
        return null;
    }
    const data = reaction.data;
    const target = (data.content.rMsg || [])[0];
    if (!target || !target.gMsgID) {
        return null;
    }
    return {
        target_msg_id: str(target.gMsgID),
        group_id: str(reaction.threadId),
        sender_uid: str(data.uidFrom),
        sender_name: str(data.dName),
        icon: str(data.content.rIcon),
        ts: Number(data.ts) || 0,
    };
}

/** Khoá chống trùng cho một lần thả cảm xúc (Zalo gửi lại khi lấy bù). */
function reactionKey(payload) {
    return [payload.target_msg_id, payload.sender_uid, payload.icon, payload.ts].join("|");
}

module.exports = { THREAD_GROUP, normalizeMessage, normalizeReaction, reactionKey, attachmentOf, textOf };

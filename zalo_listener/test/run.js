// Test các phần không cần Zalo thật: lịch giãn cách, chuẩn hoá tin, kho SQLite, tên file. Chạy: npm test
"use strict";

const assert = require("assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const backoff = require("../src/backoff");
const { normalizeMessage, normalizeReaction, reactionKey } = require("../src/normalize");
const { fileNameFor, safeName } = require("../src/media");
const { Store } = require("../src/store");

let passed = 0;
function test(name, fn) {
    fn();
    passed += 1;
    console.log("OK   " + name);
}

const MIN = 60 * 1000;

test("giãn cách đăng nhập 30s → 1 → 3 → 10 → 30 phút, quá thì giữ 30 phút", () => {
    assert.deepStrictEqual([0, 1, 2, 3, 4, 9].map((i) => backoff.pickDelay(backoff.LOGIN_DELAYS, i)),
        [30000, MIN, 3 * MIN, 10 * MIN, 30 * MIN, 30 * MIN]);
    assert.strictEqual(backoff.pickDelay(backoff.LOGIN_DELAYS, -1), 30000);
});

test("QR tối đa 3 lần / giờ, lần thứ 4 phải chờ tới khi lần cũ nhất quá 1 giờ", () => {
    const now = 10 * 3600 * 1000;
    assert.ok(backoff.qrAllowed([], now));
    const three = [now - 50 * MIN, now - 20 * MIN, now - MIN];
    assert.ok(!backoff.qrAllowed(three, now));
    assert.strictEqual(backoff.qrWait(three, now), 10 * MIN);
    assert.ok(backoff.qrAllowed([now - 61 * MIN, now - 20 * MIN, now - MIN], now));
});

test("lỗi mạng khác lỗi xác thực", () => {
    assert.ok(backoff.isNetworkError(Object.assign(new Error("x"), { code: "ENOTFOUND" })));
    assert.ok(backoff.isNetworkError(new TypeError("fetch failed")));
    assert.ok(backoff.isNetworkError({ message: "y", cause: { code: "UND_ERR_CONNECT_TIMEOUT" } }));
    assert.ok(!backoff.isNetworkError(new Error("Đăng nhập thất bại: cookie hết hạn")));
    assert.ok(!backoff.isNetworkError(null));
});

test("rớt kết nối: 3003 dừng, 3000 chờ 5 phút, 1006 giãn 5s → 15s → 60s → 5 phút, lần 10 thì đăng nhập lại", () => {
    assert.strictEqual(backoff.onClose(3003, 0).action, "stop");
    assert.strictEqual(backoff.onClose(1000, 0).action, "stop");
    assert.deepStrictEqual([backoff.onClose(3000, 4).action, backoff.onClose(3000, 4).wait], ["reconnect", 5 * MIN]);
    assert.deepStrictEqual([0, 1, 2, 3, 7].map((f) => backoff.onClose(1006, f).wait), [5000, 15000, MIN, 5 * MIN, 5 * MIN]);
    assert.strictEqual(backoff.onClose(1006, 8).action, "reconnect");
    assert.strictEqual(backoff.onClose(1006, 9).action, "relogin");
});

const textMessage = {
    type: 1, threadId: "g1", isSelf: false,
    data: {
        msgId: "7001", cliMsgId: "c1", uidFrom: "u9", dName: "Phương Daisin Vn", ts: "1760342400000", msgType: "webchat",
        content: "A27 đủ 10s\nC86 còn 9s", mentions: [{ uid: "u2", pos: 0, len: 5, type: 0 }],
        quote: { ownerId: "u2", globalMsgId: 6999, msg: "C86: 10 sợi", fromD: "Duyên Hoàng Long Vũ" },
    },
};

test("tin chữ nhóm → gói Odoo (mã tin, người gửi, trích, nhắc tên)", () => {
    const p = normalizeMessage(textMessage, "HLV - Daisin");
    assert.strictEqual(p.msg_id, "7001");
    assert.strictEqual(p.group_id, "g1");
    assert.strictEqual(p.group_name, "HLV - Daisin");
    assert.strictEqual(p.text, "A27 đủ 10s\nC86 còn 9s");
    assert.strictEqual(p.ts, 1760342400000);
    assert.strictEqual(p.attachment, null);
    assert.deepStrictEqual(p.quote, { msg_id: "6999", sender_uid: "u2", sender_name: "Duyên Hoàng Long Vũ", text: "C86: 10 sợi" });
    assert.deepStrictEqual(p.mentions, ["u2"]);
});

test("tin ảnh / file → có attachment; tin 1-1 → bỏ", () => {
    const photo = normalizeMessage({ type: 1, threadId: "g1", data: { msgId: "7002", msgType: "chat.photo", uidFrom: "u9", ts: 1,
        content: { href: "https://cdn.zalo/x/abc.jpg", title: "", description: "bảng giá", params: "{}" } } }, "");
    assert.deepStrictEqual(photo.attachment, { href: "https://cdn.zalo/x/abc.jpg", title: "", params: "{}" });
    assert.strictEqual(photo.text, "bảng giá");
    assert.strictEqual(normalizeMessage(Object.assign({}, textMessage, { type: 0 }), ""), null);
    assert.strictEqual(normalizeMessage({ type: 1, data: {} }, ""), null);
});

test("thả tim trong nhóm → gói Odoo; không phải nhóm → bỏ", () => {
    const reaction = { isGroup: true, threadId: "g1", data: { uidFrom: "u2", dName: "Trâm", ts: "1760342500000",
        content: { rMsg: [{ gMsgID: "7001", cMsgID: "c1", msgType: 1 }], rIcon: "/-heart", rType: 0, source: 0 } } };
    const p = normalizeReaction(reaction);
    assert.deepStrictEqual(p, { target_msg_id: "7001", group_id: "g1", sender_uid: "u2", sender_name: "Trâm", icon: "/-heart",
        ts: 1760342500000 });
    assert.strictEqual(reactionKey(p), "7001|u2|/-heart|1760342500000");
    assert.strictEqual(normalizeReaction(Object.assign({}, reaction, { isGroup: false })), null);
});

test("tên file tải về an toàn, giữ đuôi", () => {
    assert.strictEqual(fileNameFor("7003", { href: "https://x/y/BG.xlsx", title: "Bảng giá 10/2026.xlsx" }), "7003_Bảng giá 10_2026.xlsx");
    assert.strictEqual(fileNameFor("7004", { href: "https://x/y/abc.PNG?x=1", title: "" }), "7004.png");
    assert.strictEqual(fileNameFor("7005", { href: "https://x/y/noext", title: "" }), "7005.jpg");
    assert.strictEqual(safeName("../../etc/passwd"), ".._.._etc_passwd");
});

test("kho SQLite: không trùng tin, hàng đợi gửi, file cần gửi", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "zalo-listener-"));
    const log = { info() {}, warn() {}, error() {} };
    const store = new Store(path.join(dir, "t.db"), path.join(dir, "failed.jsonl"), log);
    const text = normalizeMessage(textMessage, "g");
    const photo = normalizeMessage({ type: 1, threadId: "g1", data: { msgId: "7002", msgType: "chat.photo", uidFrom: "u9", ts: 2,
        content: { href: "https://cdn/x.jpg", title: "" } } }, "g");
    assert.ok(store.saveMessage(text));
    assert.ok(!store.saveMessage(text), "tin trùng (lấy bù) bị bỏ");
    assert.ok(store.saveMessage(photo));
    assert.deepStrictEqual(store.unpushedMessages(10).map((m) => m.msg_id), ["7002", "7001"], "gửi theo thứ tự thời gian");
    assert.deepStrictEqual(store.pendingDownloads(10).map((d) => d.msgId), ["7002"]);
    store.setMedia("7002", "downloaded", path.join(dir, "7002.jpg"));
    assert.ok(store.saveReaction("k1", { target_msg_id: "7001" }));
    assert.ok(!store.saveReaction("k1", { target_msg_id: "7001" }));
    assert.strictEqual(store.outboxSize(), 3);
    assert.deepStrictEqual(store.mediaToUpload(5), [], "Odoo chưa đòi file thì chưa gửi");
    store.markPushed(["7001", "7002"], ["k1"], ["7002"]);
    assert.strictEqual(store.outboxSize(), 0);
    assert.deepStrictEqual(store.mediaToUpload(5).map((m) => [m.msgId, m.state]), [["7002", "downloaded"]]);
    store.markMediaSent("7002");
    assert.deepStrictEqual(store.mediaToUpload(5), []);
    store.saveGroupName("g1", "HLV - Daisin");
    assert.strictEqual(store.groupName("g1").name, "HLV - Daisin");
    store.close();
    fs.rmSync(dir, { recursive: true, force: true });
});

console.log(`ALL OK (${passed})`);

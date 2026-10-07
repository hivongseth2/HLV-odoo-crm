/**
 * Phần "sống" của trang NCC: khung trao đổi (cuộn xuống tin mới nhất, hiện tên tệp đã chọn),
 * chuông thông báo, và nhận tin mới qua websocket (odoo_bus.js) — kèm tiếng + số trên tab
 * (chat_alert.js), dán ảnh vào ô tin nhắn (chat_paste.js).
 *
 * Có tin mới: lấy lại chính trang đang xem (chạy nền) rồi thay các vùng data-live — số
 * trên chuông, danh sách thông báo, dòng trong bảng, khung trao đổi. Không tải lại cả trang,
 * kẻo mất giá NCC đang gõ dở trong bảng. Server ghi "đã xem" khi trả trang chi tiết, nên tin
 * trên đúng chứng từ đang mở không bị tính là chưa xem.
 * Tin ở chứng từ khác: thêm thông báo nhỏ ở góc kèm link.
 */
(function () {
    "use strict";

    var body = document.body;
    var CHAT_OPEN_KEY = "vq_chat_open";
    var TAB_ROOM = 48;  // chỗ cần bên phải tờ giấy cho tab (rộng 36px, 44px khi rê chuột)

    function scrollChats() {
        document.querySelectorAll(".vq-chat-list").forEach(function (list) {
            list.scrollTop = list.scrollHeight;
        });
    }

    function bindFilePickers() {
        document.querySelectorAll(".vq-chat-form input[type=file]").forEach(function (input) {
            if (window.HlvChatPaste) {
                window.HlvChatPaste.bind(input.closest("form").querySelector("textarea"), input);
            }
            input.addEventListener("change", function () {
                var out = input.closest("form").querySelector("[data-file-names]");
                if (out) {
                    out.textContent = Array.prototype.map.call(input.files, function (f) { return f.name; }).join(", ");
                }
            });
        });
    }

    function readChatPref() {
        try {
            return window.localStorage.getItem(CHAT_OPEN_KEY) === "1";
        } catch (e) {
            return false;
        }
    }

    function saveChatPref(open) {
        try {
            window.localStorage.setItem(CHAT_OPEN_KEY, open ? "1" : "0");
        } catch (e) { /* trình duyệt chặn lưu: lần sau mặc định đóng */ }
    }

    /**
     * Khung trao đổi nổi: mặc định là nút tròn, nhớ lần NCC mở / đóng gần nhất. Link
     * #trao-doi (thông báo, sau khi gửi tin) hoặc gửi tin bị lỗi thì mở sẵn.
     */
    function initChatPanel() {
        var section = document.querySelector("details.vq-chat");
        if (!section) {
            return;
        }
        var wanted = window.location.hash === "#trao-doi" || !!section.querySelector(".vq-chat-error") || readChatPref();
        // Lần mở do trang tự mở (không phải NCC bấm) thì không focus ô nhập — trên điện thoại
        // focus là bật bàn phím che trang.
        var autoOpening = wanted;
        section.addEventListener("toggle", function () {
            if (section.open) {
                section.classList.remove("vq-chat-new");
                scrollChats();
                if (!autoOpening) {
                    var input = section.querySelector("textarea");
                    if (input) {
                        input.focus({ preventScroll: true });
                    }
                }
            }
            if (!autoOpening) {
                saveChatPref(section.open);
            }
            autoOpening = false;
        });
        section.open = wanted;
        document.addEventListener("keydown", function (event) {
            if (event.key === "Escape" && section.open) {
                section.open = false;
            }
        });
    }

    /**
     * Gắn tab trao đổi vào mép phải tờ chứng từ thật (bề rộng tờ đổi theo trang / màn hình nên
     * không đoán bằng CSS): gán --vq-paper-edge = toạ độ mép phải. Bên ngoài tờ không đủ chỗ
     * cho tab (màn hẹp) thì lật tab vào trong, dán mép phải màn hình.
     */
    function placeChatTab() {
        var section = document.querySelector("details.vq-chat");
        var paper = document.querySelector(".vq-main > .vq-wrap");
        if (!section || !paper) {
            return;
        }
        var edge = paper.getBoundingClientRect().right;
        var viewport = document.documentElement.clientWidth;
        document.documentElement.style.setProperty("--vq-paper-edge", Math.round(edge) + "px");
        section.classList.toggle("vq-chat-inside", viewport - edge < TAB_ROOM);
    }

    /** Số trên tab = số trên chuông ("99+" tính 99). */
    function syncTabCount() {
        var count = document.querySelector(".vq-notify-count");
        if (window.HlvChatAlert) {
            window.HlvChatAlert.setUnread(count ? parseInt(count.textContent, 10) || 0 : 0);
        }
    }

    /** Bấm ra ngoài thì đóng bảng thông báo (details không tự đóng). */
    function bindNotifyClose() {
        document.addEventListener("click", function (event) {
            document.querySelectorAll("details.vq-notify[open]").forEach(function (box) {
                if (!box.contains(event.target)) {
                    box.removeAttribute("open");
                }
            });
        });
    }

    function refreshLive() {
        return fetch(window.location.pathname + window.location.search, { credentials: "same-origin" })
            .then(function (response) { return response.text(); })
            .then(function (html) {
                var doc = new DOMParser().parseFromString(html, "text/html");
                // Thay nội dung chứ không thay phần tử: giữ trạng thái đóng / mở và ô đang gõ.
                document.querySelectorAll("[data-live]").forEach(function (region) {
                    var fresh = doc.querySelector('[data-live="' + region.dataset.live + '"]');
                    if (fresh) {
                        region.innerHTML = fresh.innerHTML;
                    }
                });
            });
    }

    function flash(section) {
        section.classList.add("vq-chat-flash");
        setTimeout(function () { section.classList.remove("vq-chat-flash"); }, 1500);
    }

    function toast(payload) {
        var base = body.dataset.portalBase;
        var box = document.createElement("a");
        box.className = "vq-toast";
        box.href = base + (payload.model === "quote" ? "/" : "/don-mua/") + payload.res_id + "#trao-doi";
        box.textContent = (payload.author || "Bên mua") + " vừa nhắn trên " + payload.name + " — bấm để xem";
        document.body.appendChild(box);
        setTimeout(function () { box.remove(); }, 10000);
    }

    function onChat(payload) {
        var section = document.querySelector('[data-chat-key="' + payload.model + ":" + payload.res_id + '"]');
        if (window.HlvChatAlert) {
            window.HlvChatAlert.notify((payload.author || "Bên mua") + " vừa nhắn");
        }
        refreshLive().then(function () {
            syncTabCount();
            if (section && !section.open) {
                section.classList.add("vq-chat-new");  // khung đang thu thành nút: nút nháy + badge đỏ
            } else if (section) {
                flash(section);
                scrollChats();
            } else {
                toast(payload);
            }
        }).catch(function () {
            // Mạng chập chờn: vẫn báo có tin, lần tin sau sẽ tải lại.
            if (!section) {
                toast(payload);
            }
        });
    }

    function listenBus() {
        var channel = body.dataset.busChannel;
        if (!channel || !window.HlvBus) {
            return;
        }
        window.HlvBus.listen({
            version: body.dataset.busVersion,
            channels: [channel],
            onMessage: function (type, payload) {
                if (type === "hlv_vq_chat") {
                    onChat(payload);
                }
            },
        });
    }

    initChatPanel();
    placeChatTab();
    window.addEventListener("resize", placeChatTab);
    scrollChats();
    syncTabCount();
    bindFilePickers();
    bindNotifyClose();
    listenBus();
})();

/**
 * Khung trao đổi trên trang NCC: cuộn xuống tin mới nhất, hiện tên tệp đã chọn, và nhận tin
 * mới qua websocket (odoo_bus.js).
 *
 * Tin mới trên đúng báo giá / đơn mua đang xem: chỉ tải lại phần trao đổi (lấy trang về chạy
 * nền, thay khung) — không tải lại cả trang, kẻo mất giá NCC đang gõ dở trong bảng.
 * Tin ở chứng từ khác: hiện thông báo nhỏ kèm link.
 */
(function () {
    "use strict";

    var body = document.body;

    function scrollChats() {
        document.querySelectorAll(".vq-chat-list").forEach(function (list) {
            list.scrollTop = list.scrollHeight;
        });
    }

    function bindFilePickers() {
        document.querySelectorAll(".vq-chat-form input[type=file]").forEach(function (input) {
            input.addEventListener("change", function () {
                var out = input.closest("form").querySelector("[data-file-names]");
                if (out) {
                    out.textContent = Array.prototype.map.call(input.files, function (f) { return f.name; }).join(", ");
                }
            });
        });
    }

    function refreshChat(section) {
        fetch(window.location.pathname, { credentials: "same-origin" }).then(function (response) {
            return response.text();
        }).then(function (html) {
            var doc = new DOMParser().parseFromString(html, "text/html");
            var fresh = doc.querySelector('[data-chat-key="' + section.dataset.chatKey + '"]');
            if (!fresh) {
                return;
            }
            // Thay nội dung chứ không thay cả <details>: giữ trạng thái đóng / mở và ô đang gõ.
            section.querySelector(".vq-chat-list").innerHTML = fresh.querySelector(".vq-chat-list").innerHTML;
            section.querySelector("summary").innerHTML = fresh.querySelector("summary").innerHTML;
            section.classList.add("vq-chat-flash");
            setTimeout(function () { section.classList.remove("vq-chat-flash"); }, 1500);
            scrollChats();
        }).catch(function () { /* mạng chập chờn: lần tin sau sẽ tải lại */ });
    }

    function toast(payload) {
        var base = body.dataset.portalBase;
        var link = base + (payload.model === "quote" ? "/" : "/don-mua/") + payload.res_id + "#trao-doi";
        var box = document.createElement("a");
        box.className = "vq-toast";
        box.href = link;
        box.textContent = (payload.author || "Bên mua") + " vừa nhắn trên " + payload.name + " — bấm để xem";
        document.body.appendChild(box);
        setTimeout(function () { box.remove(); }, 10000);
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
                if (type !== "hlv_vq_chat") {
                    return;
                }
                var section = document.querySelector('[data-chat-key="' + payload.model + ":" + payload.res_id + '"]');
                if (section) {
                    refreshChat(section);
                } else {
                    toast(payload);
                }
            },
        });
    }

    scrollChats();
    bindFilePickers();
    listenBus();
})();

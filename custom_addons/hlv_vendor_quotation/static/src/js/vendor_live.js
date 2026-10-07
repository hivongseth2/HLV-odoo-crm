/**
 * Phần "sống" của trang NCC: khung trao đổi (cuộn xuống tin mới nhất, hiện tên tệp đã chọn),
 * chuông thông báo, và nhận tin mới qua websocket (odoo_bus.js).
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
        refreshLive().then(function () {
            if (section) {
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

    scrollChats();
    bindFilePickers();
    bindNotifyClose();
    listenBus();
})();

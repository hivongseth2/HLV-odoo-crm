/**
 * Khung "Ảnh phiếu gửi" ở bước báo đã gửi hàng (portal_order_progress): bấm để chọn ảnh, Ctrl+V dán ảnh
 * (đang ở bất kỳ ô nào trong form báo gửi — NCC hay chụp màn hình phiếu rồi dán), kéo thả, có ảnh xem trước
 * và nút bỏ từng tệp. Tệp vẫn nằm trong ô chọn tệp thật (name="attachments") nên form gửi như cũ, không cần
 * upload riêng. Gom tệp dùng HlvChatPaste (js/chat_paste.js) — cùng cách đặt tên ảnh dán với khung trao đổi.
 */
(function () {
    "use strict";

    function removeAt(input, index) {
        var transfer = new DataTransfer();
        Array.prototype.forEach.call(input.files, function (file, i) {
            if (i !== index) {
                transfer.items.add(file);
            }
        });
        input.files = transfer.files;
        input.dispatchEvent(new Event("change", { bubbles: true }));
    }

    /** Vẽ lại danh sách tệp: ảnh có ô xem trước, tệp khác (PDF) chỉ có tên. */
    function render(zone, input) {
        var list = zone.querySelector("[data-vq-drop-list]");
        list.querySelectorAll("img").forEach(function (img) { URL.revokeObjectURL(img.src); });
        list.textContent = "";
        zone.classList.toggle("has-files", input.files.length > 0);
        Array.prototype.forEach.call(input.files, function (file, index) {
            var item = document.createElement("span");
            item.className = "vq-drop-item";
            item.title = file.name;
            if (file.type.indexOf("image/") === 0) {
                var img = document.createElement("img");
                img.src = URL.createObjectURL(file);
                img.alt = file.name;
                item.appendChild(img);
            } else {
                var name = document.createElement("span");
                name.className = "vq-drop-name";
                name.textContent = file.name;
                item.appendChild(name);
            }
            var remove = document.createElement("button");
            remove.type = "button";
            remove.className = "vq-drop-remove";
            remove.setAttribute("aria-label", "Bỏ tệp " + file.name);
            remove.textContent = "×";
            remove.addEventListener("click", function (event) {
                event.stopPropagation();
                removeAt(input, index);
            });
            item.appendChild(remove);
            list.appendChild(item);
        });
    }

    // Lắng nghe ở document chứ không gắn vào từng khung: danh sách đơn mua được vendor_live.js thay bằng bản mới
    // qua websocket (data-live="rows"), khung gắn sự kiện riêng sẽ mất sau lần thay đó.
    function zoneOf(target) {
        return target && target.closest ? target.closest("[data-vq-dropzone]") : null;
    }

    function inputOf(zone) {
        return zone.querySelector("[data-vq-drop-input]");
    }

    function canAdd() {
        return Boolean(window.HlvChatPaste && window.DataTransfer);
    }

    document.addEventListener("change", function (event) {
        var zone = zoneOf(event.target);
        if (zone && event.target === inputOf(zone)) {
            render(zone, event.target);
        }
    });

    document.addEventListener("click", function (event) {
        var zone = zoneOf(event.target);
        if (zone && event.target !== inputOf(zone) && !event.target.closest(".vq-drop-remove")) {
            inputOf(zone).click();
        }
    });

    document.addEventListener("keydown", function (event) {
        var zone = zoneOf(event.target);
        if (zone && event.target === zone && (event.key === "Enter" || event.key === " ")) {
            event.preventDefault();
            inputOf(zone).click();
        }
    });

    // Dán ở đâu trong form báo gửi cũng nhận — clipboard không có tệp thì để dán chữ như thường.
    document.addEventListener("paste", function (event) {
        var form = event.target.closest && event.target.closest("form");
        var zone = form && form.querySelector("[data-vq-dropzone]");
        var files = event.clipboardData && event.clipboardData.files;
        if (zone && files && files.length && canAdd()) {
            event.preventDefault();
            window.HlvChatPaste.addFiles(inputOf(zone), files);
        }
    });

    document.addEventListener("dragover", function (event) {
        var zone = zoneOf(event.target);
        if (zone && canAdd()) {
            event.preventDefault();
            zone.classList.add("is-drag");
        }
    });

    document.addEventListener("dragleave", function (event) {
        var zone = zoneOf(event.target);
        if (zone && !zone.contains(event.relatedTarget)) {
            zone.classList.remove("is-drag");
        }
    });

    document.addEventListener("drop", function (event) {
        var zone = zoneOf(event.target);
        if (!zone || !canAdd()) {
            return;
        }
        event.preventDefault();
        zone.classList.remove("is-drag");
        if (event.dataTransfer && event.dataTransfer.files.length) {
            window.HlvChatPaste.addFiles(inputOf(zone), event.dataTransfer.files);
        }
    });
})();

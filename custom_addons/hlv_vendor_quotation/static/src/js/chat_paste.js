/**
 * Ctrl+V ảnh / tệp vào ô tin nhắn: tệp trong clipboard được thêm vào ô chọn tệp của form
 * (cộng dồn với tệp đã chọn), rồi phát sự kiện "change" để trang tự hiện tên tệp như khi
 * chọn bằng nút đính kèm. Dán chữ thường thì để trình duyệt xử lý như cũ.
 *
 * Ảnh chụp màn hình dán vào luôn tên "image.png" — đổi thành anh-dan-<giờ>.png cho khỏi
 * trùng tên khi dán nhiều ảnh.
 *
 * Dùng: HlvChatPaste.bind(textarea, fileInput)
 */
(function () {
    "use strict";

    function pad(n) {
        return n < 10 ? "0" + n : String(n);
    }

    function rename(file, index) {
        if (file.name && file.name !== "image.png") {
            return file;
        }
        var now = new Date();
        var ext = (file.type.split("/")[1] || "png").replace("jpeg", "jpg");
        var name = "anh-dan-" + pad(now.getHours()) + pad(now.getMinutes()) + pad(now.getSeconds()) +
            (index ? "-" + index : "") + "." + ext;
        return new File([file], name, { type: file.type });
    }

    function bind(textarea, fileInput) {
        if (!textarea || !fileInput || !window.DataTransfer) {
            return;
        }
        textarea.addEventListener("paste", function (event) {
            var pasted = event.clipboardData && event.clipboardData.files;
            if (!pasted || !pasted.length) {
                return;
            }
            event.preventDefault();
            var transfer = new DataTransfer();
            Array.prototype.forEach.call(fileInput.files, function (file) { transfer.items.add(file); });
            Array.prototype.forEach.call(pasted, function (file, index) { transfer.items.add(rename(file, index)); });
            fileInput.files = transfer.files;
            fileInput.dispatchEvent(new Event("change", { bubbles: true }));
        });
    }

    window.HlvChatPaste = { bind: bind };
})();

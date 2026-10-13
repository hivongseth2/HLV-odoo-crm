/**
 * Chứng từ chi NCC — dùng chung trang kế toán (/unc-ncc) và trang NCC (khung Thanh toán, tab Tài chính):
 *  - Bấm ảnh thu nhỏ có data-doc-preview="image" | "pdf": xem ngay trong trang (hộp <dialog>), không phải tải về.
 *    "file" (Word, HEIC) để trình duyệt mở / tải như link thường. Không có JS thì link vẫn mở tab mới.
 *  - Ô kéo-thả .unc-drop (trang kế toán): kéo file vào hoặc bấm chọn; hiện danh sách file sẽ tải kèm ảnh thu nhỏ.
 * Trang không qua asset bundle của Odoo nên viết JS thường. Tên file đưa vào trang bằng textContent (không innerHTML).
 */
(function () {
    "use strict";

    let dialog = null;

    function buildDialog() {
        dialog = document.createElement("dialog");
        dialog.className = "doc-preview";
        const bar = document.createElement("div");
        bar.className = "doc-preview-bar";
        const name = document.createElement("span");
        name.className = "doc-preview-name";
        const open = document.createElement("a");
        open.target = "_blank";
        open.rel = "noopener";
        open.textContent = "Mở tab mới";
        const close = document.createElement("button");
        close.type = "button";
        close.textContent = "Đóng ✕";
        close.addEventListener("click", () => dialog.close());
        bar.append(name, open, close);
        const body = document.createElement("div");
        body.className = "doc-preview-body";
        dialog.append(bar, body);
        // Bấm ra ngoài khung (vùng nền mờ) là đóng.
        dialog.addEventListener("click", (ev) => {
            if (ev.target === dialog) {
                dialog.close();
            }
        });
        dialog.addEventListener("close", () => body.replaceChildren());
        document.body.append(dialog);
    }

    function showPreview(url, kind, label) {
        if (!dialog) {
            buildDialog();
        }
        dialog.querySelector(".doc-preview-name").textContent = label;
        dialog.querySelector(".doc-preview-bar a").href = url;
        const viewer = document.createElement(kind === "image" ? "img" : "iframe");
        viewer.src = url;
        if (kind === "image") {
            viewer.alt = label;
        } else {
            viewer.title = label;
        }
        dialog.querySelector(".doc-preview-body").replaceChildren(viewer);
        dialog.showModal();
    }

    document.addEventListener("click", (ev) => {
        const link = ev.target.closest && ev.target.closest("[data-doc-preview]");
        const kind = link && link.dataset.docPreview;
        if (!link || (kind !== "image" && kind !== "pdf") || typeof HTMLDialogElement === "undefined") {
            return;
        }
        ev.preventDefault();
        showPreview(link.href, kind, link.dataset.docName || "");
    });

    // ------------------------------------------------------------------ ô kéo-thả (trang kế toán)
    function sizeText(bytes) {
        return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
    }

    function badge(name) {
        const ext = (name.split(".").pop() || "").toLowerCase();
        return { pdf: "PDF", doc: "WORD", docx: "WORD", heic: "ẢNH" }[ext] || ext.toUpperCase() || "FILE";
    }

    function renderPicked(input, list) {
        list.replaceChildren(...Array.from(input.files).map((file) => {
            const item = document.createElement("li");
            const thumb = document.createElement("span");
            thumb.className = "doc-thumb";
            if (/^image\/(png|jpe?g|webp|gif)$/.test(file.type)) {
                const img = document.createElement("img");
                img.src = URL.createObjectURL(file);
                img.alt = "";
                thumb.append(img);
            } else {
                thumb.classList.add(file.type === "application/pdf" ? "doc-thumb-pdf" : "doc-thumb-file");
                thumb.textContent = badge(file.name);
            }
            const name = document.createElement("span");
            name.className = "unc-picked-name";
            name.textContent = file.name;
            const size = document.createElement("span");
            size.className = "unc-picked-size";
            size.textContent = sizeText(file.size);
            item.append(thumb, name, size);
            return item;
        }));
    }

    for (const zone of document.querySelectorAll(".unc-drop")) {
        const input = zone.querySelector('input[type="file"]');
        const list = zone.closest("form").querySelector("[data-picked]");
        input.addEventListener("change", () => renderPicked(input, list));
        for (const type of ["dragenter", "dragover"]) {
            zone.addEventListener(type, (ev) => {
                ev.preventDefault();
                zone.classList.add("is-over");
            });
        }
        for (const type of ["dragleave", "drop"]) {
            zone.addEventListener(type, () => zone.classList.remove("is-over"));
        }
        zone.addEventListener("drop", (ev) => {
            ev.preventDefault();
            // Kéo thêm lần nữa thì CỘNG vào file đã chọn, không thay.
            const merged = new DataTransfer();
            [...input.files, ...ev.dataTransfer.files].forEach((file) => merged.items.add(file));
            input.files = merged.files;
            renderPicked(input, list);
        });
    }
})();

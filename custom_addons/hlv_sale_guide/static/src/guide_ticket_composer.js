/* Khung soạn tin của ticket: dùng cho cả tạo ticket mới lẫn trả lời trong thảo luận.
   Đính kèm bằng Ctrl+V (ảnh chụp màn hình), kéo thả, hoặc nút chọn file — ảnh, video, PDF, file
   bất kỳ. Ctrl+Enter để gửi. */
(function (ns) {
  "use strict";

  var h = ns.core.h;
  var text = ns.text;

  /** Ảnh dán từ clipboard luôn tên "image.png" — đặt tên theo giờ để phân biệt trong thảo luận. */
  function pastedName(file, index) {
    var now = new Date();
    var stamp = [now.getHours(), now.getMinutes(), now.getSeconds()].map(function (n) {
      return (n < 10 ? "0" : "") + n;
    }).join("");
    var ext = (file.type.split("/")[1] || "png").replace("jpeg", "jpg");
    return "anh-dan-" + stamp + (index ? "-" + index : "") + "." + ext;
  }

  /**
   * Dựng khung soạn tin. opts:
   *   placeholder: chữ gợi ý ô nội dung;
   *   extra: phần tử chèn trên ô nội dung (VD chọn loại, hướng dẫn, tiêu đề, đoạn trích);
   *   actions: [{label, primary, fields}] — mỗi nút gửi kèm fields riêng (VD state: "done");
   *   allowEmpty(action): true nếu nút đó gửi được khi chưa có chữ lẫn file (chỉ đổi trạng thái);
   *   submit(fields, files, onProgress) → Promise; xong thì khung tự xoá nội dung.
   * Trả phần tử gốc; .focus() để đặt con trỏ vào ô nội dung.
   */
  function composer(opts) {
    var files = [];
    var body = h("textarea", { class: "cmp-body", rows: 4, placeholder: opts.placeholder });
    var previews = h("div", { class: "cmp-files", hidden: true });
    var error = h("div", { class: "cmp-error", hidden: true });
    var progress = h("div", { class: "cmp-progress", hidden: true }, [h("span")]);
    var picker = h("input", { type: "file", multiple: true, hidden: true });
    var buttons = opts.actions.map(function (action) {
      return h("button", {
        type: "button",
        class: "btn" + (action.primary ? " btn-primary" : ""),
        text: action.label,
        onclick: function () { submit(action); },
      });
    });

    function showError(message) {
      error.textContent = message || "";
      error.hidden = !message;
    }

    function renderFiles() {
      previews.textContent = "";
      previews.hidden = !files.length;
      files.forEach(function (file, index) {
        var thumb = file.type.indexOf("image/") === 0
          ? h("img", { src: URL.createObjectURL(file), alt: "" })
          : h("span", { class: "cmp-icon", text: text.fileLabel(file.name) });
        previews.appendChild(h("div", { class: "cmp-file", title: file.name }, [
          thumb,
          h("span", { class: "cmp-name", text: file.name }),
          h("small", { text: text.formatSize(file.size) }),
          h("button", {
            type: "button", class: "cmp-remove", title: "Bỏ file này", text: "×",
            onclick: function () { files.splice(index, 1); renderFiles(); },
          }),
        ]));
      });
    }

    function addFiles(list, fromPaste) {
      var added = Array.prototype.slice.call(list).map(function (file, index) {
        return fromPaste && file.type.indexOf("image/") === 0
          ? new File([file], pastedName(file, index), { type: file.type })
          : file;
      });
      var next = files.concat(added);
      var problem = text.uploadProblem(next.map(function (file) { return file.size; }), ns.core.limits);
      showError(problem);
      if (!problem) {
        files = next;
        renderFiles();
      }
    }

    function setBusy(busy) {
      buttons.forEach(function (button) { button.disabled = busy; });
      body.disabled = busy;
      progress.hidden = !busy;
      progress.firstChild.style.width = "0";
    }

    function submit(action) {
      if (!body.value.trim() && !files.length && !(opts.allowEmpty && opts.allowEmpty(action))) {
        showError("Hãy viết nội dung, hoặc dán ảnh vào.");
        body.focus();
        return;
      }
      showError("");
      setBusy(true);
      var fields = Object.assign({ body: body.value }, action.fields || {});
      opts.submit(fields, files, function (ratio) {
        progress.firstChild.style.width = Math.round(ratio * 100) + "%";
      }).then(function () {
        body.value = "";
        files = [];
        renderFiles();
      }, function (err) {
        showError(err.message);
      }).then(function () {
        setBusy(false);
      });
    }

    var root = h("div", { class: "composer" }, [
      opts.extra || null,
      body,
      previews,
      progress,
      error,
      h("div", { class: "cmp-actions" }, [
        h("button", {
          type: "button", class: "btn btn-light", title: "Đính kèm ảnh, video, file — hoặc Ctrl+V / kéo thả vào đây",
          text: "Đính kèm", onclick: function () { picker.click(); },
        }),
        h("span", { class: "cmp-hint", text: "Ctrl+V dán ảnh · kéo thả file" }),
      ].concat(buttons)),
      picker,
    ]);

    picker.addEventListener("change", function () {
      addFiles(picker.files, false);
      picker.value = "";
    });
    // Dán: chỉ lấy file khi clipboard không có chữ — chép từ Word/Excel thường kèm ảnh của
    // chính đoạn chữ đó, người dùng muốn dán chữ chứ không phải ảnh.
    root.addEventListener("paste", function (event) {
      var clip = event.clipboardData;
      if (clip && clip.files && clip.files.length && !clip.getData("text/plain")) {
        event.preventDefault();
        addFiles(clip.files, true);
      }
    });
    root.addEventListener("dragover", function (event) {
      if (event.dataTransfer && Array.prototype.indexOf.call(event.dataTransfer.types, "Files") >= 0) {
        event.preventDefault();
        root.classList.add("is-drop");
      }
    });
    root.addEventListener("dragleave", function (event) {
      if (!root.contains(event.relatedTarget)) {
        root.classList.remove("is-drop");
      }
    });
    root.addEventListener("drop", function (event) {
      root.classList.remove("is-drop");
      if (event.dataTransfer && event.dataTransfer.files.length) {
        event.preventDefault();
        addFiles(event.dataTransfer.files, false);
      }
    });
    body.addEventListener("keydown", function (event) {
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        submit(opts.actions.filter(function (action) { return action.primary; })[0] || opts.actions[0]);
      }
    });
    root.focus = function () { body.focus(); };
    return root;
  }

  ns.composer = composer;
})(window.HlvGuide = window.HlvGuide || {});

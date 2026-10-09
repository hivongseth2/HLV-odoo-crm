/* Form tạo ticket: loại (câu hỏi / yêu cầu chỉnh sửa), hướng dẫn, các đoạn trích, tiêu đề, nội dung
   + file đính kèm (khung soạn tin dùng chung). Đang mở form mà bôi đen thêm đoạn khác trong hướng
   dẫn thì đoạn đó được thêm vào danh sách — một ticket chỉ ra được nhiều chỗ trên trang. */
(function (ns) {
  "use strict";

  var h = ns.core.h;
  var KINDS = [["question", "Câu hỏi"], ["request", "Yêu cầu chỉnh sửa"]];

  /**
   * opts: {guide: hướng dẫn chọn sẵn hoặc null, quote: đoạn trích đầu tiên hoặc "",
   *        onBack(), onCreated(id) → Promise}.
   * Trả {el: phần tử form, add({guide, quote})} — add để thêm đoạn trích khi form đang mở.
   */
  function ticketForm(opts) {
    var kind = "question";
    var quotes = [];
    var kindButtons = KINDS.map(function (item) {
      return h("button", {
        type: "button", class: "tk-kind-pick", "data-kind": item[0], "aria-pressed": String(item[0] === kind),
        text: item[1],
        onclick: function () {
          kind = item[0];
          kindButtons.forEach(function (b) { b.setAttribute("aria-pressed", String(b.dataset.kind === kind)); });
        },
      });
    });
    var guideSelect = h("select", {
      class: "tk-input", "aria-label": "Hướng dẫn",
      // Đoạn trích thuộc hướng dẫn cũ, sang hướng dẫn khác không còn tìm thấy.
      onchange: function () { quotes = []; renderQuotes(); },
    }, [h("option", { value: "", text: "Chung, không gắn hướng dẫn" })].concat(ns.viewer.guides().map(function (g) {
      return h("option", { value: g.id, text: g.name });
    })));
    var quoteBox = h("div", { class: "tk-quotes" });
    var titleInput = h("input", { class: "tk-input", type: "text", maxlength: 80, placeholder: "Tiêu đề (bỏ trống: lấy dòng đầu nội dung)" });

    function renderQuotes() {
      quoteBox.textContent = "";
      quotes.forEach(function (quote, index) {
        quoteBox.appendChild(h("div", { class: "tk-quote-pick" }, [
          h("blockquote", { class: "tk-quote tk-quote-full", text: quote }),
          h("button", {
            type: "button", class: "cmp-remove", title: "Bỏ đoạn này", text: "×",
            onclick: function () { quotes.splice(index, 1); renderQuotes(); },
          }),
        ]));
      });
      if (ns.quote.available()) {
        quoteBox.appendChild(h("div", {
          class: "tk-tip",
          text: quotes.length
            ? "Bôi đen thêm chỗ khác trong hướng dẫn để trích tiếp vào ticket này."
            : "Bôi đen một hoặc nhiều đoạn trong hướng dẫn rồi bấm nút hiện ra để chỉ rõ chỗ cần hỏi / cần sửa.",
        }));
      }
    }

    function add(preset) {
      // Đoạn trích của hướng dẫn khác: bắt đầu lại danh sách, các đoạn cũ không nằm trên trang đó.
      if (preset.guide && String(preset.guide.id) !== guideSelect.value) {
        guideSelect.value = String(preset.guide.id);
        quotes = [];
      }
      if (preset.quote && quotes.indexOf(preset.quote) < 0) {
        quotes.push(preset.quote);
      }
      renderQuotes();
      form.focus();
    }

    var form = ns.composer({
      placeholder: "Nội dung câu hỏi / yêu cầu… (Ctrl+V để dán ảnh chụp màn hình)",
      extra: h("div", { class: "tk-new-fields" }, [
        h("div", { class: "tk-kind-row" }, kindButtons),
        guideSelect,
        quoteBox,
        titleInput,
      ]),
      actions: [{ label: "Gửi ticket", primary: true }],
      submit: function (fields, files, onProgress) {
        fields.kind = kind;
        fields.guide_id = guideSelect.value;
        fields.title = titleInput.value;
        fields.quotes = quotes.slice();
        return ns.core.send("/new", fields, files, onProgress).then(function (reply) {
          return opts.onCreated(reply.id);
        });
      },
    });

    var el = h("div", { class: "tk-detail" }, [
      h("button", { type: "button", class: "tk-back", text: "← Danh sách", onclick: opts.onBack }),
      h("h2", { class: "tk-detail-title", text: "Ticket mới" }),
      form,
    ]);
    add({ guide: opts.guide, quote: opts.quote });
    return { el: el, add: add };
  }

  ns.ticketForm = ticketForm;
})(window.HlvGuide = window.HlvGuide || {});

/* Trình soạn mẫu hợp đồng: vùng contenteditable trên tờ A4 + thanh công cụ + bảng biến.
   HTML lưu ra được server đọc bằng utils/html_blocks.py, nên chỉ dùng những gì bên đó hiểu:
   p, b/i/u, span font-size, text-align, ul/li, table (class hlv-grid / hlv-noborder, colgroup). */
window.HlvContract = window.HlvContract || {};

(function (HD) {
  "use strict";

  var esc = HD.esc;
  var FONT_SIZES = [11, 12, 13, 14, 16, 18, 20];
  var DEFAULT_SIZE = 13;
  var ZWSP = "​";
  // fontSize của execCommand chỉ nhận 1..7; dùng 7 làm dấu tạm rồi đổi sang span cỡ pt thật
  var FONT_MARKER = "7";
  var BLOCK_TAGS = ["P", "DIV", "LI", "TD", "TH", "H1", "H2", "H3", "H4", "H5", "H6"];

  var TOOLBAR = [
    [["bold", "<b>B</b>", "Đậm (Ctrl+B)"], ["italic", "<i>I</i>", "Nghiêng (Ctrl+I)"], ["underline", "<u>U</u>", "Gạch chân (Ctrl+U)"]],
    [["justifyLeft", "⟸", "Căn trái"], ["justifyCenter", "≡", "Căn giữa"], ["justifyRight", "⟹", "Căn phải"], ["justifyFull", "☰", "Căn đều"]],
    [["insertUnorderedList", "• Danh sách", "Gạch đầu dòng"]],
    [["table", "Bảng", "Chèn bảng"], ["goods", "Bảng hàng hoá", "Chèn bảng hàng hoá dựng sẵn (một dòng mẫu + dòng tổng)"],
      ["rowAdd", "+ Dòng", "Thêm dòng bên dưới dòng đang đứng"], ["rowDel", "− Dòng", "Xoá dòng đang đứng"],
      ["border", "Viền bảng", "Bật/tắt viền bảng đang đứng (bảng chữ ký thường không viền)"]],
    [["undo", "↶", "Hoàn tác"], ["redo", "↷", "Làm lại"]],
  ];

  function toolbarHtml() {
    var groups = TOOLBAR.map(function (group) {
      return '<div class="hd-tool-group">' + group.map(function (btn) {
        return '<button type="button" class="hd-tool" data-cmd="' + btn[0] + '" title="' + btn[2] + '">' + btn[1] + "</button>";
      }).join("") + "</div>";
    });
    var sizes = '<select class="hd-input hd-tool-size" data-font-size="1" title="Cỡ chữ (pt)">' +
      '<option value="">Cỡ chữ</option>' + FONT_SIZES.map(function (size) {
        return '<option value="' + size + '">' + size + " pt</option>";
      }).join("") + "</select>";
    return '<div class="hd-toolbar-editor">' + groups.join("") + sizes + "</div>";
  }

  /**
   * Gắn trình soạn vào container. opts.variables(): biến nhập hiện có của mẫu [{name, label}];
   * opts.onAddVariable(def): gọi khi chèn một biến nhập chưa có (biến mới hoặc từ thư viện).
   * Trả {getHtml(), refreshPalette()}.
   */
  HD.mountEditor = function (container, html, opts) {
    var library = HD.S.config.library;
    var editor;
    var palette;
    var savedRange = null;

    container.innerHTML =
      '<div class="hd-editor-wrap">' +
      '<div class="hd-editor-main">' + toolbarHtml() +
      '<div class="hd-paper-scroll"><div class="hd-paper hd-editor" contenteditable="true" spellcheck="false"></div></div>' +
      "</div><aside class=\"hd-palette\"></aside></div>";
    editor = container.querySelector(".hd-editor");
    palette = container.querySelector(".hd-palette");
    editor.innerHTML = html || "<p><br></p>";
    document.execCommand("defaultParagraphSeparator", false, "p");
    document.execCommand("styleWithCSS", false, false);
    lockChips();

    function lockChips() {
      editor.querySelectorAll(".hlv-var").forEach(function (chip) { chip.setAttribute("contenteditable", "false"); });
    }

    function rememberSelection() {
      var selection = window.getSelection();
      if (selection.rangeCount && editor.contains(selection.anchorNode)) {
        savedRange = selection.getRangeAt(0).cloneRange();
      }
    }

    function restoreSelection() {
      editor.focus();
      if (savedRange) {
        var selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(savedRange);
      }
    }

    function exec(command, value) {
      restoreSelection();
      document.execCommand(command, false, value == null ? null : value);
      rememberSelection();
      lockChips();
    }

    /**
     * Vị trí chèn luôn nằm TRONG một đoạn. Con trỏ đứng thẳng trên vùng soạn (bấm vào khoảng
     * trắng dưới chữ) thì chèn trực tiếp sẽ tạo phần tử ngoài đoạn, hiện thành dòng riêng —
     * đó là lý do biến từng bị "tự xuống hàng". Khi đó đưa con trỏ về cuối đoạn gần nhất.
     */
    function insertionRange() {
      var range = savedRange && editor.contains(savedRange.startContainer) ? savedRange.cloneRange() : null;
      if (range && range.startContainer !== editor) {
        return range;
      }
      // Phần tử đứng ngay trước con trỏ: là đoạn chữ thì chèn vào cuối đoạn đó; là bảng/danh
      // sách (hoặc không có gì) thì tạo đoạn mới ngay sau nó
      var index = range ? Math.min(range.startOffset, editor.childNodes.length) : editor.childNodes.length;
      var prev = null;
      for (var i = index - 1; i >= 0 && !prev; i--) {
        prev = editor.childNodes[i].nodeType === 1 ? editor.childNodes[i] : null;
      }
      var target = prev && BLOCK_TAGS.indexOf(prev.tagName) >= 0 ? prev : null;
      if (!target) {
        target = document.createElement("p");
        if (prev) {
          prev.after(target);
        } else {
          editor.insertBefore(target, editor.firstChild);
        }
      }
      var brs = target.querySelectorAll(":scope > br:last-child");
      range = document.createRange();
      if (brs.length) {
        range.setStartBefore(brs[0]);
      } else {
        range.selectNodeContents(target);
        range.collapse(false);
      }
      return range;
    }

    function insertChip(name) {
      editor.focus();
      var range = insertionRange();
      range.deleteContents();
      var holder = document.createElement("span");
      holder.innerHTML = HD.varChip(name);
      var chip = holder.firstChild;
      var after = document.createTextNode(ZWSP);
      range.insertNode(after);
      range.insertNode(chip);
      // Con trỏ đứng ngay sau biến để gõ tiếp trên cùng dòng
      range = document.createRange();
      range.setStartAfter(after);
      range.collapse(true);
      var selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      savedRange = range.cloneRange();
    }

    function currentNode(tag) {
      var node = savedRange ? savedRange.startContainer : null;
      var el = node && (node.nodeType === 1 ? node : node.parentElement);
      var found = el ? el.closest(tag) : null;
      return found && editor.contains(found) ? found : null;
    }

    function applyFontSize(size) {
      exec("fontSize", FONT_MARKER);
      editor.querySelectorAll('font[size="' + FONT_MARKER + '"]').forEach(function (font) {
        var span = document.createElement("span");
        if (+size !== DEFAULT_SIZE) {
          span.style.fontSize = size + "pt";
        }
        while (font.firstChild) {
          span.appendChild(font.firstChild);
        }
        font.replaceWith(span);
      });
    }

    function tableCommand(command) {
      if (command === "table") {
        var cols = parseInt(window.prompt("Số cột của bảng?", "2"), 10);
        var rows = parseInt(window.prompt("Số dòng?", "2"), 10);
        if (cols > 0 && rows > 0) {
          exec("insertHTML", HD.tableHtml(rows, cols));
        }
        return;
      }
      if (command === "goods") {
        exec("insertHTML", HD.goodsTableHtml());
        return;
      }
      var table = currentNode("table");
      var row = currentNode("tr");
      if (!table) {
        HD.toast("Đặt con trỏ vào trong một bảng trước", "error");
        return;
      }
      if (command === "border") {
        var bordered = table.classList.contains("hlv-grid");
        table.classList.toggle("hlv-grid", !bordered);
        table.classList.toggle("hlv-noborder", bordered);
      } else if (command === "rowAdd" && row) {
        var clone = row.cloneNode(true);
        clone.querySelectorAll("td, th").forEach(function (cell) { cell.innerHTML = "<p><br></p>"; });
        row.after(clone);
      } else if (command === "rowDel" && row) {
        if (table.rows.length <= 1) {
          table.remove();
        } else {
          row.remove();
        }
      }
    }

    /* ---------------------------------------------------------- bảng biến bên phải */

    function chip(name, label, extraClass) {
      return '<button type="button" class="hd-var-btn ' + (extraClass || "") + '" data-var="' + esc(name) +
        '" title="Chèn {{' + esc(name) + '}}"><span>' + esc(label) + '</span><code>' + esc(name) + "</code></button>";
    }

    function refreshPalette() {
      var mine = opts.variables();
      var mineNames = mine.map(function (v) { return v.name; });
      var suggestions = library.standard.filter(function (v) { return mineNames.indexOf(v.name) < 0; });
      palette.innerHTML =
        '<div class="hd-palette-head">Bấm để chèn vào chỗ con trỏ</div>' +
        '<details class="hd-palette-help"><summary>Biến dùng chung giữa các mẫu?</summary>' +
        "<p>Mỗi mẫu tự chọn biến nào cần. <b>Cùng tên biến = cùng một thông tin</b> ở mọi mẫu: " +
        "đổi mẫu khi đang soạn thì giá trị đã gõ được giữ; chọn khách thì các biến Bên mua tự điền.</p>" +
        "<p>Nên dùng biến trong <b>Gợi ý</b> cho thông tin chung (bên mua, giao hàng…); chỉ tạo " +
        "<b>Biến mới</b> cho thông tin riêng của mẫu này.</p></details>" +
        '<div class="hd-palette-group"><div class="hd-palette-title">Biến của mẫu này — người dùng điền</div>' +
        (mine.length ? mine.map(function (v) { return chip(v.name, v.label, "is-mine"); }).join("")
          : '<div class="hd-muted hd-small">Chưa có. Thêm biến mới hoặc chọn từ gợi ý bên dưới.</div>') +
        '<button type="button" class="hd-btn hd-btn-mini mt-2" data-new-var="1">+ Biến mới…</button></div>' +
        (suggestions.length ? '<div class="hd-palette-group"><div class="hd-palette-title">Gợi ý hay dùng — tự điền khi chọn khách</div>' +
          suggestions.map(function (v) { return chip(v.name, v.label, ""); }).join("") + "</div>" : "") +
        '<div class="hd-palette-group"><div class="hd-palette-title">Tự điền — không cần nhập</div>' +
        library.system.map(function (group) {
          return '<div class="hd-palette-sub">' + esc(group.title) + "</div>" +
            group.items.map(function (item) { return chip(item.name, item.label, "is-system"); }).join("");
        }).join("") + "</div>";
    }

    function insertVariable(name) {
      var isSystem = library.system.some(function (group) {
        return group.items.some(function (item) { return item.name === name; });
      });
      var known = opts.variables().some(function (v) { return v.name === name; });
      if (!isSystem && !known) {
        var standard = library.standard.filter(function (v) { return v.name === name; })[0];
        opts.onAddVariable(Object.assign({ default_value: "" }, standard || { name: name, label: name, var_type: "text", section: "other" }));
        refreshPalette();
      }
      insertChip(name);
    }

    function newVariable() {
      var label = (window.prompt("Tên biến (ví dụ: Thời hạn bảo hành)") || "").trim();
      if (!label) {
        return;
      }
      var name = HD.variableCode(label);
      var exists = opts.variables().some(function (v) { return v.name === name; });
      if (!exists) {
        opts.onAddVariable({ name: name, label: label, var_type: "text", section: "other", default_value: "" });
        refreshPalette();
      }
      insertChip(name);
    }

    ["keyup", "mouseup", "input"].forEach(function (name) { editor.addEventListener(name, rememberSelection); });
    HD.on(container, "mousedown", "[data-cmd], [data-var], [data-new-var]", function (el, event) {
      event.preventDefault();   // giữ vùng chọn trong trang giấy khi bấm nút
    });
    HD.on(container, "click", "[data-cmd]", function (el) {
      var command = el.dataset.cmd;
      if (["table", "goods", "rowAdd", "rowDel", "border"].indexOf(command) >= 0) {
        restoreSelection();
        tableCommand(command);
      } else {
        exec(command);
      }
    });
    HD.on(container, "click", "[data-var]", function (el) { insertVariable(el.dataset.var); });
    HD.on(container, "click", "[data-new-var]", newVariable);
    HD.on(container, "change", "[data-font-size]", function (el) {
      if (el.value) {
        applyFontSize(el.value);
        el.value = "";
      }
    });
    refreshPalette();

    return {
      refreshPalette: refreshPalette,
      getHtml: function () {
        var clone = editor.cloneNode(true);
        clone.querySelectorAll("[contenteditable]").forEach(function (el) { el.removeAttribute("contenteditable"); });
        return clone.innerHTML.split(ZWSP).join("");
      },
    };
  };
})(window.HlvContract);

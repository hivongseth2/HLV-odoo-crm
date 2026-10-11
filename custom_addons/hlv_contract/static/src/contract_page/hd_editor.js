/* Trình soạn mẫu hợp đồng: vùng contenteditable trên tờ A4 + thanh công cụ + bảng biến.
   HTML lưu ra được server đọc bằng utils/html_blocks.py, nên chỉ dùng những gì bên đó hiểu:
   p, b/i/u, span font-size, text-align, ul/li, table (class hlv-grid / hlv-noborder, colgroup). */
window.HlvContract = window.HlvContract || {};

(function (HD) {
  "use strict";

  var FONT_SIZES = [11, 12, 13, 14, 16, 18, 20];
  var DEFAULT_SIZE = 13;
  var ZWSP = "​";
  // fontSize của execCommand chỉ nhận 1..7; dùng 7 làm dấu tạm rồi đổi sang span cỡ pt thật
  var FONT_MARKER = "7";

  var TOOLBAR = [
    [["bold", "<b>B</b>", "Đậm (Ctrl+B)"], ["italic", "<i>I</i>", "Nghiêng (Ctrl+I)"], ["underline", "<u>U</u>", "Gạch chân (Ctrl+U)"]],
    [["justifyLeft", "⟸", "Căn trái"], ["justifyCenter", "≡", "Căn giữa"], ["justifyRight", "⟹", "Căn phải"], ["justifyFull", "☰", "Căn đều"]],
    [["insertUnorderedList", "• Danh sách", "Gạch đầu dòng"]],
    [["table", "Bảng", "Chèn bảng"], ["goods", "Bảng hàng hoá", "Chèn bảng hàng hoá dựng sẵn"],
      ["rowAdd", "+ Dòng", "Thêm dòng bên dưới dòng đang đứng"], ["rowDel", "− Dòng", "Xoá dòng đang đứng"],
      ["border", "Viền bảng", "Bật/tắt viền bảng đang đứng (bảng chữ ký thường không viền)"]],
    [["undo", "↶", "Hoàn tác"], ["redo", "↷", "Làm lại"]],
  ];

  var editor = null;
  var savedRange = null;

  function toolbarHtml() {
    var groups = TOOLBAR.map(function (group) {
      return '<div class="hd-tool-group">' + group.map(function (btn) {
        return '<button type="button" class="hd-tool" data-cmd="' + btn[0] + '" title="' + btn[2] + '">' + btn[1] + "</button>";
      }).join("") + "</div>";
    });
    var sizes = '<select class="hd-input hd-tool-size" id="hd-font-size" title="Cỡ chữ (pt)">' +
      '<option value="">Cỡ chữ</option>' + FONT_SIZES.map(function (size) {
        return '<option value="' + size + '">' + size + " pt</option>";
      }).join("") + "</select>";
    return '<div class="hd-toolbar-editor">' + groups.join("") + sizes + "</div>";
  }

  function paletteHtml() {
    return '<div class="hd-palette-head">Bấm để chèn biến vào chỗ con trỏ</div>' +
      (HD.S.config.variables || []).map(function (group) {
        return '<div class="hd-palette-group"><div class="hd-palette-title">' + HD.esc(group.title) + "</div>" +
          group.items.map(function (item) {
            return '<button type="button" class="hd-var-btn" data-var="' + HD.esc(item.name) + '" title="{{' +
              HD.esc(item.name) + '}}">' + HD.esc(item.label) + "</button>";
          }).join("") + "</div>";
      }).join("") +
      '<p class="hd-muted hd-small mt-2">Bảng hàng chỉ cần một dòng có biến số 1; hợp đồng nhiều mặt hàng thì dòng ' +
      "này tự nhân bản khi xuất, dòng thừa tự bỏ.</p>";
  }

  function rememberSelection() {
    var selection = window.getSelection();
    if (selection.rangeCount && editor && editor.contains(selection.anchorNode)) {
      savedRange = selection.getRangeAt(0);
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
  }

  function insertHtml(html) {
    exec("insertHTML", html);
    lockChips();
  }

  /* Chip biến không cho gõ vào giữa, để {{Ten_Bien}} không bị sửa hỏng thành chữ thường. */
  function lockChips() {
    editor.querySelectorAll(".hlv-var").forEach(function (chip) {
      chip.setAttribute("contenteditable", "false");
    });
  }

  function currentCell(tag) {
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

  function runTableCommand(command) {
    var row = currentCell("tr");
    var table = currentCell("table");
    if (command === "table") {
      var cols = parseInt(window.prompt("Số cột của bảng?", "2"), 10);
      var rows = parseInt(window.prompt("Số dòng?", "2"), 10);
      if (cols > 0 && rows > 0) {
        insertHtml(HD.tableHtml(rows, cols));
      }
      return;
    }
    if (command === "goods") {
      insertHtml(HD.goodsTableHtml());
      return;
    }
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

  function onToolbar(el) {
    var command = el.dataset.cmd;
    if (["table", "goods", "rowAdd", "rowDel", "border"].indexOf(command) >= 0) {
      restoreSelection();
      runTableCommand(command);
    } else {
      exec(command);
    }
  }

  /**
   * Gắn trình soạn vào container với nội dung html. Trả {getHtml()} — HTML sạch để lưu
   * (bỏ ký tự đệm sau chip biến và thuộc tính chỉ dùng khi soạn).
   */
  HD.mountEditor = function (container, html) {
    container.innerHTML =
      '<div class="hd-editor-wrap">' +
      '<div class="hd-editor-main">' + toolbarHtml() +
      '<div class="hd-paper-scroll"><div class="hd-paper hd-editor" id="hd-editor" contenteditable="true" spellcheck="false"></div></div>' +
      "</div>" +
      '<aside class="hd-palette">' + paletteHtml() + "</aside></div>";
    editor = HD.$("hd-editor");
    editor.innerHTML = html || "<p><br></p>";
    savedRange = null;
    lockChips();
    document.execCommand("defaultParagraphSeparator", false, "p");
    document.execCommand("styleWithCSS", false, false);

    ["keyup", "mouseup", "input"].forEach(function (name) {
      editor.addEventListener(name, rememberSelection);
    });
    HD.on(container, "mousedown", "[data-cmd], [data-var]", function (el, event) {
      event.preventDefault();   // giữ vùng chọn trong trang giấy khi bấm nút
    });
    HD.on(container, "click", "[data-cmd]", onToolbar);
    HD.on(container, "click", "[data-var]", function (el) {
      insertHtml(HD.varChip(el.dataset.var) + ZWSP);
    });
    HD.$("hd-font-size").addEventListener("change", function (event) {
      if (event.target.value) {
        applyFontSize(event.target.value);
        event.target.value = "";
      }
    });

    return {
      getHtml: function () {
        var clone = editor.cloneNode(true);
        clone.querySelectorAll("[contenteditable]").forEach(function (el) { el.removeAttribute("contenteditable"); });
        return clone.innerHTML.split(ZWSP).join("");
      },
    };
  };
})(window.HlvContract);

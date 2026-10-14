/* Định dạng ô biến trong trình soạn: đậm, nghiêng, gạch chân, IN HOA, cỡ chữ.

   Ô biến là phần tử contenteditable=false (để không sửa nhầm tên biến), nên trình duyệt bỏ qua nó khi
   chạy execCommand — bôi đen ô biến rồi bấm B hay AA không có tác dụng, kể cả khi bôi lẫn với chữ.
   Ở đây tự bọc / gỡ thẻ quanh từng ô biến. Định dạng đặt riêng tại từng chỗ, nên cùng một biến có
   thể in hoa ở chỗ ký tên mà in thường ở chỗ khác.

   HD.chipFormat.chips(editor, range)          ô biến nằm trong vùng chọn
   HD.chipFormat.hasText(range)                vùng chọn có chữ thường ngoài ô biến không
   HD.chipFormat.isOn(editor, chip, kind)      ô biến đang có định dạng kind ("bold" | "italic" | "underline" | "caps")
   HD.chipFormat.apply(editor, chips, kind, on) bật / tắt kind cho các ô biến
   HD.chipFormat.size(editor, chips, pt)       đặt cỡ chữ; pt = null bỏ cỡ riêng */
window.HlvContract = window.HlvContract || {};

(function (HD) {
  "use strict";

  var KINDS = {
    bold: { selector: "b, strong", tag: "b" },
    italic: { selector: "i, em", tag: "i" },
    underline: { selector: "u", tag: "u" },
    caps: { selector: '[style*="text-transform"]', style: ["textTransform", "uppercase"] },
    size: { selector: '[style*="font-size"]', style: ["fontSize", ""] },
  };

  function chips(editor, range) {
    if (!range) {
      return [];
    }
    return Array.from(editor.querySelectorAll(".hlv-var")).filter(function (chip) { return range.intersectsNode(chip); });
  }

  function hasText(range) {
    var copy = range.cloneContents();
    copy.querySelectorAll(".hlv-var").forEach(function (chip) { chip.remove(); });
    return copy.textContent.trim() !== "";
  }

  function wrapperOf(editor, chip, kind) {
    var wrapper = chip.parentElement ? chip.parentElement.closest(KINDS[kind].selector) : null;
    if (kind === "caps" && wrapper && wrapper.style.textTransform !== "uppercase") {
      return null;
    }
    return wrapper && wrapper !== editor && editor.contains(wrapper) ? wrapper : null;
  }

  function isOn(editor, chip, kind) {
    return !!wrapperOf(editor, chip, kind);
  }

  /** Tách wrapper thành [phần trước][node][phần sau]; trả wrapper chỉ còn bọc node. */
  function isolate(node, wrapper) {
    var before = document.createRange();
    before.setStart(wrapper, 0);
    before.setEndBefore(node);
    var after = document.createRange();
    after.setStartAfter(node);
    after.setEnd(wrapper, wrapper.childNodes.length);
    var head = wrapper.cloneNode(false);
    head.appendChild(before.extractContents());
    var tail = wrapper.cloneNode(false);
    tail.appendChild(after.extractContents());
    if (head.textContent) {
      wrapper.before(head);
    }
    if (tail.textContent) {
      wrapper.after(tail);
    }
    return wrapper;
  }

  function unwrap(el) {
    el.replaceWith.apply(el, Array.from(el.childNodes));
  }

  function makeWrapper(kind, value) {
    var def = KINDS[kind];
    var el = document.createElement(def.tag || "span");
    if (def.style) {
      el.style[def.style[0]] = value || def.style[1];
    }
    return el;
  }

  /** Bỏ định dạng kind khỏi wrapper đã tách riêng cho ô biến; span còn kiểu khác thì giữ span. */
  function clearFormat(wrapper, kind) {
    var def = KINDS[kind];
    if (!def.style) {
      unwrap(wrapper);
      return;
    }
    wrapper.style[def.style[0]] = "";
    if (!wrapper.getAttribute("style")) {
      unwrap(wrapper);
    }
  }

  function apply(editor, list, kind, on, value) {
    list.forEach(function (chip) {
      var wrapper = wrapperOf(editor, chip, kind);
      if (on && kind === "size" && wrapper) {
        isolate(chip, wrapper).style.fontSize = value;
      } else if (on && !wrapper) {
        var el = makeWrapper(kind, value);
        chip.parentNode.insertBefore(el, chip);
        el.appendChild(chip);
      } else if (!on && wrapper) {
        clearFormat(isolate(chip, wrapper), kind);
      }
    });
  }

  HD.chipFormat = {
    chips: chips,
    hasText: hasText,
    isOn: isOn,
    apply: function (editor, list, kind, on) { apply(editor, list, kind, on); },
    size: function (editor, list, pt) { apply(editor, list, "size", pt != null, pt != null ? pt + "pt" : ""); },
  };
})(window.HlvContract);

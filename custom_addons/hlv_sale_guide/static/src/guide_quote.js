/* Gắn ticket với nội dung hướng dẫn đang mở trong khung xem (cùng origin nên đọc được DOM):
   - bôi đen một đoạn → nút nổi "Hỏi / yêu cầu sửa đoạn này" → mở form ticket kèm đoạn trích;
   - tô màu các đoạn đã có ticket, bấm vào là mở ticket đó;
   - nhảy tới đoạn trích của một ticket.
   Hướng dẫn PDF nằm trong trình xem PDF của trình duyệt — không đọc được, các việc trên bỏ qua. */
(function (ns) {
  "use strict";

  var view = document.getElementById("guide-view");
  var pick = document.getElementById("quote-pick");
  var MARK = "hlv-ticket-mark";
  var STYLE =
    "mark." + MARK + "{background:#fde68a;color:inherit;border-bottom:2px solid #d97706;cursor:pointer;padding:0;border-radius:2px}" +
    "mark." + MARK + ".is-done{background:transparent;border-bottom:2px dotted #9ca3af}" +
    "mark." + MARK + ".is-flash{animation:hlv-flash 1.2s ease-out 2}" +
    "@keyframes hlv-flash{0%{background:#fb923c}100%{background:#fde68a}}";
  var handlers = { pick: null, open: null };
  var picked = "";

  function frameDoc() {
    try {
      return view.contentDocument && view.contentDocument.body ? view.contentDocument : null;
    } catch (err) {
      return null;
    }
  }

  function hidePick() {
    pick.hidden = true;
    picked = "";
  }

  /** Đặt nút nổi ngay dưới đoạn bôi đen (hết chỗ thì lên trên), toạ độ quy về trang ngoài. */
  function placePick(doc) {
    var selection = doc.getSelection();
    var text = selection && !selection.isCollapsed ? selection.toString().trim() : "";
    if (text.length < 2) {
      hidePick();
      return;
    }
    var rect = selection.getRangeAt(0).getBoundingClientRect();
    var frame = view.getBoundingClientRect();
    picked = text;
    pick.hidden = false;
    var top = frame.top + rect.bottom + 6;
    if (top + pick.offsetHeight > window.innerHeight - 8) {
      top = frame.top + rect.top - pick.offsetHeight - 6;
    }
    var left = Math.min(Math.max(frame.left + rect.left, frame.left + 8), window.innerWidth - pick.offsetWidth - 12);
    pick.style.top = Math.max(top, frame.top + 4) + "px";
    pick.style.left = left + "px";
  }

  function textNodes(doc) {
    var walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT, {
      acceptNode: function (node) {
        var tag = node.parentNode.nodeName;
        return tag === "SCRIPT" || tag === "STYLE" || tag === "NOSCRIPT" ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
      },
    });
    var nodes = [];
    while (walker.nextNode()) {
      nodes.push(walker.currentNode);
    }
    return nodes;
  }

  /** Bỏ mọi đánh dấu cũ, trả lại text node như ban đầu. */
  function clearMarks(doc) {
    doc.querySelectorAll("mark." + MARK).forEach(function (mark) {
      var parent = mark.parentNode;
      while (mark.firstChild) {
        parent.insertBefore(mark.firstChild, mark);
      }
      parent.removeChild(mark);
      parent.normalize();
    });
  }

  /**
   * Bọc đoạn trích của ticket bằng <mark>. Đoạn trích có thể vắt qua nhiều thẻ (in đậm, hai đoạn
   * văn…) nên bọc riêng từng text node; text node chỉ có khoảng trắng (giữa các <li>, <tr>) bỏ qua
   * để không chèn <mark> vào chỗ trình duyệt không cho.
   */
  function wrapQuote(doc, ticket) {
    var nodes = textNodes(doc);
    var hit = ns.text.locateQuote(nodes.map(function (node) { return node.data; }), ticket.quote);
    if (!hit) {
      return;
    }
    for (var i = hit.endNode; i >= hit.startNode; i--) {
      var part = nodes[i];
      var start = i === hit.startNode ? hit.startOffset : 0;
      var end = i === hit.endNode ? hit.endOffset : part.length;
      if (!part.data.slice(start, end).trim()) {
        continue;
      }
      if (end < part.length) {
        part.splitText(end);
      }
      if (start > 0) {
        part = part.splitText(start);
      }
      var mark = doc.createElement("mark");
      mark.className = MARK + (ticket.state === "done" ? " is-done" : "");
      mark.dataset.ticket = ticket.id;
      mark.title = (ticket.state === "done" ? "Đã xử lý: " : "Ticket: ") + ticket.name;
      part.parentNode.insertBefore(mark, part);
      mark.appendChild(part);
    }
  }

  function attach() {
    var doc = frameDoc();
    hidePick();
    if (!doc) {
      return;
    }
    if (!doc.getElementById("hlv-ticket-style")) {
      var style = doc.createElement("style");
      style.id = "hlv-ticket-style";
      style.textContent = STYLE;
      (doc.head || doc.documentElement).appendChild(style);
    }
    var later = function () { setTimeout(function () { placePick(doc); }, 0); };
    doc.addEventListener("mouseup", later);
    doc.addEventListener("keyup", later);
    doc.addEventListener("scroll", hidePick, true);
    doc.addEventListener("selectionchange", function () {
      if (doc.getSelection().isCollapsed) {
        hidePick();
      }
    });
    doc.addEventListener("click", function (event) {
      var mark = event.target.closest && event.target.closest("mark." + MARK);
      if (mark && doc.getSelection().isCollapsed && handlers.open) {
        handlers.open(Number(mark.dataset.ticket));
      }
    });
    document.dispatchEvent(new CustomEvent("hlv:guide-loaded"));
  }

  ns.quote = {
    /** fn(đoạn trích) khi bấm nút nổi. */
    onPick: function (fn) { handlers.pick = fn; },
    /** fn(id ticket) khi bấm vào một đoạn đã đánh dấu. */
    onOpen: function (fn) { handlers.open = fn; },
    /** Tô các đoạn trích của tickets ([{id, name, state, quote}]) trên hướng dẫn đang mở. */
    mark: function (tickets) {
      var doc = frameDoc();
      if (!doc) {
        return;
      }
      clearMarks(doc);
      tickets.forEach(function (ticket) {
        if (ticket.quote) {
          wrapQuote(doc, ticket);
        }
      });
    },
    /** Cuộn tới đoạn trích của ticket và nháy sáng. Không thấy trên trang → false. */
    reveal: function (ticketId) {
      var doc = frameDoc();
      var marks = doc ? doc.querySelectorAll('mark.' + MARK + '[data-ticket="' + ticketId + '"]') : [];
      if (!marks.length) {
        return false;
      }
      marks[0].scrollIntoView({ block: "center", behavior: "smooth" });
      marks.forEach(function (mark) {
        mark.classList.remove("is-flash");
        void mark.offsetWidth; // đọc lại bố cục để animation chạy lại khi bấm lần nữa
        mark.classList.add("is-flash");
      });
      return true;
    },
  };

  if (!view || !pick) {
    return;
  }
  view.addEventListener("load", attach);
  // Nhấn giữ chuột trên nút: không để trang ngoài lấy focus làm mất vùng bôi đen trong khung.
  pick.addEventListener("mousedown", function (event) { event.preventDefault(); });
  pick.addEventListener("click", function () {
    var text = picked;
    var doc = frameDoc();
    hidePick();
    if (doc) {
      doc.getSelection().removeAllRanges();
    }
    if (text && handlers.pick) {
      handlers.pick(text);
    }
  });
  window.addEventListener("resize", hidePick);
})(window.HlvGuide = window.HlvGuide || {});

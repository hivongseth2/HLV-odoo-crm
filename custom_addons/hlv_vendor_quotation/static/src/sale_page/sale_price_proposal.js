/* Thu mua đề xuất giá (models/po_price_proposal.py): thu mua không sửa giá đơn mua ở backend nữa mà đề xuất giá gợi ý.
   Việc của sale nằm ngay trên ô giá của bảng so giá (ô + dòng tô màu, giá trên đơn gạch đi): "Hỏi lại NCC" — món mở
   lại trên báo giá của NCC, kèm lời nhắn — NCC báo lại thì "Gửi thu mua duyệt"; hoặc "NCC giữ giá". Đầu ngăn chỉ còn
   một dải "việc cần làm" dẫn tới ô, cộng một dòng ngắn cho mỗi đề xuất đã xong — mỗi thông tin chỉ hiện một chỗ.
   Giá sau VAT là số chính. */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  var esc = HQ.esc;
  var STATE_CLASS = {
    sale: "hq-tag-warn", vendor: "hq-tag-mine", quoted: "hq-tag-warn", to_approve: "hq-tag-mine",
    rejected: "hq-tag-danger", approved: "hq-tag-ok",
  };
  // Đề xuất đã xong (không còn việc của sale): vẽ gọn, mờ đi, không tô ô trên bảng so giá.
  var DONE = { approved: true, kept: true };

  /** Đề xuất còn mở của một ô giá (id dòng báo giá) — mới nhất trước (payload xếp id giảm). Không có → null. */
  HQ.openProposal = function (d, quoteLineId) {
    return (d.price_proposals || []).find(function (p) {
      return p.quote_line_id === quoteLineId && !DONE[p.state];
    }) || null;
  };

  /** Đơn mua có đề xuất còn mở — tin "thu mua đề xuất giá" của đơn đã nằm trên ô so giá, phần Đơn mua khỏi nhắc lại. */
  HQ.orderHasOpenProposal = function (d, orderId) {
    return (d.price_proposals || []).some(function (p) { return p.order_id === orderId && !DONE[p.state]; });
  };

  /** Món của đề xuất có ô trên bảng so giá không — có thì mọi thứ của đề xuất nằm ở ô. */
  function shownInCompare(d, p) {
    return (d.lines || []).some(function (line) {
      return Object.keys(line.offers).some(function (key) {
        var offer = line.offers[key];
        return offer && !offer.withdrawn && offer.line_id === p.quote_line_id;
      });
    });
  }

  /** Đầu ngăn: dải việc cần làm (đề xuất chờ sale, có ô trên bảng) + đề xuất không có ô (vẽ đủ, kèm nút) + một dòng
   cho mỗi đề xuất đã xong. Đề xuất đang chờ NCC / thu mua chỉ hiện ở ô — sale không có gì để làm. */
  HQ.priceProposalBox = function (d) {
    var list = d.price_proposals || [];
    var inCell = list.filter(function (p) { return !DONE[p.state] && shownInCompare(d, p); });
    var todo = inCell.filter(function (p) { return p.can_requote || p.can_submit || p.can_keep; });
    var orphan = list.filter(function (p) { return !DONE[p.state] && inCell.indexOf(p) < 0; });
    var done = list.filter(function (p) { return DONE[p.state]; });
    return todoBanner(todo) + (orphan.length || done.length
      ? '<div class="hq-share hq-proposals"><div class="hq-share-head"><b>Thu mua đề xuất giá</b></div>' +
        orphan.map(item).join("") + done.map(doneLine).join("") + "</div>" : "");
  };

  function todoBanner(todo) {
    if (!todo.length) {
      return "";
    }
    var submit = todo.some(function (p) { return p.can_submit; });
    return '<div class="hq-todo" role="status"><div><b>Thu mua trả về giá ' + todo.length + " món</b>" +
      "<span>" + (submit ? "NCC đã báo lại — gửi thu mua duyệt" : "Hỏi lại NCC") +
      " ngay trên ô tô cam ở bảng So giá</span></div>" +
      '<button type="button" class="hq-btn hq-btn-primary" data-pp-jump="1">Đến ô cần làm</button></div>';
  }

  /** Đề xuất đã xong: một dòng kết quả. */
  function doneLine(p) {
    return '<div class="hq-proposal is-done">' + esc(p.product) + " " + HQ.docChip(p.order) + " " +
      (p.state === "approved" ? "đơn đã đổi sang " + price(p.new_price) + " sau VAT"
        : "NCC giữ giá " + HQ.money(p.old_price)) + "</div>";
  }

  function price(value) {
    return "<b>" + HQ.money(value) + "</b>";
  }

  function stateTag(p) {
    return '<span class="hq-tag ' + (STATE_CLASS[p.state] || "") + '">' + esc(p.state_label) + "</span>";
  }

  /** Giá trong ô so giá có đề xuất còn mở: giá trên đơn gạch đi, số chính là giá NCC báo lại (hoặc giá thu mua gợi ý
   khi NCC chưa báo), dưới là lý do của thu mua và việc đang chờ ai. NCC giữ nguyên giá thì không gạch — giá trên đơn
   vẫn là giá đang dùng. Giá NCC khác không nhắc: đã nằm ở các cột bên cạnh. */
  HQ.proposalPrice = function (offer, p) {
    var head = p.vendor_kept_price
      ? '<span class="hq-offer-price">' + HQ.money(p.old_price) + ' <span class="hq-offer-unit">NCC giữ nguyên giá</span></span>' +
        '<span class="hq-offer-meta">thu mua gợi ý ' + HQ.money(p.suggested_price) + "</span>"
      : '<span class="hq-offer-old" title="Giá sau VAT đang trên đơn mua ' + esc(p.order) + '"><s>' +
        HQ.money(p.old_price) + "</s> giá trên đơn</span>" + (p.vendor_price
        ? '<span class="hq-offer-price">' + HQ.money(p.vendor_price) + ' <span class="hq-offer-unit">NCC báo lại</span></span>'
        : '<span class="hq-offer-price is-proposed">' + HQ.money(p.suggested_price) +
          ' <span class="hq-offer-unit">thu mua gợi ý</span></span>');
    var notes = [p.buyer_note ? "Lý do: " + esc(p.buyer_note) : "",
      // Không có nút nào cho sale = đang chờ người khác: nói rõ chờ ai.
      p.can_requote || p.can_submit || p.can_keep ? "" : esc(p.state_label)].filter(Boolean);
    return head + notes.map(function (n) { return '<span class="hq-offer-meta">' + n + "</span>"; }).join("") +
      (p.reject_reason && p.state === "rejected" ? '<span class="hq-offer-short">Thu mua không duyệt: ' +
        esc(p.reject_reason) + "</span>" : "") +
      (p.vat_warning ? '<span class="hq-offer-short">' + esc(p.vat_warning) + "</span>" : "");
  };

  /** Nút việc của sale cho một đề xuất — trên ô so giá (hoặc ở khối phía trên khi món không có ô). */
  HQ.proposalActions = function (p) {
    var html = "";
    if (p.can_submit) {
      html += '<button type="button" class="hq-btn hq-btn-mini hq-btn-primary" data-pp-submit="' + p.id +
        '" title="Gửi giá NCC vừa báo lại cho thu mua duyệt — duyệt xong đơn mua đổi giá">Gửi thu mua duyệt</button>';
    }
    if (p.can_requote) {
      html += '<button type="button" class="hq-btn hq-btn-mini' + (p.can_submit ? "" : " hq-btn-primary") +
        '" data-pp-requote="' + p.id + '" title="Mở lại món này trên báo giá của NCC và gửi lời nhắn — NCC báo lại giá ' +
        'trên trang NCC">' + (p.can_submit ? "Hỏi lại lần nữa" : "Hỏi lại NCC") + "</button>";
    }
    if (p.can_keep) {
      html += '<button type="button" class="hq-btn hq-btn-mini' + (p.vendor_kept_price ? " hq-btn-primary" : "") +
        '" data-pp-keep="' + p.id + '" title="NCC không giảm — đơn giữ giá cũ, đóng đề xuất">NCC giữ giá</button>';
    }
    return html ? '<div class="hq-pp-actions">' + html + "</div>" : "";
  };

  /** Đề xuất còn mở mà món không có ô trên bảng so giá (VD đã thu hồi NCC): vẽ đủ ở đây, kèm nút. */
  function item(p) {
    var lines = ['<div class="hq-muted">Giá trên đơn ' + HQ.money(p.old_price) + (p.suggested_price
      ? " → thu mua gợi ý " + price(p.suggested_price) : "") + " (sau VAT)" +
      (p.buyer ? " · " + esc(p.buyer) : "") + (p.date ? " · " + esc(p.date) : "") + "</div>"];
    if (p.buyer_note) {
      lines.push("<div>Lý do: " + esc(p.buyer_note) + "</div>");
    }
    if ((p.other_offers || []).length) {
      // Phiếu hỏi nhiều NCC: giá NCC khác đã báo cho cùng món — để sale có số mà thương lượng với NCC của đơn.
      lines.push('<div class="hq-muted">NCC khác đã báo: ' + p.other_offers.map(function (o) {
        return esc(o.vendor) + " " + price(o.price) + (o.supply ? " (" + esc(o.supply) + ")" : "");
      }).join(" · ") + "</div>");
    }
    if (p.vendor_kept_price) {
      lines.push('<div class="hq-partial">NCC gửi lại nhưng <b>giữ nguyên giá</b> ' + HQ.money(p.vendor_price) +
        " sau VAT — thương lượng thêm (hỏi lại NCC) hoặc bấm \"NCC giữ giá\"</div>");
    } else if (p.vendor_price) {
      lines.push("<div>NCC báo lại: " + price(p.vendor_price) + " sau VAT</div>");
    }
    if (p.vat_warning) {
      lines.push('<div class="hq-partial">' + esc(p.vat_warning) + "</div>");
    }
    if (p.new_price) {
      lines.push("<div>Đã gửi duyệt: " + price(p.new_price) + " sau VAT</div>");
    }
    if (p.reject_reason && p.state === "rejected") {
      lines.push('<div class="hq-expired">Thu mua không duyệt: ' + esc(p.reject_reason) + "</div>");
    }
    if (p.sale_note) {
      lines.push('<div class="hq-muted">Sale ghi: ' + esc(p.sale_note) + "</div>");
    }
    return '<div class="hq-proposal">' +
      '<div class="hq-share-head"><span>' + esc(p.product) + "</span>" + HQ.docChip(p.order) +
      '<span class="hq-muted">' + esc(p.vendor) + "</span>" + stateTag(p) + "</div>" +
      lines.join("") + HQ.proposalActions(p) + "</div>";
  }

  function proposalById(id) {
    return ((HQ.addVendorDetail || {}).price_proposals || []).find(function (p) { return p.id === id; }) || { id: id };
  }

  function send(name, params, button, message) {
    button.disabled = true;
    HQ.api(name, params).then(function (detail) {
      HQ.renderInquiry(detail);
      HQ.toast(message);
      HQ.reloadAll();
    }).catch(function (err) {
      button.disabled = false;
      HQ.toast(err.message);
    });
  }

  /** Hộp nhập trên nút bấm (ô so giá hẹp, không đặt ô nhập dài được). Bấm Huỷ → null = không gửi. */
  function ask(question, value) {
    return window.prompt(question, value || "");
  }

  HQ.bindPriceProposalEvents = function () {
    var panel = HQ.$("hq-drawer-panel");
    HQ.on(panel, "click", "[data-pp-jump]", function () {
      var cell = panel.querySelector(".hq-offer.has-proposal");
      if (cell) {
        cell.scrollIntoView({ behavior: "smooth", block: "center" });
        cell.classList.remove("is-flash");
        void cell.offsetWidth;  // vẽ lại để bấm lần nữa vẫn nháy
        cell.classList.add("is-flash");
      }
    });
    HQ.on(panel, "click", "[data-pp-requote]", function (el) {
      var p = proposalById(+el.dataset.ppRequote);
      var message = ask("Lời nhắn gửi " + (p.vendor || "NCC") + " — NCC thấy trên trang báo giá (sửa được):",
        p.vendor_message || p.default_message);
      if (message !== null) {
        send("price_requote", { proposal_id: p.id, message: message }, el,
          "Đã mở lại món trên báo giá và nhắn NCC — chờ NCC báo lại giá");
      }
    });
    HQ.on(panel, "click", "[data-pp-submit]", function (el) {
      var note = ask("Gửi thu mua duyệt giá NCC báo lại — ghi chú cho thu mua (không bắt buộc):");
      if (note !== null) {
        send("price_submit", { proposal_id: +el.dataset.ppSubmit, note: note }, el, "Đã gửi thu mua duyệt giá mới");
      }
    });
    HQ.on(panel, "click", "[data-pp-keep]", function (el) {
      var note = ask("NCC giữ giá cũ — ghi chú cho thu mua (không bắt buộc):");
      if (note !== null) {
        send("price_keep", { proposal_id: +el.dataset.ppKeep, note: note }, el, "Đã báo thu mua: NCC giữ giá");
      }
    });
  };
})(window.HlvQuote);

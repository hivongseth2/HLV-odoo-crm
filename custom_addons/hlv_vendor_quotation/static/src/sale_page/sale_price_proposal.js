/* Thu mua đề xuất giá (models/po_price_proposal.py): thu mua không sửa giá đơn mua ở backend nữa mà đề xuất giá gợi ý.
   Việc của sale nằm ngay trên ô giá của bảng so giá (ô + dòng tô màu, giá trên đơn gạch đi): "Hỏi lại NCC" — món mở
   lại trên báo giá của NCC, kèm lời nhắn — NCC báo lại thì "Gửi thu mua duyệt"; hoặc "NCC giữ giá". Khối "Thu mua đề
   xuất giá" phía trên chỉ để đọc lý do / giá NCC khác / kết quả. Giá sau VAT là số chính. */
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

  /** Món của đề xuất có ô trên bảng so giá không — có thì nút thao tác nằm ở ô, khối phía trên không vẽ trùng. */
  function shownInCompare(d, p) {
    return (d.lines || []).some(function (line) {
      return Object.keys(line.offers).some(function (key) {
        var offer = line.offers[key];
        return offer && !offer.withdrawn && offer.line_id === p.quote_line_id;
      });
    });
  }

  HQ.priceProposalBox = function (d) {
    var list = d.price_proposals || [];
    if (!list.length) {
      return "";
    }
    var waiting = list.filter(function (p) { return p.can_requote || p.can_submit; }).length;
    return '<div class="hq-share hq-proposals"><div class="hq-share-head"><b>Thu mua đề xuất giá</b>' +
      (waiting ? '<span class="hq-tag hq-tag-warn">' + waiting + " việc cần sale làm</span>" +
        '<span class="hq-muted">— bấm nút trên ô tô màu ở bảng So giá</span>' : "") + "</div>" +
      list.map(function (p) { return item(p, !DONE[p.state] && shownInCompare(d, p)); }).join("") + "</div>";
  };

  function price(value) {
    return "<b>" + HQ.money(value) + "</b>";
  }

  function stateTag(p) {
    return '<span class="hq-tag ' + (STATE_CLASS[p.state] || "") + '">' + esc(p.state_label) + "</span>";
  }

  /** Giá trong ô so giá có đề xuất còn mở: giá trên đơn gạch đi, số chính là giá NCC báo lại (hoặc giá thu mua gợi ý
   khi NCC chưa báo). NCC giữ nguyên giá thì không gạch — giá trên đơn vẫn là giá đang dùng. */
  HQ.proposalPrice = function (offer, p) {
    if (p.vendor_kept_price) {
      return '<span class="hq-offer-price">' + HQ.money(offer.price_incl) + ' <span class="hq-offer-unit">sau VAT</span></span>' +
        '<span class="hq-offer-meta">NCC giữ nguyên giá · thu mua gợi ý ' + HQ.money(p.suggested_price) + "</span>" +
        stateTag(p);
    }
    var main = p.vendor_price
      ? '<span class="hq-offer-price">' + HQ.money(p.vendor_price) + ' <span class="hq-offer-unit">NCC báo lại</span></span>'
      : '<span class="hq-offer-price is-proposed">' + HQ.money(p.suggested_price) +
        ' <span class="hq-offer-unit">thu mua gợi ý</span></span>';
    return '<span class="hq-offer-old" title="Giá sau VAT đang trên đơn mua ' + esc(p.order) + '"><s>' +
      HQ.money(p.old_price) + "</s> giá trên đơn</span>" + main + stateTag(p);
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

  /** inCompare: món có ô trên bảng so giá — nút thao tác nằm ở ô, ở đây chỉ còn thông tin. */
  function item(p, inCompare) {
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
    if (p.new_price && !DONE[p.state]) {
      lines.push("<div>Đã gửi duyệt: " + price(p.new_price) + " sau VAT</div>");
    }
    if (p.state === "approved") {
      lines.push('<div class="hq-alloc-ok">Đơn mua đã đổi sang ' + HQ.money(p.new_price) + " sau VAT</div>");
    }
    if (p.reject_reason && p.state === "rejected") {
      lines.push('<div class="hq-expired">Thu mua không duyệt: ' + esc(p.reject_reason) + "</div>");
    }
    if (p.sale_note) {
      lines.push('<div class="hq-muted">Sale ghi: ' + esc(p.sale_note) + "</div>");
    }
    return '<div class="hq-proposal' + (DONE[p.state] ? " is-done" : "") + '">' +
      '<div class="hq-share-head"><span>' + esc(p.product) + "</span>" + HQ.docChip(p.order) +
      '<span class="hq-muted">' + esc(p.vendor) + "</span>" + stateTag(p) + "</div>" +
      lines.join("") + (inCompare ? "" : HQ.proposalActions(p)) + "</div>";
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

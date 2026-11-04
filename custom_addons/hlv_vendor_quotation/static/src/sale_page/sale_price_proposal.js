/* Khối "Thu mua đề xuất giá" trong ngăn phiếu: thu mua không sửa giá đơn mua ở backend nữa mà đề xuất giá gợi ý
   (models/po_price_proposal.py). Sale "Hỏi lại NCC" — món mở lại trên báo giá của NCC, kèm lời nhắn — NCC báo lại
   thì "Gửi thu mua duyệt"; hoặc báo "NCC giữ giá". Giá sau VAT là số chính. */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  var esc = HQ.esc;
  var STATE_CLASS = {
    sale: "hq-tag-warn", vendor: "hq-tag-mine", quoted: "hq-tag-warn", to_approve: "hq-tag-mine",
    rejected: "hq-tag-danger", approved: "hq-tag-ok",
  };
  // Đề xuất đã xong (không còn việc của sale): vẽ gọn, mờ đi.
  var DONE = { approved: true, kept: true };

  HQ.priceProposalBox = function (d) {
    var list = d.price_proposals || [];
    if (!list.length) {
      return "";
    }
    var waiting = list.filter(function (p) { return p.can_requote || p.can_submit; }).length;
    return '<div class="hq-share hq-proposals"><div class="hq-share-head"><b>Thu mua đề xuất giá</b>' +
      (waiting ? '<span class="hq-tag hq-tag-warn">' + waiting + " việc cần sale làm</span>" : "") + "</div>" +
      list.map(item).join("") + "</div>";
  };

  function price(value) {
    return "<b>" + HQ.money(value) + "</b>";
  }

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
    if (p.vendor_price) {
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
      '<span class="hq-muted">' + esc(p.vendor) + "</span>" +
      '<span class="hq-tag ' + (STATE_CLASS[p.state] || "") + '">' + esc(p.state_label) + "</span></div>" +
      lines.join("") + actions(p) + "</div>";
  }

  /** Hỏi lại NCC (lời nhắn sửa được), gửi duyệt, NCC giữ giá. NCC đã báo lại thì ô hỏi lại thu gọn sau nút. */
  function actions(p) {
    var html = "";
    if (p.can_submit) {
      html += '<div class="hq-close-row"><input type="text" class="hq-input hq-close-note" maxlength="255" ' +
        'data-pp-note="' + p.id + '" placeholder="Ghi chú cho thu mua (không bắt buộc)"/>' +
        '<button type="button" class="hq-btn hq-btn-primary" data-pp-submit="' + p.id + '">Gửi thu mua duyệt</button></div>';
    }
    if (p.can_requote) {
      var hidden = p.can_submit;
      html += (hidden ? '<button type="button" class="hq-link-btn" data-pp-reask="' + p.id + '">Hỏi lại NCC lần nữa</button>' : "") +
        '<div class="hq-close-row' + (hidden ? " hq-hidden" : "") + '" data-pp-box="' + p.id + '">' +
        '<label class="hq-sr-only" for="hq-pp-msg-' + p.id + '">Lời nhắn gửi NCC</label>' +
        '<textarea class="hq-input hq-textarea" rows="3" id="hq-pp-msg-' + p.id + '" data-pp-msg="' + p.id + '">' +
        esc(p.vendor_message || p.default_message) + "</textarea>" +
        '<button type="button" class="hq-btn' + (hidden ? "" : " hq-btn-primary") + '" data-pp-requote="' + p.id +
        '" title="Mở lại món này trên báo giá của NCC và gửi lời nhắn — NCC báo lại giá trên trang NCC">Hỏi lại NCC</button></div>';
    }
    if (p.can_keep) {
      html += '<div class="hq-close-row"><button type="button" class="hq-btn hq-btn-mini" data-pp-keep="' + p.id +
        '" title="NCC không giảm — đơn giữ giá cũ, đóng đề xuất">NCC giữ giá</button></div>';
    }
    return html;
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

  function fieldValue(attr, id) {
    var el = HQ.$("hq-drawer-panel").querySelector("[" + attr + '="' + id + '"]');
    return el ? el.value : "";
  }

  HQ.bindPriceProposalEvents = function () {
    var panel = HQ.$("hq-drawer-panel");
    HQ.on(panel, "click", "[data-pp-reask]", function (el) {
      panel.querySelector('[data-pp-box="' + el.dataset.ppReask + '"]').classList.toggle("hq-hidden");
    });
    HQ.on(panel, "click", "[data-pp-requote]", function (el) {
      var id = +el.dataset.ppRequote;
      send("price_requote", { proposal_id: id, message: fieldValue("data-pp-msg", id) }, el,
        "Đã mở lại món trên báo giá và nhắn NCC — chờ NCC báo lại giá");
    });
    HQ.on(panel, "click", "[data-pp-submit]", function (el) {
      var id = +el.dataset.ppSubmit;
      send("price_submit", { proposal_id: id, note: fieldValue("data-pp-note", id) }, el, "Đã gửi thu mua duyệt giá mới");
    });
    HQ.on(panel, "click", "[data-pp-keep]", function (el) {
      var note = window.prompt("NCC giữ giá cũ — ghi chú cho thu mua (không bắt buộc):", "");
      if (note === null) {
        return;
      }
      send("price_keep", { proposal_id: +el.dataset.ppKeep, note: note }, el, "Đã báo thu mua: NCC giữ giá");
    });
  };
})(window.HlvQuote);

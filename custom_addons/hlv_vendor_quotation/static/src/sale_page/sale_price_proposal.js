/* Thu mua trả về một dòng đơn mua (models/po_price_proposal.py + po_proposal_change.py): giá gợi ý, SL, mã thay thế —
   đều tuỳ chọn — kèm lý do. Việc của sale nằm ngay trên ô giá của bảng so giá (ô + dòng tô màu, giá trên đơn gạch đi):
   "Hỏi lại NCC" mở popup (sale_price_proposal_form.js) — sale chốt mã / SL rồi hỏi NCC hoặc gửi thẳng
   thu mua; NCC báo lại thì "Gửi thu mua duyệt"; hoặc "NCC giữ giá". Đầu ngăn chỉ còn một dải "việc cần làm" dẫn tới
   ô, cộng một dòng ngắn cho mỗi đề xuất đã xong — mỗi thông tin chỉ hiện một chỗ. Giá sau VAT là số chính. */
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

  /** Ô giá thuộc đề xuất: ô của món trên đơn, hoặc ô mã mới khi đổi mã. */
  function ownsCell(p, quoteLineId) {
    return p.quote_line_id === quoteLineId || (!!p.new_quote_line_id && p.new_quote_line_id === quoteLineId);
  }

  /** Đề xuất còn mở của một ô giá (id dòng báo giá) — mới nhất trước (payload xếp id giảm). Không có → null. */
  HQ.openProposal = function (d, quoteLineId) {
    return (d.price_proposals || []).find(function (p) {
      return ownsCell(p, quoteLineId) && !DONE[p.state];
    }) || null;
  };

  HQ.proposalById = function (id) {
    return ((HQ.addVendorDetail || {}).price_proposals || []).find(function (p) { return p.id === id; }) || { id: id };
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
  /** Đề xuất còn việc của sale (hỏi lại NCC / gửi duyệt / giữ giá) — popup "Xử lý tất cả" (sale_price_proposal_bulk.js). */
  HQ.proposalTodo = function (d) {
    return (d.price_proposals || []).filter(function (p) {
      return !DONE[p.state] && (p.can_requote || p.can_submit || p.can_keep);
    });
  };

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
    return '<div class="hq-todo" role="status"><div><b>Thu mua trả về ' + todo.length + " món</b>" +
      "<span>" + (submit ? "NCC đã báo lại — gửi thu mua duyệt" : "Hỏi lại NCC / gửi thu mua") +
      " ngay trên ô tô cam ở bảng So giá, hoặc xử lý tất cả một lần</span></div>" +
      '<div class="hq-pp-actions"><button type="button" class="hq-btn" data-pp-jump="1">Đến ô cần làm</button>' +
      '<button type="button" class="hq-btn hq-btn-primary" data-ppb-open="1">Xử lý tất cả</button></div></div>';
  }

  /** Đề xuất đã xong: một dòng kết quả. */
  function doneLine(p) {
    return '<div class="hq-proposal is-done">' + esc(p.product) + " " + HQ.docChip(p.order) + " " +
      (p.state === "approved" ? "đơn đã đổi: " + price(p.new_price) + " sau VAT" +
        (p.change_text ? " · " + esc(p.change_text) : "")
        : "NCC giữ giá " + HQ.money(p.old_price)) + "</div>";
  }

  function price(value) {
    return "<b>" + HQ.money(value) + "</b>";
  }

  function stateTag(p) {
    return '<span class="hq-tag ' + (STATE_CLASS[p.state] || "") + '">' + esc(p.state_label) + "</span>";
  }

  /** Nhãn đầu ô so giá: đề xuất đang ở bước nào, ai phải làm — nhìn là biết NCC đã báo lại chưa. [chữ, lớp màu] */
  function cellTag(p) {
    if (p.state === "quoted") {
      if (p.vendor_kept_price) {
        return ["NCC giữ nguyên giá", "hq-tag-warn"];
      }
      return p.vendor_price ? ["NCC đã báo mới", "hq-tag-ok"] : ["NCC không có hàng", "hq-tag-danger"];
    }
    return {
      sale: ["Thu mua trả về — sale xử lý", "hq-tag-warn"],
      vendor: ["Chờ NCC báo", "hq-tag-mine"],
      to_approve: ["Chờ thu mua duyệt", "hq-tag-mine"],
      rejected: ["Thu mua không duyệt", "hq-tag-danger"],
    }[p.state] || [p.state_label, ""];
  }

  function pct(rate) {
    return HQ.qty(rate || 0) + "%";
  }

  /** Giá trong ô so giá có đề xuất còn mở, một hàng: giá trên đơn gạch → giá NCC báo lại (hoặc thu mua gợi ý khi NCC
   chưa báo). NCC giữ nguyên giá thì không gạch — giá trên đơn vẫn là giá đang dùng. Dưới: VAT đổi (nếu có), lý do (khi
   NCC chưa báo — lúc sale cần để hỏi), chờ ai, và nút "Chi tiết" mở các bước báo giá cũ → thu mua đề xuất → NCC báo lại.
   Giá NCC khác không nhắc: đã nằm ở các cột bên cạnh. */
  HQ.proposalPrice = function (offer, p) {
    var swapCell = offer.line_id === p.new_quote_line_id;
    var head;
    if (p.vendor_kept_price) {
      head = HQ.money(p.old_price) + ' <span class="hq-offer-unit">NCC giữ nguyên giá</span>';
    } else if (p.vendor_price || p.suggested_price) {
      head = (swapCell ? "" : '<s class="hq-offer-old" title="Giá sau VAT đang trên đơn mua ' + esc(p.order) + '">' +
        HQ.money(p.old_price) + "</s> → ") + (p.vendor_price
        ? HQ.money(p.vendor_price) + ' <span class="hq-offer-unit">NCC báo lại</span>'
        : '<span class="is-proposed">' + HQ.money(p.suggested_price) + '</span> <span class="hq-offer-unit">thu mua gợi ý</span>');
    } else {
      // Thu mua chỉ ghi lý do / đổi SL, mã — chưa có giá mới nào để gạch giá cũ.
      head = HQ.money(swapCell ? offer.price_incl : p.old_price) + ' <span class="hq-offer-unit">' +
        (p.state === "quoted" ? "NCC không có hàng" : swapCell ? "chờ NCC báo giá" : "giá trên đơn") + "</span>";
    }
    var notes = [
      swapCell ? '<span class="hq-offer-short">Mã thay cho ' + esc(p.product) + "</span>" : "",
      p.change_text ? '<span class="hq-offer-short">' + esc(p.change_text) + "</span>"
        : buyerWish(p) ? '<span class="hq-offer-short">Thu mua muốn: ' + buyerWish(p) + "</span>" : "",
      p.vat_warning ? '<span class="hq-offer-short" title="' + esc(p.vat_warning) + '">VAT ' + pct(p.tax_rate) + " → " +
        pct(p.vendor_tax_rate) + "</span>" : "",
      p.buyer_note && !p.vendor_price ? '<span class="hq-offer-meta">Lý do: ' + esc(p.buyer_note) + "</span>" : "",
      p.reject_reason && p.state === "rejected"
        ? '<span class="hq-offer-short">Thu mua không duyệt: ' + esc(p.reject_reason) + "</span>" : "",
    ];
    var tag = cellTag(p);
    var when = p.state === "quoted" && p.vendor_date ? ' title="NCC báo lúc ' + esc(p.vendor_date) + '"' : "";
    return '<span class="hq-tag ' + tag[1] + '"' + when + ">" + esc(tag[0]) + "</span>" +
      '<span class="hq-offer-price">' + head + "</span>" + notes.join("") +
      '<button type="button" class="hq-link-btn hq-pp-detail-btn" data-pp-detail="' + p.id + '">Chi tiết</button>' +
      '<div class="hq-pp-steps hq-hidden" data-pp-steps="' + p.id + '">' + steps(p) + "</div>";
  };

  /** SL / mã thu mua đề xuất (sale chưa chốt) — "SL 1 → 2 Cái · mã X"; "" khi thu mua chỉ ghi giá / lý do. */
  function buyerWish(p) {
    return [p.suggested_drop ? "không mua nữa (SL " + HQ.qty(p.old_qty) + " → 0)"
      : p.suggested_qty ? "SL " + HQ.qty(p.old_qty) + " → " + HQ.qty(p.suggested_qty) + " " + esc(p.uom) : "",
      p.suggested_product ? "mã " + esc(p.suggested_product.name) : "",
      p.suggested_vat ? "VAT " + pct(p.tax_rate) + " → " + (p.suggested_vat === "kct" ? "KCT" : p.suggested_vat + "%") : ""]
      .filter(Boolean).join(" · ");
  }

  /** Các bước của đề xuất: báo giá cũ → thu mua đề xuất → NCC báo lại (→ đã gửi duyệt). */
  function steps(p) {
    var rows = [["Giá trên đơn", HQ.money(p.old_price) + " · VAT " + pct(p.tax_rate)],
      ["Thu mua đề xuất", [p.suggested_price ? HQ.money(p.suggested_price) : "", buyerWish(p), esc(p.buyer), esc(p.date)]
        .filter(Boolean).join(" · ") + (p.buyer_note ? "<br>Lý do: " + esc(p.buyer_note) : "")]];
    if (p.change_text && p.state !== "sale") {
      rows.push(["Sale chốt", esc(p.change_text) + (p.needs_vendor ? "" : " · gửi thẳng thu mua, không hỏi NCC")]);
    }
    if (p.vendor_price) {
      rows.push(["NCC báo lại", HQ.money(p.vendor_price) + " · VAT " + pct(p.vendor_tax_rate) +
        (p.vendor_date ? " · " + esc(p.vendor_date) : "")]);
    }
    if (p.new_price) {
      rows.push(["Đã gửi duyệt", HQ.money(p.new_price) + (p.sale_note ? " · " + esc(p.sale_note) : "")]);
    }
    return "<ol>" + rows.map(function (r) { return "<li><b>" + r[0] + "</b> " + r[1] + "</li>"; }).join("") + "</ol>" +
      (p.vat_warning ? '<div class="hq-muted">' + esc(p.vat_warning) + "</div>" : "");
  }

  /** Nút việc của sale cho một đề xuất — trên ô so giá (hoặc ở khối phía trên khi món không có ô). */
  HQ.proposalActions = function (p) {
    var html = "";
    if (p.can_submit) {
      html += '<button type="button" class="hq-btn hq-btn-mini hq-btn-primary" data-pp-submit="' + p.id +
        '" title="Gửi giá NCC vừa báo lại cho thu mua duyệt — duyệt xong đơn mua đổi giá">Gửi thu mua duyệt</button>';
    }
    if (p.can_requote) {
      html += '<button type="button" class="hq-btn hq-btn-mini' + (p.can_submit ? "" : " hq-btn-primary") +
        '" data-pp-form="' + p.id + '" title="Chốt mã / SL rồi hỏi NCC hoặc gửi thẳng thu mua">' +
        (p.can_submit ? "Hỏi lại lần nữa" : "Hỏi lại NCC") + "</button>";
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

  HQ.proposalSend = send;

  /** Gọi API của đề xuất rồi vẽ lại phiếu. Trả promise → true khi xong, false khi lỗi (đã báo lỗi). */
  function send(name, params, button, message) {
    button.disabled = true;
    return HQ.api(name, params).then(function (detail) {
      HQ.renderInquiry(detail);
      HQ.toast(message);
      HQ.reloadAll();
      return true;
    }).catch(function (err) {
      button.disabled = false;
      HQ.toast(err.message);
      return false;
    });
  }

  /** Hộp nhập trên nút bấm (ô so giá hẹp, không đặt ô nhập dài được). Bấm Huỷ → null = không gửi. */
  function ask(question, value) {
    return window.prompt(question, value || "");
  }

  HQ.bindPriceProposalEvents = function () {
    var panel = HQ.$("hq-drawer-panel");
    HQ.bindProposalFormEvents(panel);
    HQ.bindProposalBulkEvents(panel);
    HQ.on(panel, "click", "[data-pp-detail]", function (el) {
      panel.querySelector('[data-pp-steps="' + el.dataset.ppDetail + '"]').classList.toggle("hq-hidden");
    });
    HQ.on(panel, "click", "[data-pp-jump]", function () {
      var cell = panel.querySelector(".hq-offer.has-proposal");
      if (cell) {
        cell.scrollIntoView({ behavior: "smooth", block: "center" });
        cell.classList.remove("is-flash");
        void cell.offsetWidth;  // vẽ lại để bấm lần nữa vẫn nháy
        cell.classList.add("is-flash");
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

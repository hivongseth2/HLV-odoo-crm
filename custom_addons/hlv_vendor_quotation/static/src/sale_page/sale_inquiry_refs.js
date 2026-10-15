/* Thông tin của phiếu hỏi giá và YCMH (ngăn phiếu, sale_compare.js gọi):
   - "Sale" ở đầu ngăn: mã sale của phiếu = "Người yêu cầu" của YCMH — chỗ DUY NHẤT chọn mã. Phiếu chưa có
     mã thì điền sẵn mã đang xem trên đầu trang; lên YCMH gửi luôn mã đang chọn ở ô này (chưa bấm Lưu cũng
     được — server ghi làm mã của phiếu). Đổi mã sau → YCMH lập từ trang này ghi theo;
   - lên YCMH: địa điểm giao, kho nhận hàng, ghi chú từng dòng (giữ qua các lần vẽ lại);
   - "Mã đơn hàng của khách": có ngay khi phiếu đã lên YCMH, chưa cần đơn mua — ghi vào YCMH (đơn mua tạo
     sau tự lấy) và các đơn mua đã có (controllers/sale_page.py set_order_ref). */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  var esc = HQ.esc;
  // Thông tin lên YCMH sale đang nhập, theo phiếu: {delivery, pickingType, notes: {id dòng báo giá: ghi chú}}.
  var drafts = {};

  function codes() {
    return (HQ.S.config && HQ.S.config.codes) || [];
  }

  function options(selected) {
    var list = codes().map(function (c) { return c.code; });
    if (selected && list.indexOf(selected) < 0) {
      list.unshift(selected);  // mã cũ của phiếu không thuộc tài khoản này — vẫn hiện đúng
    }
    return (selected ? "" : '<option value="">— Chọn mã sale —</option>') + list.map(function (code) {
      return '<option value="' + esc(code) + '"' + (code === selected ? " selected" : "") + ">" +
        esc(HQ.saleLabel(code)) + "</option>";
    }).join("");
  }

  /** Mã gợi ý cho phiếu chưa có mã: mã đang xem trên đầu trang (không phải "Tất cả"). */
  function pageCode() {
    var S = HQ.S;
    return S.code && S.code !== S.config.all_code ? S.code : "";
  }

  /** Ô "Sale" ở đầu ngăn phiếu: chọn + Lưu; không sửa được thì chỉ hiện tên. */
  HQ.saleCodeFact = function (d) {
    if (!d.can_set_sale_code || !codes().length) {
      return d.sale_code ? '<div class="hq-fact"><span class="hq-label">Sale</span>' + esc(HQ.saleLabel(d.sale_code)) + "</div>" : "";
    }
    return '<div class="hq-fact"><label class="hq-label" for="hq-sale-code">Sale (người yêu cầu YCMH)</label>' +
      '<span class="hq-opp-edit"><select id="hq-sale-code" class="hq-input hq-sale-code">' +
      options(d.sale_code || pageCode()) + "</select>" +
      '<button type="button" class="hq-btn hq-btn-mini" data-save-sale-code="1">Lưu</button></span></div>';
  };

  /** Ô "Hạn báo giá": sửa được khi Cài đặt bật (can_set_deadline) — không thì chỉ hiện ngày. */
  HQ.deadlineFact = function (d) {
    if (!d.can_set_deadline) {
      return d.deadline ? '<div class="hq-fact"><span class="hq-label">Hạn báo giá</span>' + esc(d.deadline) + "</div>" : "";
    }
    return '<div class="hq-fact"><label class="hq-label" for="hq-deadline-edit">Hạn báo giá</label><span class="hq-opp-edit">' +
      '<input type="date" id="hq-deadline-edit" class="hq-input" min="' + esc(HQ.S.config.today) + '" value="' +
      esc(d.deadline_iso) + '"/><button type="button" class="hq-btn hq-btn-mini" data-save-deadline="1">Lưu</button></span></div>';
  };

  function saveDeadline(button) {
    var d = HQ.addVendorDetail;
    var value = HQ.$("hq-deadline-edit").value;
    if (!value) {
      HQ.toast("Chọn ngày hạn báo giá");
      return;
    }
    button.disabled = true;
    HQ.api("set_deadline", { inquiry_id: d.id, deadline: value }).then(function (detail) {
      HQ.renderInquiry(detail);
      HQ.toast("Đã đổi hạn báo giá thành " + detail.deadline + " — NCC thấy hạn mới");
      HQ.reloadAll();
    }).catch(function (err) {
      button.disabled = false;
      HQ.toast(err.message);
    });
  }

  /** Mã sale gửi lên khi tạo YCMH: mã đang chọn ở ô Sale ("" = chưa chọn). */
  HQ.requestCode = function (d) {
    var select = HQ.$("hq-sale-code");
    return select ? select.value : d.sale_code || "";
  };

  function draft(d) {
    if (!drafts[d.id]) {
      drafts[d.id] = { delivery: "", pickingType: HQ.S.config.default_picking_type_id || "", dateWanted: "", notes: {} };
    }
    return drafts[d.id];
  }

  /** Ô ghi chú cho một dòng ở bảng tóm tắt lên YCMH. quoteLineId: id dòng báo giá. */
  HQ.requestNoteCell = function (d, quoteLineId) {
    return '<td><input type="text" class="hq-input hq-req-note" maxlength="255" data-req-note="' + quoteLineId +
      '" value="' + esc(draft(d).notes[quoteLineId] || "") + '" placeholder="Ghi chú dòng…"/></td>';
  };

  /** Ngày muốn nhận hàng + kho nhận + địa điểm giao của YCMH (bước xác nhận lên YCMH). */
  HQ.requestFieldsHtml = function (d) {
    var dr = draft(d);
    var types = HQ.S.config.picking_types || [];
    return '<div class="hq-request-fields">' +
      '<label><span class="hq-label">Ngày muốn nhận hàng</span><input type="date" class="hq-input" required="required" ' +
      'data-req-field="dateWanted" min="' + esc(HQ.S.config.today || "") + '" value="' + esc(dr.dateWanted) + '"/></label>' +
      '<label><span class="hq-label">Kho nhận hàng</span><select class="hq-input" data-req-field="pickingType">' +
      types.map(function (t) {
        return '<option value="' + t.id + '"' + (String(t.id) === String(dr.pickingType) ? " selected" : "") + ">" +
          esc(t.name) + "</option>";
      }).join("") + "</select></label>" +
      '<label class="hq-grow"><span class="hq-label">Địa điểm giao</span><input type="text" class="hq-input" maxlength="255" ' +
      'data-req-field="delivery" value="' + esc(dr.delivery) + '" placeholder="Để trống nếu giao về kho nhận"/></label></div>';
  };

  /** Thông tin thêm gửi kèm create_request. */
  HQ.requestExtras = function (d) {
    var dr = draft(d);
    return {
      delivery_address: dr.delivery, picking_type_id: +dr.pickingType || null, date_wanted: dr.dateWanted || null,
      line_notes: dr.notes,
    };
  };

  HQ.clearRequestDraft = function (d) {
    delete drafts[d.id];
  };

  /** Khung mã đơn hàng cho cả phiếu (đã lên YCMH hoặc có đơn mua). */
  HQ.orderRefBox = function (d) {
    if (!d.can_set_order_ref) {
      return "";
    }
    return HQ.originEditor("inquiry", d.order_ref, [], "Cập nhật", function (detail) {
      HQ.renderInquiry(detail);
    }, d.id);
  };

  function saveSaleCode(button) {
    var d = HQ.addVendorDetail;
    var code = HQ.$("hq-sale-code").value;
    if (!code) {
      HQ.toast("Chọn mã sale");
      return;
    }
    button.disabled = true;
    HQ.api("set_sale_code", { inquiry_id: d.id, sale_code: code }).then(function (detail) {
      HQ.renderInquiry(detail);
      HQ.toast("Đã đổi mã sale của phiếu" + (detail.requests.length ? " và người yêu cầu trên YCMH" : ""));
      HQ.reloadAll();
    }).catch(function (err) {
      button.disabled = false;
      HQ.toast(err.message);
    });
  }

  HQ.bindInquiryRefEvents = function () {
    var panel = HQ.$("hq-drawer-panel");
    HQ.on(panel, "click", "[data-save-sale-code]", saveSaleCode);
    HQ.on(panel, "click", "[data-save-deadline]", saveDeadline);
    HQ.on(panel, "input", "[data-req-note]", function (el) {
      draft(HQ.addVendorDetail).notes[el.dataset.reqNote] = el.value;
    });
    HQ.on(panel, "input", "[data-req-field]", function (el) {
      draft(HQ.addVendorDetail)[el.dataset.reqField] = el.value;
    });
    HQ.on(panel, "change", "[data-req-field]", function (el) {
      draft(HQ.addVendorDetail)[el.dataset.reqField] = el.value;
    });
  };
})(window.HlvQuote);

/* Mã sale và mã đơn hàng của một phiếu hỏi giá (ngăn phiếu, sale_compare.js gọi):
   - "Sale": đổi mã sale của phiếu bất cứ lúc nào — YCMH lập từ trang này ghi theo làm "Người yêu cầu";
   - khung lên YCMH: chọn mã sale (người yêu cầu) BẮT BUỘC, điền sẵn mã của phiếu, không có thì mã đang
     chọn trên đầu trang;
   - "Mã đơn hàng của khách": có ngay khi phiếu đã lên YCMH, chưa cần đơn mua — ghi vào YCMH (đơn mua tạo
     sau tự lấy) và các đơn mua đã có (controllers/sale_page.py set_order_ref). */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  var esc = HQ.esc;
  var picked = {};  // id phiếu → mã sale đang chọn ở khung lên YCMH (giữ qua các lần vẽ lại)

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

  /** Ô "Sale" ở đầu ngăn phiếu: chọn + Lưu; không sửa được thì chỉ hiện tên. */
  HQ.saleCodeFact = function (d) {
    if (!d.can_set_sale_code || !codes().length) {
      return d.sale_code ? '<div class="hq-fact"><span class="hq-label">Sale</span>' + esc(HQ.saleLabel(d.sale_code)) + "</div>" : "";
    }
    return '<div class="hq-fact"><label class="hq-label" for="hq-sale-code">Sale</label><span class="hq-opp-edit">' +
      '<select id="hq-sale-code" class="hq-input">' + options(d.sale_code) + "</select>" +
      '<button type="button" class="hq-btn hq-btn-mini" data-save-sale-code="1">Lưu</button></span></div>';
  };

  /** Mã sale mặc định cho khung lên YCMH: đã chọn trước đó → mã của phiếu → mã đang xem trên trang. */
  function defaultCode(d) {
    if (picked[d.id] !== undefined) {
      return picked[d.id];
    }
    var S = HQ.S;
    return d.sale_code || (S.code && S.code !== S.config.all_code ? S.code : "");
  }

  HQ.requestCodePicker = function (d) {
    return '<label class="hq-req-code"><span class="hq-label">Người yêu cầu (mã sale) *</span>' +
      '<select id="hq-req-code" class="hq-input">' + options(defaultCode(d)) + "</select></label>";
  };

  /** Mã sale đã chọn cho YCMH ("" = chưa chọn). */
  HQ.requestCode = function (d) {
    var select = HQ.$("hq-req-code");
    return select ? select.value : defaultCode(d);
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
      delete picked[d.id];
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
    HQ.on(panel, "change", "#hq-req-code", function (el) {
      picked[HQ.addVendorDetail.id] = el.value;
    });
  };
})(window.HlvQuote);

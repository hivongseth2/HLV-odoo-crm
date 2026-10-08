/* Đóng phiếu "Không mua" (khách không lấy, giá cao…). Khác "Huỷ phiếu" (hỏi nhầm): giá NCC đã
   báo vẫn giữ tới ngày hiệu lực — phiếu sau của bất kỳ sale nào hỏi cùng NCC, cùng sản phẩm sẽ
   tự dùng lại, không phải hỏi lại NCC. */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  var esc = HQ.esc;

  /** Nút + khung chọn lý do ở cuối ngăn phiếu (chỉ phiếu đang hỏi giá). */
  HQ.closeBox = function (d) {
    if (!d.can_close) {
      return "";
    }
    var reasons = (HQ.S.config.close_reasons || []).map(function (r) {
      return '<option value="' + esc(r[0]) + '">' + esc(r[1]) + "</option>";
    }).join("");
    return '<div class="hq-close-box hq-hidden" id="hq-close-box">' +
      '<div class="hq-share-head"><b>Không mua — đóng phiếu</b>' +
      '<span class="hq-muted">Giá NCC đã báo vẫn được giữ tới ngày hiệu lực để lần sau dùng lại.</span></div>' +
      '<div class="hq-close-row"><label class="hq-sr-only" for="hq-close-reason">Lý do</label>' +
      '<select id="hq-close-reason" class="hq-input">' + reasons + "</select>" +
      '<label class="hq-sr-only" for="hq-close-note">Ghi chú</label>' +
      '<input type="text" id="hq-close-note" class="hq-input hq-close-note" maxlength="255" placeholder="Ghi chú (không bắt buộc)"/>' +
      '<button type="button" class="hq-btn hq-btn-primary" data-close-confirm="1">Đóng phiếu</button>' +
      '<button type="button" class="hq-btn" data-close-toggle="1">Thôi</button></div></div>';
  };

  /** Phiếu đã đóng: lý do + nhắc giá vẫn dùng lại được. */
  HQ.closedBanner = function (d) {
    if (d.sale_status !== "closed") {
      return "";
    }
    return '<div class="hq-share hq-closed-note"><b>Không mua' + (d.close_reason ? " — " + esc(d.close_reason) : "") +
      "</b>" + (d.close_note ? '<div class="hq-muted">' + esc(d.close_note) + "</div>" : "") +
      '<div class="hq-muted">Giá NCC trong phiếu vẫn giữ tới ngày hiệu lực: lập phiếu mới với cùng NCC, cùng sản phẩm ' +
      "là giá được điền sẵn, không phải hỏi lại.</div></div>";
  };

  function confirmClose(button) {
    button.disabled = true;
    HQ.api("close", {
      inquiry_id: HQ.S.openInquiryId,
      reason: HQ.$("hq-close-reason").value,
      note: HQ.$("hq-close-note").value,
    }).then(function () {
      HQ.toast("Đã đóng phiếu — giá NCC vẫn được giữ");
      HQ.openInquiry(HQ.S.openInquiryId, true);
      HQ.reloadAll();
    }).catch(function (err) {
      HQ.toast(err.message);
      button.disabled = false;
    });
  }

  HQ.bindCloseEvents = function () {
    var panel = HQ.$("hq-drawer-panel");
    HQ.on(panel, "click", "[data-close-toggle]", function () {
      HQ.$("hq-close-box").classList.toggle("hq-hidden");
    });
    HQ.on(panel, "click", "[data-close-confirm]", confirmClose);
  };
})(window.HlvQuote);

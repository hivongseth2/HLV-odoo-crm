/* Bản scan đã ký (PDF) trên ngăn soạn: tải lên, xem, thay, xoá (Quản lý). Nằm ngoài phần ô nhập bị
   khoá vì thường tải lên lúc hợp đồng đã xác nhận. Tải lên cho hợp đồng đang "Đã xác nhận" thì hỏi
   đánh dấu "Đã ký" luôn. Dùng các hàm ngăn soạn qua HD.form. */
window.HlvContract = window.HlvContract || {};

(function (HD) {
  "use strict";

  var S = HD.S;
  var esc = HD.esc;

  /** Giờ server (UTC, "YYYY-MM-DD HH:MM:SS") -> giờ máy người xem. */
  function localTime(utc) {
    var d = utc ? new Date(utc.replace(" ", "T") + "Z") : null;
    return d && !isNaN(d) ? d.toLocaleString("vi-VN", { dateStyle: "short", timeStyle: "short" }) : "";
  }

  /** Khung "Bản scan đã ký" của hợp đồng đã lưu; hợp đồng mới chưa có gì để gắn -> "". */
  HD.signedHtml = function () {
    var c = S.contract;
    if (!c) {
      return "";
    }
    var s = c.signed;
    var input = '<input type="file" id="hd-signed-file" class="hd-hidden" accept=".pdf,application/pdf"/>';
    if (!s) {
      return '<section class="hd-step hd-signed"><h3 class="hd-h3">Bản scan đã ký</h3>' +
        '<div class="hd-signed-row"><span class="hd-muted hd-small">Chưa có. Khách ký xong, scan thành một file PDF rồi tải lên để lưu kèm.</span>' +
        '<button type="button" class="hd-btn hd-btn-primary hd-btn-mini" data-signed-pick="1">Tải lên bản đã ký (PDF)</button>' +
        input + "</div></section>";
    }
    return '<section class="hd-step hd-signed"><h3 class="hd-h3">Bản scan đã ký</h3>' +
      '<div class="hd-signed-row"><a class="hd-signed-file" href="' + s.url + '" target="_blank" rel="noopener">📄 ' +
      esc(s.filename) + "</a>" +
      '<span class="hd-muted hd-small">tải lên ' + esc(localTime(s.uploaded_at)) + " · " + esc(s.uploaded_by) + "</span>" +
      '<span class="hd-push d-flex gap-2">' +
      '<a class="hd-btn hd-btn-mini" href="' + s.url + '?download=1">Tải về</a>' +
      '<button type="button" class="hd-btn hd-btn-mini" data-signed-pick="1">Thay file</button>' +
      (S.config.is_manager ? '<button type="button" class="hd-btn hd-btn-mini hd-btn-danger-soft" data-signed-delete="1">Xoá</button>' : "") +
      "</span>" + input + "</div></section>";
  };

  /** Sau khi tải lên: hợp đồng đang chờ ký thì hỏi đánh dấu "Đã ký". */
  function offerSign(detail) {
    if (detail.state !== "confirmed" || detail.actions.indexOf("sign") < 0 ||
        !window.confirm("Đã có bản ký. Đánh dấu hợp đồng " + detail.name + " là Đã ký luôn?")) {
      return detail;
    }
    return HD.api("action", { contract_id: detail.id, action: "sign" });
  }

  function upload(file) {
    if (!/\.pdf$/i.test(file.name) && file.type !== "application/pdf") {
      HD.toast("Chỉ nhận file PDF", "error");
      return;
    }
    if (S.contract.signed && !window.confirm("Thay bản đã ký đang lưu (" + S.contract.signed.filename + ") bằng file mới?")) {
      return;
    }
    HD.toast("Đang tải lên…");
    HD.form.saveIfDirty().then(function (detail) {
      return HD.readFileBase64(file).then(function (data) {
        return HD.api("signed/upload", { contract_id: detail.id, filename: file.name, data: data });
      });
    }).then(function (detail) {
      HD.toast("Đã lưu bản ký");
      return offerSign(detail);
    }).then(HD.showContractDetail).catch(HD.fail);
  }

  HD.initSigned = function () {
    var panel = HD.$("hd-drawer-panel");
    HD.on(panel, "click", "[data-signed-pick]", function () { HD.$("hd-signed-file").click(); });
    HD.on(panel, "change", "#hd-signed-file", function (el) {
      if (el.files && el.files[0]) {
        upload(el.files[0]);
      }
      el.value = "";
    });
    HD.on(panel, "click", "[data-signed-delete]", function () {
      if (window.confirm("Xoá bản scan đã ký " + S.contract.signed.filename + "? Việc xoá được ghi nhật ký.")) {
        HD.api("signed/delete", { contract_id: S.contract.id }).then(HD.showContractDetail).catch(HD.fail);
      }
    });
  };
})(window.HlvContract);

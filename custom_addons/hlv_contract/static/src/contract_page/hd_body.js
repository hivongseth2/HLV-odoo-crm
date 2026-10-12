/* Sửa chữ trên riêng một hợp đồng: mở nội dung của hợp đồng (bản chụp từ mẫu, hoặc bản đã
   sửa trước đó) trong trình soạn, biến vẫn là ô vàng tự điền. Lưu chỉ đổi hợp đồng này —
   mẫu gốc và các hợp đồng khác giữ nguyên. */
window.HlvContract = window.HlvContract || {};

(function (HD) {
  "use strict";

  var contractId = null;
  var varDefs = [];       // biến của hợp đồng + biến mới chèn trong lúc sửa (gửi kèm khi lưu)
  var editorApi = null;

  HD.openBodyEditor = function (id) {
    HD.api("body", { contract_id: id }).then(function (result) {
      contractId = id;
      varDefs = result.variables.map(function (v) { return Object.assign({}, v); });
      HD.$("hd-body-title").textContent = "Sửa nội dung · " + result.name;
      editorApi = HD.mountEditor(HD.$("hd-body-host"), result.html, {
        variables: function () { return varDefs; },
        onAddVariable: function (def) { varDefs.push(def); },
      });
      HD.openModal("hd-body");
    }).catch(HD.fail);
  };

  function save() {
    HD.api("body/save", { contract_id: contractId, body_html: editorApi.getHtml(), variables: varDefs }).then(function (detail) {
      HD.closeModal("hd-body");
      HD.showContractDetail(detail);
      HD.toast("Đã lưu nội dung riêng của " + detail.name);
    }).catch(HD.fail);
  }

  function reset() {
    if (!window.confirm("Bỏ phần chữ đã sửa, lấy lại nội dung theo mẫu hiện tại? Giá trị đã điền được giữ.")) {
      return;
    }
    HD.api("apply_template", { contract_id: contractId }).then(function (detail) {
      HD.closeModal("hd-body");
      HD.showContractDetail(detail);
      HD.toast("Đã khôi phục nội dung theo mẫu");
    }).catch(HD.fail);
  }

  HD.initBody = function () {
    HD.$("hd-body-save").addEventListener("click", save);
    HD.$("hd-body-reset").addEventListener("click", reset);
  };
})(window.HlvContract);

/* Nhật ký hợp đồng: mục "Nhật ký" cuối ngăn soạn (một hợp đồng) và màn Nhật ký của Quản lý
   (mọi hợp đồng, kể cả đã xoá). Chỉ đọc. */
window.HlvContract = window.HlvContract || {};

(function (HD) {
  "use strict";

  var esc = HD.esc;
  var ACTION_CLASS = {
    create: "hd-tag-ok",
    update: "hd-tag-soft",
    body: "hd-tag-mine",
    template: "hd-tag-mine",
    state: "hd-tag-warn",
    export: "hd-tag-muted",
    signed: "hd-tag-ok",
    delete: "hd-tag-danger",
  };
  var all = { search: "", action: "", page: 1 };

  function entryHtml(log, withContract) {
    var details = log.details.length
      ? '<ul class="hd-log-details">' + log.details.map(function (line) { return "<li>" + esc(line) + "</li>"; }).join("") + "</ul>"
      : "";
    var contract = withContract
      ? (log.contract_id
        ? '<button type="button" class="hd-link" data-open="' + log.contract_id + '">' + esc(log.contract_name) + "</button>"
        : '<span class="hd-muted" title="Hợp đồng đã bị xoá">' + esc(log.contract_name) + " (đã xoá)</span>")
      : "";
    return '<div class="hd-log">' +
      '<div class="hd-log-meta"><span class="hd-num">' + esc(log.date) + "</span> · <b>" + esc(log.user) + "</b>" +
      (contract ? " · " + contract : "") + "</div>" +
      '<div><span class="hd-tag ' + (ACTION_CLASS[log.action] || "") + '">' + esc(log.action_label) + "</span> " +
      esc(log.summary) + "</div>" + details + "</div>";
  }

  /** Ngăn soạn: mục Nhật ký (thẻ <details>) chỉ tải khi người dùng mở ra. */
  HD.bindContractLogs = function (box, contractId) {
    if (!box) {
      return;
    }
    box.addEventListener("toggle", function () {
      if (!box.open) {
        return;
      }
      var list = box.querySelector(".hd-log-list");
      list.innerHTML = '<div class="hd-muted">Đang tải…</div>';
      HD.api("logs", { contract_id: contractId }).then(function (logs) {
        list.innerHTML = logs.length ? logs.map(function (log) { return entryHtml(log, false); }).join("")
          : '<div class="hd-muted">Chưa có nhật ký.</div>';
      }).catch(HD.fail);
    });
  };

  /* ---------------------------------------------------------- màn Nhật ký (Quản lý) */

  HD.loadAllLogs = function () {
    return HD.api("logs/all", all).then(function (result) {
      var select = HD.$("hd-log-action");
      if (select.options.length <= 1) {
        select.innerHTML = '<option value="">Mọi việc</option>' + result.actions.map(function (a) {
          return '<option value="' + a[0] + '">' + esc(a[1]) + "</option>";
        }).join("");
      }
      HD.$("hd-log-all").innerHTML = result.logs.length
        ? result.logs.map(function (log) { return entryHtml(log, true); }).join("")
        : '<div class="hd-empty">Không có dòng nhật ký nào.</div>';
      all.page = result.page;
      HD.$("hd-log-pager").innerHTML =
        '<button type="button" class="hd-btn hd-btn-mini" data-log-page="' + (result.page - 1) + '"' + (result.page <= 1 ? " disabled" : "") + ">‹ Trước</button>" +
        '<span class="hd-muted">Trang ' + result.page + "/" + result.pages + " · " + result.total + " dòng</span>" +
        '<button type="button" class="hd-btn hd-btn-mini" data-log-page="' + (result.page + 1) + '"' + (result.page >= result.pages ? " disabled" : "") + ">Sau ›</button>";
    }).catch(HD.fail);
  };

  HD.initLogs = function () {
    HD.$("hd-log-search").addEventListener("input", HD.debounce(function (event) {
      all.search = event.target.value.trim();
      all.page = 1;
      HD.loadAllLogs();
    }, 300));
    HD.$("hd-log-action").addEventListener("change", function (event) {
      all.action = event.target.value;
      all.page = 1;
      HD.loadAllLogs();
    });
    HD.on(HD.$("hd-log-pager"), "click", "[data-log-page]", function (el) {
      all.page = +el.dataset.logPage;
      HD.loadAllLogs();
    });
    HD.on(HD.$("hd-log-all"), "click", "[data-open]", function (el) { HD.openContract(+el.dataset.open); });
  };
})(window.HlvContract);

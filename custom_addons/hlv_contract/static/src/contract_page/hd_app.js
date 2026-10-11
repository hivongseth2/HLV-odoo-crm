/* Khởi động trang /hop-dong: nạp cấu hình, chuyển màn, đóng hộp thoại. */
window.HlvContract = window.HlvContract || {};

(function (HD) {
  "use strict";

  var MODALS = ["hd-preview", "hd-export", "hd-import", "hd-seller"];

  function switchView(view) {
    HD.show("hd-view-contracts", view === "contracts");
    HD.show("hd-view-templates", view === "templates");
    document.querySelectorAll("[data-view]").forEach(function (tab) {
      tab.classList.toggle("is-active", tab.dataset.view === view);
    });
    if (view === "templates") {
      HD.loadTemplates();
    }
  }

  function bindGlobal() {
    HD.on(HD.$("hd-nav"), "click", "[data-view]", function (el) { switchView(el.dataset.view); });
    HD.on(HD.$("hd-nav"), "click", "[data-open-seller]", function () { HD.openSeller(); });
    // Nút đóng có data-close="<tên hộp>" (preview, export, import, seller); drawer tự lo trong hd_form.js
    HD.on(document.body, "click", "[data-close]", function (el) {
      var name = el.dataset.close;
      if (name !== "drawer") {
        HD.closeModal("hd-" + name);
      }
    });
    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") {
        return;
      }
      var open = MODALS.filter(function (id) { return !HD.$(id).classList.contains("hd-hidden"); });
      if (open.length) {
        HD.closeModal(open[open.length - 1]);
      } else if (!HD.$("hd-drawer").classList.contains("hd-hidden")) {
        HD.closeDrawer(false);
      }
    });
    window.addEventListener("beforeunload", function (event) {
      if (HD.S.dirty) {
        event.preventDefault();
        event.returnValue = "";
      }
    });
  }

  function start() {
    if (!HD.$("hd-app")) {
      return;   // chưa có quyền: trang chỉ hiện thông báo
    }
    HD.api("config").then(function (config) {
      HD.S.config = config;
      document.querySelectorAll("[data-manager]").forEach(function (el) {
        el.classList.toggle("hd-hidden", !config.is_manager);
      });
      bindGlobal();
      HD.initList();
      HD.initGrid();
      HD.initForm();
      HD.initTemplates();
      return HD.loadList();
    }).catch(HD.fail);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})(window.HlvContract);

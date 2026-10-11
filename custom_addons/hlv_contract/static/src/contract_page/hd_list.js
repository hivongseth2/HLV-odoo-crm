/* Màn hợp đồng: thanh sheet (Tất cả + mỗi mẫu một sheet), tab trạng thái, tìm, chọn nhiều để
   xuất / in. Sheet "Tất cả" là danh sách tổng hợp (file này); sheet một mẫu là bảng dữ liệu kiểu
   Excel (hd_grid.js). */
window.HlvContract = window.HlvContract || {};

(function (HD) {
  "use strict";

  var S = HD.S;
  var esc = HD.esc;

  HD.stateTag = function (row) {
    return '<span class="hd-tag ' + (HD.STATE_CLASS[row.state] || "") + '">' + esc(row.state_label) + "</span>";
  };

  HD.checkCell = function (row) {
    return '<td class="hd-col-check"><input type="checkbox" class="hd-check" data-check="' + row.id + '"' +
      (S.selected[row.id] ? " checked" : "") + ' aria-label="Chọn ' + esc(row.name) + '"/></td>';
  };

  HD.rowActions = function (row) {
    return '<td class="hd-right hd-nowrap hd-row-actions">' +
      '<button type="button" class="hd-btn hd-btn-mini" data-open="' + row.id + '">Mở</button>' +
      '<button type="button" class="hd-btn hd-btn-mini" data-preview="' + row.id + '">Xem nhanh</button>' +
      '<button type="button" class="hd-btn hd-btn-mini" data-pdf="' + row.id + '">PDF</button></td>';
  };

  function summaryRow(row) {
    return '<tr data-id="' + row.id + '" class="hd-row' + (S.selected[row.id] ? " is-selected" : "") + '">' +
      HD.checkCell(row) +
      '<td class="hd-strong hd-nowrap">' + esc(row.name) + "</td>" +
      '<td class="hd-nowrap">' + HD.date(row.contract_date) + "</td>" +
      '<td><span class="hd-muted">' + esc(row.template_name) + "</span></td>" +
      "<td>" + esc(row.party_name) +
      (row.party_vat ? '<div class="hd-muted hd-small">MST ' + esc(row.party_vat) + "</div>" : "") + "</td>" +
      '<td class="hd-right hd-num">' + (row.has_lines ? HD.money(row.amount_total) : '<span class="hd-muted">—</span>') + "</td>" +
      '<td class="hd-muted">' + esc(row.user) + "</td>" +
      "<td>" + HD.stateTag(row) + "</td>" + HD.rowActions(row) + "</tr>";
  }

  var SUMMARY_HEAD = '<tr><th class="hd-col-check"><input type="checkbox" id="hd-check-all" aria-label="Chọn tất cả"/></th>' +
    "<th>Số hợp đồng</th><th>Ngày ký</th><th>Mẫu</th><th>Bên mua</th>" +
    '<th class="hd-right">Giá trị (sau VAT)</th><th>Phụ trách</th><th>Trạng thái</th><th></th></tr>';

  /* ---------------------------------------------------------- khung chung */

  function renderTabs(counts) {
    var tabs = [["all", "Tất cả"]].concat(S.config.states || []);
    HD.$("hd-tabs").innerHTML = tabs.map(function (tab) {
      return '<button type="button" class="hd-tab' + (tab[0] === S.state ? " is-active" : "") +
        '" data-state="' + tab[0] + '">' + esc(tab[1]) +
        '<span class="hd-tab-count">' + (counts[tab[0]] || 0) + "</span></button>";
    }).join("");
  }

  function renderPager(result) {
    var pager = HD.$("hd-pager");
    if (result.pages <= 1) {
      pager.innerHTML = result.total ? '<span class="hd-muted">' + result.total + " hợp đồng</span>" : "";
      return;
    }
    pager.innerHTML =
      '<button type="button" class="hd-btn hd-btn-mini" data-page="' + (result.page - 1) + '"' +
      (result.page <= 1 ? " disabled" : "") + ">‹ Trước</button>" +
      '<span class="hd-muted">Trang ' + result.page + "/" + result.pages + " · " + result.total + " hợp đồng</span>" +
      '<button type="button" class="hd-btn hd-btn-mini" data-page="' + (result.page + 1) + '"' +
      (result.page >= result.pages ? " disabled" : "") + ">Sau ›</button>";
  }

  /** Vẽ phần chung sau khi tải một trang dữ liệu (tab trạng thái, phân trang, ô chọn). */
  HD.afterLoad = function (result) {
    S.page = result.page;
    renderTabs(result.counts);
    renderPager(result);
    HD.renderSelection();
  };

  function selectedIds() {
    return Object.keys(S.selected).map(Number);
  }

  HD.renderSelection = function () {
    var count = selectedIds().length;
    HD.$("hd-export-open").disabled = !count;
    HD.$("hd-selected-count").textContent = count ? "(" + count + ")" : "";
    var all = HD.$("hd-check-all");
    if (all) {
      all.checked = !!S.rows.length && S.rows.every(function (row) { return S.selected[row.id]; });
    }
  };

  /** Thanh sheet: "Tất cả hợp đồng" + mỗi mẫu đang dùng một sheet. */
  HD.refreshSheets = function () {
    var templates = (S.config.templates || []).filter(function (t) { return t.active; });
    if (S.sheet !== "all" && !templates.some(function (t) { return t.id === S.sheet; })) {
      S.sheet = "all";
    }
    HD.$("hd-sheets").innerHTML =
      '<button type="button" class="hd-sheet' + (S.sheet === "all" ? " is-active" : "") + '" data-sheet="all">Tất cả hợp đồng</button>' +
      templates.map(function (t) {
        return '<button type="button" class="hd-sheet' + (S.sheet === t.id ? " is-active" : "") + '" data-sheet="' + t.id +
          '" title="Bảng dữ liệu kiểu Excel: mỗi biến của mẫu là một cột">' + esc(t.name) + "</button>";
      }).join("");
  };

  function loadSummary() {
    HD.show("hd-grid-add", false);
    HD.show("hd-sheet-hint", false);
    return HD.api("list", { search: S.search, state: S.state, page: S.page }).then(function (result) {
      S.rows = result.contracts;
      HD.$("hd-thead").innerHTML = SUMMARY_HEAD;
      HD.$("hd-list").innerHTML = S.rows.length
        ? S.rows.map(summaryRow).join("")
        : '<tr><td colspan="9" class="hd-empty">Chưa có hợp đồng nào' +
          (S.search ? " khớp “" + esc(S.search) + "”" : "") + ".</td></tr>";
      HD.afterLoad(result);
    }).catch(HD.fail);
  }

  /** Tải lại màn đang xem (danh sách tổng hợp hoặc bảng dữ liệu một mẫu). */
  HD.loadList = function () {
    return S.sheet === "all" ? loadSummary() : HD.loadGrid();
  };

  function openExport(ids) {
    S.exportIds = ids;
    HD.$("hd-export-count").textContent = ids.length + " hợp đồng sẽ được xuất. Excel: mỗi mẫu một sheet.";
    HD.openModal("hd-export");
  }

  HD.initList = function () {
    S.sheet = "all";
    HD.refreshSheets();
    HD.$("hd-search").addEventListener("input", HD.debounce(function (event) {
      S.search = event.target.value.trim();
      S.page = 1;
      HD.loadList();
    }, 300));
    HD.on(HD.$("hd-sheets"), "click", "[data-sheet]", function (el) {
      S.sheet = el.dataset.sheet === "all" ? "all" : +el.dataset.sheet;
      S.page = 1;
      HD.refreshSheets();
      HD.loadList();
    });
    HD.on(HD.$("hd-tabs"), "click", "[data-state]", function (el) {
      S.state = el.dataset.state;
      S.page = 1;
      HD.loadList();
    });
    HD.on(HD.$("hd-pager"), "click", "[data-page]", function (el) {
      S.page = +el.dataset.page;
      HD.loadList();
    });

    var table = HD.$("hd-table");
    HD.on(table, "change", "[data-check]", function (el) {
      var id = +el.dataset.check;
      if (el.checked) {
        S.selected[id] = true;
      } else {
        delete S.selected[id];
      }
      el.closest("tr").classList.toggle("is-selected", el.checked);
      HD.renderSelection();
    });
    HD.on(table, "change", "#hd-check-all", function (el) {
      S.rows.forEach(function (row) {
        if (el.checked) {
          S.selected[row.id] = true;
        } else {
          delete S.selected[row.id];
        }
      });
      HD.loadList();
    });
    HD.on(table, "click", "[data-open]", function (el) { HD.openContract(+el.dataset.open); });
    HD.on(table, "click", "[data-preview]", function (el) { HD.openPreview(+el.dataset.preview); });
    HD.on(table, "click", "[data-pdf]", function (el) { HD.download(HD.exportUrl([+el.dataset.pdf], "pdf")); });
    // Danh sách tổng hợp: bấm vào dòng thì mở ngăn soạn (bảng dữ liệu thì bấm ô để sửa tại chỗ)
    HD.on(table, "click", "tr.hd-row[data-id]", function (el, event) {
      if (S.sheet === "all" && !event.target.closest("input, button")) {
        HD.openContract(+el.dataset.id);
      }
    });

    HD.$("hd-new").addEventListener("click", function () {
      HD.openContract(null, S.sheet === "all" ? null : S.sheet);
    });
    HD.$("hd-export-open").addEventListener("click", function () { openExport(selectedIds()); });
    HD.$("hd-export-run").addEventListener("click", function () {
      var fmt = (document.querySelector('input[name="hd-fmt"]:checked') || {}).value || "pdf";
      HD.closeModal("hd-export");
      HD.download(HD.exportUrl(S.exportIds || [], fmt));
    });
  };
})(window.HlvContract);

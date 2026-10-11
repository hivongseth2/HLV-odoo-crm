/* Danh sách hợp đồng: tab trạng thái, tìm, chọn nhiều để xuất / in hàng loạt. */
window.HlvContract = window.HlvContract || {};

(function (HD) {
  "use strict";

  var S = HD.S;

  function stateTag(row) {
    return '<span class="hd-tag ' + (HD.STATE_CLASS[row.state] || "") + '">' + HD.esc(row.state_label) + "</span>";
  }

  function rowHtml(row) {
    var checked = S.selected[row.id] ? " checked" : "";
    return '<tr data-id="' + row.id + '" class="hd-row' + (S.selected[row.id] ? " is-selected" : "") + '">' +
      '<td class="hd-col-check"><input type="checkbox" class="hd-check" data-check="' + row.id + '"' + checked +
      ' aria-label="Chọn ' + HD.esc(row.name) + '"/></td>' +
      '<td class="hd-strong hd-nowrap">' + HD.esc(row.name) + "</td>" +
      '<td class="hd-nowrap">' + HD.date(row.contract_date) + "</td>" +
      '<td><span class="hd-type hd-type-' + row.contract_type + '">' + HD.esc(row.type_label) + "</span></td>" +
      "<td>" + HD.esc(row.buyer_name) +
      (row.buyer_vat ? '<div class="hd-muted hd-small">MST ' + HD.esc(row.buyer_vat) + "</div>" : "") + "</td>" +
      '<td class="hd-right hd-num">' + (row.line_count ? HD.money(row.amount_total) : '<span class="hd-muted">—</span>') + "</td>" +
      '<td class="hd-muted">' + HD.esc(row.user) + "</td>" +
      "<td>" + stateTag(row) + "</td>" +
      '<td class="hd-right hd-nowrap hd-row-actions">' +
      '<button type="button" class="hd-btn hd-btn-mini" data-preview="' + row.id + '">Xem nhanh</button>' +
      '<button type="button" class="hd-btn hd-btn-mini" data-pdf="' + row.id + '">PDF</button>' +
      "</td></tr>";
  }

  function renderTabs(counts) {
    var tabs = [["all", "Tất cả"]].concat(S.config.states || []);
    HD.$("hd-tabs").innerHTML = tabs.map(function (tab) {
      return '<button type="button" class="hd-tab' + (tab[0] === S.state ? " is-active" : "") +
        '" data-state="' + tab[0] + '">' + HD.esc(tab[1]) +
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

  function selectedIds() {
    return Object.keys(S.selected).map(Number);
  }

  function renderSelection() {
    var count = selectedIds().length;
    HD.$("hd-export-open").disabled = !count;
    HD.$("hd-selected-count").textContent = count ? "(" + count + ")" : "";
    var visible = S.rows.length && S.rows.every(function (row) { return S.selected[row.id]; });
    HD.$("hd-check-all").checked = !!visible;
  }

  HD.loadList = function () {
    return HD.api("list", { search: S.search, state: S.state, contract_type: S.type, page: S.page }).then(function (result) {
      S.rows = result.contracts;
      S.page = result.page;
      renderTabs(result.counts);
      renderPager(result);
      HD.$("hd-list").innerHTML = S.rows.length
        ? S.rows.map(rowHtml).join("")
        : '<tr><td colspan="9" class="hd-empty">Chưa có hợp đồng nào' +
          (S.search ? " khớp “" + HD.esc(S.search) + "”" : "") + ".</td></tr>";
      renderSelection();
    }).catch(HD.fail);
  };

  function openExport(ids) {
    S.exportIds = ids;
    HD.$("hd-export-count").textContent = ids.length + " hợp đồng sẽ được xuất.";
    HD.openModal("hd-export");
  }

  HD.openExport = openExport;

  HD.initList = function () {
    HD.$("hd-type-filter").innerHTML = HD.typeOptions("", true);
    HD.$("hd-search").addEventListener("input", HD.debounce(function (event) {
      S.search = event.target.value.trim();
      S.page = 1;
      HD.loadList();
    }, 300));
    HD.$("hd-type-filter").addEventListener("change", function (event) {
      S.type = event.target.value;
      S.page = 1;
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

    var list = HD.$("hd-list");
    HD.on(list, "change", "[data-check]", function (el) {
      var id = +el.dataset.check;
      if (el.checked) {
        S.selected[id] = true;
      } else {
        delete S.selected[id];
      }
      el.closest("tr").classList.toggle("is-selected", el.checked);
      renderSelection();
    });
    HD.on(list, "click", "[data-preview]", function (el) { HD.openPreview(+el.dataset.preview); });
    HD.on(list, "click", "[data-pdf]", function (el) { HD.download(HD.exportUrl([+el.dataset.pdf], "pdf")); });
    // Bấm vào dòng (trừ ô chọn và nút) thì mở ngăn soạn
    HD.on(list, "click", "tr[data-id]", function (el, event) {
      if (!event.target.closest("input, button")) {
        HD.openContract(+el.dataset.id);
      }
    });
    HD.$("hd-check-all").addEventListener("change", function (event) {
      S.rows.forEach(function (row) {
        if (event.target.checked) {
          S.selected[row.id] = true;
        } else {
          delete S.selected[row.id];
        }
      });
      HD.loadList();
    });

    HD.$("hd-new").addEventListener("click", function () { HD.openContract(null); });
    HD.$("hd-export-open").addEventListener("click", function () { openExport(selectedIds()); });
    HD.$("hd-export-run").addEventListener("click", function () {
      var fmt = (document.querySelector('input[name="hd-fmt"]:checked') || {}).value || "pdf";
      HD.closeModal("hd-export");
      HD.download(HD.exportUrl(S.exportIds || [], fmt));
    });
  };
})(window.HlvContract);

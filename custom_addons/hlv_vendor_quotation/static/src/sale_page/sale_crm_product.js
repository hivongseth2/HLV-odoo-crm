/* Hàng có trên MISA CRM mà Odoo chưa có (controllers/sale_page_crm.py):
   - ô "Thêm sản phẩm" không thấy trong Odoo → dòng "Tìm trên MISA CRM" → khung kết quả CRM, bấm
     "Thêm" là tạo sản phẩm Odoo từ CRM rồi đưa vào phiếu;
   - khung dán danh sách (sale_paste.js) dùng HQ.crmMatchRows / HQ.crmImport cho dòng "không thấy". */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  var esc = HQ.esc;
  var found = [];   // kết quả CRM đang hiện trong khung

  /** Dòng đã dán → [{best: mã CRM chắc chắn hoặc "", candidates}] cùng thứ tự. */
  HQ.crmMatchRows = function (lines) {
    return HQ.rpc("/api/hoi-gia-ncc/crm_match_rows", { lines: lines }).then(function (res) { return res.rows || []; });
  };

  /** Mã CRM → [{code, product?, created?, error?}] cùng thứ tự (server tạo sản phẩm nếu Odoo chưa có). */
  HQ.crmImport = function (codes) {
    return HQ.rpc("/api/hoi-gia-ncc/import_products", { codes: codes }).then(function (res) { return res.results || []; });
  };

  /** "mã — tên · ĐVT" của một hàng CRM (ô chọn, danh sách). */
  HQ.crmLabel = function (p) {
    return p.code + " — " + p.name + (p.unit ? " · " + p.unit : "");
  };

  HQ.openCrmSearch = function (term) {
    var box = HQ.$("hq-crm-results");
    HQ.show("hq-crm-results", true);
    box.innerHTML = '<div class="hq-loading">Đang tìm "' + esc(term) + '" trên MISA CRM…</div>';
    HQ.rpc("/api/hoi-gia-ncc/crm_products", { search: term }).then(function (res) {
      found = res.products || [];
      render(term);
    }).catch(function (err) {
      box.innerHTML = '<div class="hq-alert">' + esc(err.message) + "</div>";
    });
  };

  function render(term) {
    var head = '<div class="hq-share-head"><b>Trên MISA CRM</b><span class="hq-muted">"' + esc(term) +
      '" — chưa có trong Odoo thì bấm Thêm để tạo sản phẩm (tên, ĐVT, giá, thuế theo CRM).</span>' +
      '<span class="hq-spacer"></span><button type="button" class="hq-btn hq-btn-mini" data-crm-close="1">Đóng</button></div>';
    if (!found.length) {
      HQ.$("hq-crm-results").innerHTML = head + '<div class="hq-muted">MISA CRM cũng không có hàng này.</div>';
      return;
    }
    HQ.$("hq-crm-results").innerHTML = head + '<div class="hq-table-wrap"><table class="hq-table"><tbody>' +
      found.map(function (p, index) {
        return "<tr><td class=\"hq-nowrap\">" + esc(p.code) + "</td><td>" + esc(p.name) +
          (p.odoo_exists ? ' <span class="hq-tag hq-tag-ok">Odoo đã có</span>' : "") + "</td>" +
          "<td>" + esc(p.unit) + '</td><td class="hq-num">' + (p.price ? HQ.money(p.price) : "") + "</td>" +
          '<td class="hq-num">' + (p.is_combo
            ? '<span class="hq-muted" title="Hàng combo cần dựng thành phần — tạo qua đơn bán">combo</span>'
            : '<button type="button" class="hq-btn hq-btn-mini hq-btn-primary" data-crm-add="' + index + '">Thêm</button>') +
          "</td></tr>";
      }).join("") + "</tbody></table></div>";
  }

  function add(button, item) {
    button.disabled = true;
    HQ.crmImport([item.code]).then(function (results) {
      var result = results[0] || {};
      if (result.error) {
        throw new Error(result.error);
      }
      HQ.addCreateLines([result.product]);
      HQ.toast(result.created ? "Đã tạo sản phẩm " + item.code + " từ MISA CRM và thêm vào phiếu"
        : "Đã thêm " + item.code + " vào phiếu");
      HQ.show("hq-crm-results", false);
    }).catch(function (err) {
      button.disabled = false;
      HQ.toast(err.message);
    });
  }

  HQ.bindCrmEvents = function () {
    var modal = HQ.$("hq-modal");
    HQ.on(modal, "click", "[data-crm-add]", function (el) { add(el, found[+el.dataset.crmAdd]); });
    HQ.on(modal, "click", "[data-crm-close]", function () { HQ.show("hq-crm-results", false); });
  };
})(window.HlvQuote);

/* Văn bản căn cứ vào văn bản khác trên ngăn soạn: ô "Căn cứ" (phụ lục → hợp đồng nguyên tắc, đề nghị
   thanh toán → phụ lục / hợp đồng mua bán), phần thanh toán theo đợt, số báo giá CRM, danh sách văn
   bản liên quan và nút "+ Phụ lục" / "+ Đề nghị thanh toán". Dùng các hàm ngăn soạn qua HD.form. */
window.HlvContract = window.HlvContract || {};

(function (HD) {
  "use strict";

  var S = HD.S;
  var esc = HD.esc;
  // Khoá của S.form thuộc phần này, gửi kèm khi lưu / xem trước
  var PAYLOAD_KEYS = ["parent_id", "quote_code", "payment_no", "payment_percent", "payment_amount_manual"];

  function typeLabel(type) {
    var found = (S.config.types || []).filter(function (t) { return t[0] === type; })[0];
    return found ? found[1] : "";
  }

  function parentTypes(type) {
    return (S.config.parent_types || {})[type] || [];
  }

  /** Giá trị mặc định của phần này cho S.form (văn bản mới hoặc nạp từ chi tiết đã lưu). */
  HD.linkFormDefaults = function (detail) {
    var d = detail || {};
    var payment = d.payment || {};
    return {
      parent_id: d.parent ? d.parent.id : false,
      parent_label: d.parent ? d.parent.name + " · " + d.parent.party_name : "",
      parent_type: d.parent ? d.parent.contract_type : "",
      quote_code: d.quote_code || "",
      payment_no: d.payment_no || 1,
      payment_percent: d.payment_percent != null ? d.payment_percent : 100,
      payment_amount_manual: d.payment_amount_manual || 0,
      payment_base: payment.base || 0,
      payment_previous: payment.previous || 0,
    };
  };

  HD.linkPayload = function () {
    var out = {};
    PAYLOAD_KEYS.forEach(function (key) { out[key] = S.form[key]; });
    out.parent_id = S.form.parent_id || false;
    return out;
  };

  /* ---------------------------------------------------------- HTML */

  function parentHtml(type) {
    var allowed = parentTypes(type).map(typeLabel).join(" / ").toLowerCase();
    var chosen = S.form.parent_id
      ? '<div class="hd-link-chosen"><span class="hd-linked-tag">● ' + esc(S.form.parent_label) + "</span>" +
        ' <button type="button" class="hd-btn hd-btn-mini" data-unlink-parent="1">Bỏ</button></div>'
      : '<div class="hd-muted hd-small">Chưa chọn — câu "căn cứ hợp đồng số … ký ngày …" sẽ để trống.</div>';
    return '<div class="hd-picker"><label class="hd-label" for="hd-parent-search">Căn cứ ' + esc(allowed) + "</label>" +
      '<input type="search" id="hd-parent-search" class="hd-input w-100" autocomplete="off" ' +
      'placeholder="Số văn bản hoặc tên khách — để trống là văn bản của khách đang chọn"/>' +
      '<div id="hd-parent-results" class="hd-dropdown hd-hidden"></div>' + chosen + "</div>";
  }

  function paymentNumbers() {
    var f = S.form;
    var auto = Math.round((f.payment_base || 0) * (f.payment_percent || 0) / 100);
    var amount = f.payment_amount_manual > 0 ? f.payment_amount_manual : auto;
    return { auto: auto, amount: amount, remaining: (f.payment_base || 0) - (f.payment_previous || 0) - amount };
  }

  function paymentInfoHtml() {
    var n = paymentNumbers();
    return "Giá trị văn bản gốc <b>" + HD.money(S.form.payment_base) + "</b> · đã đề nghị các đợt trước <b>" +
      HD.money(S.form.payment_previous) + "</b> · đợt này <b>" + HD.money(n.amount) + "</b> · còn lại <b>" +
      HD.money(n.remaining) + "</b>";
  }

  function paymentHtml() {
    var f = S.form;
    var input = function (key, label, value, extra) {
      return '<div class="hd-field"><label class="hd-label" for="hd-l-' + key + '">' + label + "</label>" +
        '<input type="text" class="hd-input w-100 hd-right" id="hd-l-' + key + '" data-link="' + key + '" value="' +
        esc(value) + '"' + (extra || "") + "/></div>";
    };
    return '<div class="hd-grid">' +
      input("payment_no", "Đợt thanh toán", f.payment_no) +
      input("payment_percent", "Tỷ lệ đợt này (%)", HD.qty(f.payment_percent)) +
      input("payment_amount_manual", "Số tiền đề nghị", f.payment_amount_manual ? HD.money(f.payment_amount_manual) : "",
        ' placeholder="' + esc(HD.money(paymentNumbers().auto)) + '" title="Để trống: theo tỷ lệ"') +
      '</div><div class="hd-muted hd-small mt-1" id="hd-payment-info">' + paymentInfoHtml() + "</div>";
  }

  function relatedHtml() {
    var c = S.contract;
    if (!c || (!c.parent && !(c.children || []).length)) {
      return "";
    }
    var row = function (doc, role) {
      return '<li><span class="hd-muted">' + role + "</span> " +
        '<button type="button" class="hd-link" data-open="' + doc.id + '">' + esc(doc.name) + "</button> " +
        esc(doc.type_label) + (doc.payment_no ? " đợt " + doc.payment_no : "") + " · " + HD.money(doc.amount_total) +
        " · " + HD.stateTag(doc) + "</li>";
    };
    return '<ul class="hd-related">' + (c.parent ? row(c.parent, "Căn cứ:") : "") +
      (c.children || []).map(function (doc) { return row(doc, "↳"); }).join("") + "</ul>";
  }

  /** Phần "Căn cứ & thanh toán" của ngăn soạn; "" nếu loại văn bản này không cần gì. */
  HD.linksHtml = function () {
    var tpl = HD.form.template();
    var type = tpl.contract_type;
    var parts = [];
    if (parentTypes(type).length) {
      parts.push(parentHtml(type));
    }
    if (tpl.has_lines) {
      parts.push('<div class="hd-grid"><div class="hd-field"><label class="hd-label" for="hd-l-quote_code">Số báo giá CRM</label>' +
        '<input type="text" class="hd-input w-100" id="hd-l-quote_code" data-link="quote_code" value="' + esc(S.form.quote_code) +
        '" placeholder="Tự điền khi lấy hàng từ báo giá BG…"/></div></div>');
    }
    if (type === "payment") {
      parts.push(paymentHtml());
    }
    var related = relatedHtml();
    if (!parts.length && !related) {
      return "";
    }
    return '<section class="hd-step"><h3 class="hd-h3">' + (type === "payment" ? "Căn cứ & thanh toán" : "Văn bản liên quan") +
      "</h3>" + parts.join("") + related + "</section>";
  };

  /** Nút lập văn bản con trên đầu ngăn (hợp đồng nguyên tắc → phụ lục; phụ lục / mua bán → đề nghị thanh toán). */
  HD.childButtonsHtml = function (c) {
    if (!c || c.state === "cancel") {
      return "";
    }
    return (S.config.types || []).filter(function (t) {
      return parentTypes(t[0]).indexOf(c.contract_type) >= 0;
    }).map(function (t) {
      return '<button type="button" class="hd-btn" data-new-child="' + t[0] + '">+ ' + esc(t[1]) + "</button>";
    }).join("");
  };

  /* ---------------------------------------------------------- thao tác */

  /** Điền phần văn bản gốc trả về từ child_defaults vào form đang soạn. */
  function applyParent(defaults, keepFilled) {
    var f = S.form;
    Object.assign(f, {
      parent_id: defaults.parent_id,
      parent_label: defaults.parent_label,
      parent_type: defaults.parent_type,
      payment_base: defaults.payment_base || 0,
      payment_previous: defaults.payment_previous || 0,
    });
    if (!f.quote_code) {
      f.quote_code = defaults.quote_code || "";
    }
    if (defaults.payment_no) {
      f.payment_no = defaults.payment_no;
      f.payment_percent = defaults.payment_percent;
      f.payment_amount_manual = 0;
    }
    if (!f.partner_id || !keepFilled) {
      f.partner_id = defaults.partner_id;
      f.partner_label = defaults.partner_label;
    }
    if (keepFilled) {
      HD.form.fillVariables(defaults.values || {}, false);
    } else {
      f.values = Object.assign({}, defaults.values || {});
      f.vat_rate = defaults.vat_rate;
    }
  }

  function pickParent(item) {
    var type = HD.form.template().contract_type;
    HD.form.collectForm();
    HD.api("child_defaults", { parent_id: item.id, child_type: type }).then(function (defaults) {
      applyParent(defaults, true);
      HD.form.markDirty(true);
      HD.form.render();
    }).catch(HD.fail);
  }

  function newChild(childType) {
    HD.form.saveIfDirty().then(function (detail) {
      return HD.api("child_defaults", { parent_id: detail.id, child_type: childType });
    }).then(function (defaults) {
      if (!defaults.template_id) {
        HD.toast("Chưa có mẫu " + typeLabel(childType).toLowerCase() + " — Quản lý tạo mẫu trước", "error");
        return;
      }
      HD.openContract(null, defaults.template_id, function () { applyParent(defaults, false); });
    }).catch(HD.fail);
  }

  /** Đổi mẫu sang loại khác: bỏ văn bản gốc không còn hợp loại. */
  HD.checkParentType = function () {
    if (S.form.parent_id && parentTypes(HD.form.template().contract_type).indexOf(S.form.parent_type) < 0) {
      S.form.parent_id = false;
      S.form.parent_label = "";
    }
  };

  HD.collectLinks = function (form) {
    document.querySelectorAll("#hd-form [data-link]").forEach(function (el) {
      var key = el.dataset.link;
      form[key] = key === "quote_code" ? el.value.trim() : HD.parseNumber(el.value);
    });
  };

  HD.bindLinks = function () {
    var input = HD.$("hd-parent-search");
    if (!input) {
      return;
    }
    HD.bindPicker(input, HD.$("hd-parent-results"), function (term) {
      return HD.api("parents", {
        contract_type: HD.form.template().contract_type, search: term, partner_id: S.form.partner_id || false,
      });
    }, function (doc) {
      return '<span class="hd-strong">' + esc(doc.name) + "</span> " + esc(doc.party_name) +
        ' <span class="hd-muted">' + esc(doc.type_label) + " · " + HD.date(doc.contract_date) + " · " +
        HD.money(doc.amount_total) + "</span>";
    }, pickParent);
  };

  HD.initLinks = function () {
    var panel = HD.$("hd-drawer-panel");
    HD.on(panel, "input", "[data-link]", function () {
      HD.collectLinks(S.form);
      var info = HD.$("hd-payment-info");
      if (info) {
        info.innerHTML = paymentInfoHtml();
        HD.$("hd-l-payment_amount_manual").placeholder = HD.money(paymentNumbers().auto);
      }
      HD.form.markDirty(true);
    });
    HD.on(panel, "focusout", '[data-link="payment_amount_manual"]', function (el) {
      el.value = S.form.payment_amount_manual ? HD.money(S.form.payment_amount_manual) : "";
    });
    HD.on(panel, "click", "[data-unlink-parent]", function () {
      HD.form.collectForm();
      S.form.parent_id = false;
      S.form.parent_label = "";
      HD.form.markDirty(true);
      HD.form.render();
    });
    HD.on(panel, "click", "[data-new-child]", function (el) { newChild(el.dataset.newChild); });
    HD.on(panel, "click", ".hd-related [data-open]", function (el) {
      if (!S.dirty || window.confirm("Văn bản đang có thay đổi chưa lưu. Mở văn bản khác và bỏ thay đổi?")) {
        HD.openContract(+el.dataset.open);
      }
    });
  };
})(window.HlvContract);

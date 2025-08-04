(async () => {
  // 🧠 Inject XLSX nếu chưa có
  if (typeof XLSX === "undefined") {
    await new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js";
      script.onload = resolve;
      script.onerror = reject;
      document.head.appendChild(script);
    });
  }

  // 📥 1. Chọn file Excel
  const input = document.createElement("input");
  input.type = "file";
  input.accept = ".xlsx,.xls";
  input.click();

  input.onchange = async () => {
    const file = input.files[0];
    if (!file) return alert("❌ Không có file!");

    const data = await file.arrayBuffer();
    const workbook = XLSX.read(data, { type: "array" });
    const sheet = workbook.Sheets[workbook.SheetNames[0]];
    const json = XLSX.utils.sheet_to_json(sheet, { range: 2 });

    const date = prompt("Nhập ngày (YYYY-MM-DD):", "2025-07-25");
    if (!date) return alert("❌ Thiếu ngày!");

    // 🔐 Thông tin auth
    const token = localStorage.getItem("smeToken");
    const aidEncode = localStorage.getItem("AidEncode");
    const deviceCode = localStorage.getItem("DeviceCode");

    const infoKey = Object.keys(localStorage).find(k => k.startsWith("amisplatformfullinfo_"));
    const dbKey = Object.keys(localStorage).find(k => k.startsWith("databaseconnectedprocess_"));
    const userInfo = JSON.parse(localStorage.getItem(infoKey));
    const dbInfo = JSON.parse(localStorage.getItem(dbKey));


    const context = {
      TenantId: "47ab503b-99d5-4eb8-aa11-24927abb3585",
      TenantCode: "3R2PY2F4",
      DatabaseId: "f4b18d63-6c99-4a53-b974-f6208e84fced",
      BranchId:"53a073a0-5381-4493-820f-51ea32ebe990",
      WorkingBook: 0,
      Language: "vi",
      IncludeDependentBranch: "false",
      SessionId: `ss${userInfo.Data.MISAID}.${deviceCode}.${dbInfo.Data}.${Date.now()}`,
      DBType: 1,
      AuthType: 0,
      AmisSessionId: aidEncode,
      HasAgent: false,
      UserType: 1,
      art: 1,
      UserId: userInfo.Data.MISAID
    };

    const headers = {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${token}`,
      "X-MISA-Context": JSON.stringify(context),
      "X-MISA-BranchID": context.BranchId,
      "X-MISA-Language": context.Language,
      "X-MISA-WorkingBook": context.WorkingBook.toString(),
      "X-Device": deviceCode
    };

    const toDateString = (isoStr) => {
      if (!isoStr) return "";
      const d = new Date(isoStr);
      return d.toLocaleDateString("vi-VN");
    };

    const getAccountObject = async (name) => {
      const payload = {
        sort: `[{"property":34,"desc":false,"data_type":1,"operand":1}]`,
        filter: [
          { property: 2345, value: true, operator: 7, data_type: 1, operand: 1 },
          { property: 2016, value: false, operator: 7, operand: 1, data_type: 1 },
          { property: 488, value: context.BranchId, operator: 7, data_type: 1, operand: 1 }
        ],
        customFilter: [34, 57, 141, 903, 4927].map(p => ({
          property: p,
          value: name,
          operator: 1,
          operand: 2,
          data_type: 1
        })),
        pageIndex: 1,
        pageSize: 20,
        useSp: false
      };

      const res = await fetch("https://actapp.misa.vn/g3/api/di/v1/account_object_get/paging_filter_v2", {
        method: "POST", headers, body: JSON.stringify(payload)
      });
      const json = await res.json();
      return json?.Data?.PageData || [];
    };

    const getVoucherDetails = async (accountObjectId) => {
      const allPages = [];
      let page = 1;

      while (true) {
        const payload = {
          sort: `[{"property":3654,"desc":false,"data_type":3,"operand":1},{"property":3972,"desc":false,"data_type":3,"operand":1},{"property":4008,"desc":false,"data_type":1,"operand":1},{"property":2189,"desc":false,"data_type":1,"operand":1}]`,
          filter: [
            { id: "default", property: 52, value: accountObjectId, operator: 7, operand: 1, data_type: 1 },
            { id: "default", property: 1103, value: "VND", operator: 7, operand: 1 },
            { id: "default", property: 21, value: "131", operator: 7, operand: 1 },
            { id: "default", property: 3654, value: date, operator: 12, operand: 1, data_type: 3 }
          ],
          pageIndex: page,
          pageSize: 20,
          useSp: false,
          view: 182,
          summaryColumns: [308, 268, 4109, 4107, 5775, 5776]
        };

        const res = await fetch("https://actapp.misa.vn/g3/api/gl/v1/gl_voucher_cross_entry_detail/paging_filter_v2", {
          method: "POST", headers, body: JSON.stringify(payload)
        });

        if (!res.ok) break;
        const json = await res.json();
        const pageData = json?.Data?.PageData;
        if (!pageData?.length) break;

        allPages.push(...pageData);
        page++;
      }

      return allPages;
    };

    const renameAndFormat = (item) => {
      return {
        "Loại chứng từ": item.reftype_name || "",
        "Ngày hạch toán": toDateString(item.refdate),
        "Ngày ghi sổ": toDateString(item.posted_date),
        "Số chứng từ": item.refno || "",
        "Số HĐ": item.inv_no || "",
        "Hạn thanh toán": toDateString(item.due_date),
        "Mã NV": item.employee_code || "",
        "Tên nhân viên": item.employee_name || "",
        "Diễn giải": item.description || "",
        "Số tiền (NT)": item.amount_oc || 0,
        "Số tiền (VNĐ)": item.amount || 0,
        "Còn lại (NT)": item.remain_amount_oc || 0,
        "Còn lại (VNĐ)": item.remain_amount || 0,
        "Đã đối trừ (NT)": item.cross_entry_amount_oc || 0,
        "Đã đối trừ (VNĐ)": item.cross_entry_amount || 0,
        "Chiết khấu (NT)": item.discount_amount_oc || 0,
        "Chiết khấu (VNĐ)": item.discount_amount || 0,
        "Tổng CK (NT)": item.total_discount_amount_oc || 0,
        "Tổng CK (VNĐ)": item.total_discount_amount || 0
      };
    };

    const finalResult = [];

    for (let row of json) {
      const name = row["Tên khách hàng"]?.trim();
      if (!name) continue;

      const matches = await getAccountObject(name);
      if (!matches.length) continue;

      for (const match of matches) {
        const details = await getVoucherDetails(match.account_object_id);
        const mapped = details.map(renameAndFormat);
        finalResult.push(...mapped);
      }
    }

    const ws = XLSX.utils.json_to_sheet(finalResult);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Kết quả");
    XLSX.writeFile(wb, `chi_tiet_voucher_${date}.xlsx`);
    alert("✅ Xuất file xong luôn nha đại ca!");
  };
})();

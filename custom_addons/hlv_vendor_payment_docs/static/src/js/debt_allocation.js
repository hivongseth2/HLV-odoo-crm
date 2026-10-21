/**
 * Form trả công nợ NCC (/unc-ncc/cong-no/moi):
 *  - Tìm đơn trong bảng (số đơn / ngày / số tiền), "chỉ đơn đã chọn", chọn tất cả đơn đang hiện. Đơn bị ẩn vẫn giữ
 *    tick và vẫn được gửi.
 *  - Cộng ngay số "trả vào đơn" của các đơn được tick; ô "Số tiền đã chi" tự bằng tổng đó cho tới khi kế toán gõ tay.
 *  - Lỗi / cảnh báo hiện NGAY khi tick hoặc gõ số: hỏi server (/kiem-tra) — quy tắc chỉ nằm ở Python
 *    (debt_allocation_issues), JS không tự phán.
 *  - Bấm lưu: kiểm lại lần cuối. Lỗi → không gửi. Cảnh báo (trả một phần, còn dư, đơn có đề nghị chi chờ duyệt) → hỏi
 *    xác nhận rồi mới gửi. Hỏi bằng fetch nên file UNC đã chọn không mất như khi server vẽ lại form.
 * Không có JS (hoặc fetch lỗi) thì form gửi thẳng, server tự kiểm và vẽ lại kèm cảnh báo.
 */
(function () {
    "use strict";

    const form = document.querySelector("[data-debt-form]");
    if (!form || !window.hlvVendorQuote) {
        return;
    }
    const { parseVnNumber, formatVnNumber } = window.hlvVendorQuote;
    const CHECK_DELAY_MS = 350;
    const amountInput = form.querySelector("[data-debt-amount]");
    const totalCell = form.querySelector("[data-debt-total]");
    const summary = form.querySelector("[data-debt-summary]");
    const issuesBox = form.querySelector("[data-debt-issues]");
    const searchInput = form.querySelector("[data-debt-search]");
    const onlyPicked = form.querySelector("[data-debt-only-picked]");
    const pickAll = form.querySelector("[data-debt-pick-all]");
    const countText = form.querySelector("[data-debt-count]");
    const noMatch = form.querySelector("[data-debt-no-match]");
    const rows = Array.from(form.querySelectorAll("[data-debt-row]")).map((row) => ({
        row,
        pick: row.querySelector("[data-debt-pick]"),
        alloc: row.querySelector("[data-debt-alloc]"),
        // Chữ để tìm: số đơn, ngày, các số tiền — thêm bản bỏ dấu chấm/phẩy để gõ "587238" cũng ra "587.238.231".
        text: row.textContent.replace(/\s+/g, " ").toLowerCase(),
    }));
    rows.forEach((item) => { item.digits = item.text.replace(/[.,]/g, ""); });

    // Kế toán đã gõ số tiền (hoặc server vẽ lại form có sẵn số) thì thôi tự điền.
    let amountTouched = amountInput.value.trim() !== "";
    let checkTimer = null;
    let checkSeq = 0;

    // ------------------------------------------------------------------ tìm / chọn đơn
    function isShown(item) {
        return !item.row.hidden;
    }

    function applyFilter() {
        const query = (searchInput.value || "").trim().toLowerCase();
        const queryDigits = query.replace(/[.,\s]/g, "");
        rows.forEach((item) => {
            const matches = !query || item.text.includes(query) || (/^\d+$/.test(queryDigits) && item.digits.includes(queryDigits));
            item.row.hidden = !matches || (onlyPicked.checked && !item.pick.checked);
        });
        const shown = rows.filter(isShown);
        const picked = rows.filter((item) => item.pick.checked).length;
        noMatch.hidden = shown.length > 0;
        countText.textContent = `Hiện ${shown.length} / ${rows.length} đơn · đã chọn ${picked}`;
        const shownPicked = shown.filter((item) => item.pick.checked).length;
        pickAll.checked = shown.length > 0 && shownPicked === shown.length;
        pickAll.indeterminate = shownPicked > 0 && shownPicked < shown.length;
    }

    // ------------------------------------------------------------------ cộng tiền
    function selectedTotal() {
        return rows.reduce((sum, item) => (item.pick.checked ? sum + (parseVnNumber(item.alloc.value) || 0) : sum), 0);
    }

    function refreshTotals() {
        rows.forEach((item) => item.row.classList.toggle("is-off", !item.pick.checked));
        const total = selectedTotal();
        totalCell.textContent = total ? formatVnNumber(Math.round(total)) : "—";
        if (!amountTouched) {
            amountInput.value = total ? formatVnNumber(Math.round(total)) : "";
        }
        const amount = parseVnNumber(amountInput.value) || 0;
        const diff = Math.round(amount - total);
        summary.textContent = !total && !amount ? "" : `Trả vào đơn ${formatVnNumber(Math.round(total))} · số tiền phiếu `
            + `${formatVnNumber(Math.round(amount))}` + (diff ? ` · ${diff > 0 ? "còn dư" : "thiếu"} ${formatVnNumber(Math.abs(diff))}` : "");
        summary.classList.toggle("is-off-balance", diff !== 0);
    }

    // ------------------------------------------------------------------ lỗi / cảnh báo từ server
    function renderIssues(result) {
        const boxes = [];
        if (result.errors.length) {
            boxes.push(issueBox("Chưa lưu được:", result.errors, "vq-alert vq-alert-error"));
        } else if (result.warnings.length) {
            boxes.push(issueBox("Cần xác nhận khi lưu:", result.warnings, "vq-alert"));
        }
        issuesBox.replaceChildren(...boxes);
    }

    function issueBox(title, messages, cssClass) {
        const box = document.createElement("div");
        box.className = cssClass;
        const head = document.createElement("b");
        head.textContent = title;
        const list = document.createElement("ul");
        list.className = "debt-issues";
        messages.forEach((msg) => {
            const item = document.createElement("li");
            item.textContent = msg;
            list.append(item);
        });
        box.append(head, list);
        return box;
    }

    async function fetchIssues() {
        const data = new FormData(form);
        data.delete("files"); // chỉ kiểm số, khỏi gửi file
        const response = await fetch(form.dataset.checkUrl, { method: "POST", body: data, credentials: "same-origin" });
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        return response.json();
    }

    function nothingEntered() {
        return !rows.some((item) => item.pick.checked) && !amountInput.value.trim();
    }

    function scheduleCheck() {
        clearTimeout(checkTimer);
        if (nothingEntered()) {
            issuesBox.replaceChildren(); // chưa nhập gì — khỏi báo "chưa chọn đơn"
            return;
        }
        checkTimer = setTimeout(async () => {
            const seq = ++checkSeq;
            try {
                const result = await fetchIssues();
                if (seq === checkSeq) { // bỏ kết quả cũ về muộn
                    renderIssues(result);
                }
            } catch (_err) {
                // Mất mạng / hết phiên: bấm lưu thì server vẫn kiểm.
            }
        }, CHECK_DELAY_MS);
    }

    function onEdit(ev) {
        if (ev.target === amountInput) {
            amountTouched = amountInput.value.trim() !== "";
        }
        if (ev.target === searchInput || ev.target === onlyPicked) {
            applyFilter();
            return; // lọc bảng không đổi số tiền
        }
        if (ev.target === pickAll) {
            rows.filter(isShown).forEach((item) => { item.pick.checked = pickAll.checked; });
        }
        refreshTotals();
        applyFilter();
        scheduleCheck();
    }

    // ------------------------------------------------------------------ lưu
    function submitConfirmed() {
        const flag = document.createElement("input");
        flag.type = "hidden";
        flag.name = "confirmed";
        flag.value = "1";
        form.append(flag);
        form.submit(); // không qua sự kiện submit — khỏi hỏi lại
    }

    form.addEventListener("input", onEdit);
    form.addEventListener("change", onEdit);
    // Enter trong ô tìm đơn chỉ để lọc, không gửi form.
    searchInput.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter") {
            ev.preventDefault();
        }
    });

    form.addEventListener("submit", async (ev) => {
        if (ev.submitter && ev.submitter.name === "confirmed") {
            return; // nút "Vẫn lưu" của form server vẽ lại — đã xem cảnh báo
        }
        ev.preventDefault();
        clearTimeout(checkTimer);
        checkSeq += 1; // kết quả kiểm đang chờ (nếu có) không vẽ đè lên kết quả này
        let result;
        try {
            result = await fetchIssues();
        } catch (_err) {
            form.submit(); // không hỏi được → để server kiểm
            return;
        }
        renderIssues(result);
        if (result.errors.length) {
            issuesBox.scrollIntoView({ behavior: "smooth", block: "center" });
            return;
        }
        if (result.warnings.length) {
            const text = result.warnings.map((msg) => `• ${msg}`).join("\n");
            if (!window.confirm(`${text}\n\nVẫn lưu phiếu trả công nợ?`)) {
                return;
            }
        }
        submitConfirmed();
    });

    form.querySelector("[data-debt-tools]").hidden = false;
    refreshTotals();
    applyFilter();
})();

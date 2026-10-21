/**
 * Form trả công nợ NCC (/unc-ncc/cong-no/moi):
 *  - Cộng ngay số "trả vào đơn" của các đơn được tick; ô "Số tiền đã chi" tự bằng tổng đó cho tới khi kế toán gõ tay.
 *  - Bấm lưu: hỏi server (/kiem-tra) lỗi / cảnh báo của phiếu — quy tắc chỉ nằm ở Python (debt_allocation_issues).
 *    Lỗi → hiện, không gửi. Cảnh báo (trả một phần, còn dư, đơn có đề nghị chi chờ duyệt) → hỏi xác nhận rồi mới gửi.
 *    Hỏi trước bằng fetch để file UNC đã chọn không mất như khi server vẽ lại form.
 * Không có JS (hoặc fetch lỗi) thì form gửi thẳng, server tự kiểm và vẽ lại kèm cảnh báo.
 */
(function () {
    "use strict";

    const form = document.querySelector("[data-debt-form]");
    if (!form || !window.hlvVendorQuote) {
        return;
    }
    const { parseVnNumber, formatVnNumber } = window.hlvVendorQuote;
    const amountInput = form.querySelector("[data-debt-amount]");
    const totalCell = form.querySelector("[data-debt-total]");
    const summary = form.querySelector("[data-debt-summary]");
    const issuesBox = document.querySelector("[data-debt-issues]");
    const rows = Array.from(form.querySelectorAll("[data-debt-row]"));
    // Kế toán đã gõ số tiền (hoặc server vẽ lại form có sẵn số) thì thôi tự điền.
    let amountTouched = amountInput.value.trim() !== "";

    function selectedTotal() {
        return rows.reduce((sum, row) => {
            const pick = row.querySelector("[data-debt-pick]");
            return pick.checked ? sum + (parseVnNumber(row.querySelector("[data-debt-alloc]").value) || 0) : sum;
        }, 0);
    }

    function refresh() {
        rows.forEach((row) => row.classList.toggle("is-off", !row.querySelector("[data-debt-pick]").checked));
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

    function showIssues(title, messages, cssClass) {
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
        issuesBox.replaceChildren(box);
        issuesBox.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    function submitConfirmed() {
        const flag = document.createElement("input");
        flag.type = "hidden";
        flag.name = "confirmed";
        flag.value = "1";
        form.append(flag);
        form.submit(); // không qua sự kiện submit — khỏi hỏi lại
    }

    form.addEventListener("input", (ev) => {
        if (ev.target === amountInput) {
            amountTouched = amountInput.value.trim() !== "";
        }
        refresh();
    });
    form.addEventListener("change", refresh);

    form.addEventListener("submit", async (ev) => {
        if (ev.submitter && ev.submitter.name === "confirmed") {
            return; // nút "Vẫn lưu" của form server vẽ lại — đã xem cảnh báo
        }
        ev.preventDefault();
        const data = new FormData(form);
        data.delete("files"); // chỉ kiểm số, khỏi gửi file hai lần
        let result;
        try {
            const response = await fetch(form.dataset.checkUrl, { method: "POST", body: data, credentials: "same-origin" });
            result = await response.json();
        } catch (_err) {
            form.submit(); // không hỏi được → để server kiểm
            return;
        }
        if (result.errors.length) {
            showIssues("Chưa lưu được:", result.errors, "vq-alert vq-alert-error");
            return;
        }
        if (result.warnings.length) {
            showIssues("Cần xác nhận trước khi lưu:", result.warnings, "vq-alert");
            const text = result.warnings.map((msg) => `• ${msg}`).join("\n");
            if (!window.confirm(`${text}\n\nVẫn lưu phiếu trả công nợ?`)) {
                return;
            }
        }
        submitConfirmed();
    });

    refresh();
})();

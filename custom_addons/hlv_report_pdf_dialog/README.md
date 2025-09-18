
# Report PDF Preview Dialog (Odoo 18)

Open qweb-pdf reports inside an in-app dialog (no new tab). Includes **Print** and **Download** buttons.

## Install
- Copy `hlv_report_pdf_dialog` into your addons path.
- Update Apps List and install.
- Depends only on `web`.

## Notes
- Overrides `/report/pdf/...` to return `inline` so the browser can preview.
- Front-end handler fetches the PDF and shows it in a Dialog with an `<iframe>`.

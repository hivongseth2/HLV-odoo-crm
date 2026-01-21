import openpyxl
import os

excel_path = r'e:\project\odoo_HLV\HLV-odoo-crm\custom_addons\hlv_delivery_jt\J&T_Danh mục địa chỉ.xlsx'
output_txt = r'e:\project\odoo_HLV\HLV-odoo-crm\custom_addons\hlv_delivery_jt\scripts\excel_dump_2.txt'

if not os.path.exists(excel_path):
    print(f"File not found: {excel_path}")
else:
    try:
        wb = openpyxl.load_workbook(excel_path, data_only=True)
        sheet = wb['MAPPING']
        
        with open(output_txt, 'w', encoding='utf-8') as f:
            for r in range(10, 21):
                f.write(f"\n--- Row {r} ---\n")
                # Read more columns this time
                for c in range(1, 10):
                    val = sheet.cell(row=r, column=c).value
                    if val:
                        val = str(val).replace('\n', ' | ')
                    f.write(f"Col {c}: {val}\n")
        print(f"Dumped to {output_txt}")

    except Exception as e:
        print(f"Error reading excel: {e}")

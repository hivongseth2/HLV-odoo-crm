import openpyxl
import json
import os

excel_path = r'e:\project\odoo_HLV\HLV-odoo-crm\custom_addons\hlv_delivery_jt\J&T_Danh mục địa chỉ.xlsx'
output_path = r'e:\project\odoo_HLV\HLV-odoo-crm\custom_addons\hlv_delivery_jt\data\jnt_mapping.json'

def normalize(name):
    if not name: return ""
    name = str(name).lower().strip()
    prefixes = [
        'tỉnh ', 'thành phố ', 'quận ', 'huyện ', 'thị xã ', 
        'phường ', 'xã ', 'thị trấn ', 'tp. ', 'tp ', 'q. ', 'h. ', 'p. ', 'x. '
    ]
    for p in prefixes:
        if name.startswith(p):
            name = name[len(p):]
    return name.strip()

if not os.path.exists(os.path.dirname(output_path)):
    os.makedirs(os.path.dirname(output_path))

try:
    wb = openpyxl.load_workbook(excel_path, data_only=True)
    sheet = wb['MAPPING']
    
    data = []
    for row in sheet.iter_rows(min_row=3):
        prov = row[0].value
        dist = row[1].value
        ward_raw = row[2].value
        ward_clean = row[3].value
        
        if not prov or not dist or not ward_raw:
            continue
            
        code = None
        if '-' in str(ward_raw):
            code = str(ward_raw).split('-')[-1].strip()
        
        if code:
            data.append({
                'p': normalize(prov),
                'd': normalize(dist),
                'w': normalize(ward_clean),
                'c': code
            })
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    
    print(f"Successfully converted {len(data)} items to JSON.")
except Exception as e:
    print(f"Error: {e}")

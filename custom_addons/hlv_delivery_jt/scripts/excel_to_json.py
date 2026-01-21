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
        
        if not prov or not dist:
            continue
            
        code = None
        if ward_raw and '-' in str(ward_raw):
            code = str(ward_raw).split('-')[-1].strip()
        
        # Include if we have code OR if we want to allow 2-level addresses (Prov/Dist only)
        # Assuming the goal is to import everything. 
        # If no ward, we still export p/d/pn/dn. 'w' might be empty or None.
        
        data.append({
            'p': normalize(prov),
            'pn': str(prov).strip(),
            'd': normalize(dist),
            'dn': str(dist).strip(),
            'w': str(ward_raw).strip() if ward_raw else "", 
            'c': code if code else ""
        })
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    
    print(f"Successfully converted {len(data)} items to JSON.")
except Exception as e:
    print(f"Error: {e}")

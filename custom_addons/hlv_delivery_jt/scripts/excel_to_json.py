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
    seen = set()

    for row in sheet.iter_rows(min_row=3):
        # 3-Level Address (Old)
        # Col 0: Prov, 1: Dist, 2: Ward+Code, 3: Ward Name
        prov = row[0].value
        dist = row[1].value
        ward_raw_3 = row[2].value
        
        # 2-Level Address (New)
        # Col 4: Prov (New), 5: Ward (New)
        # Note: District is assumed same as Col 1
        prov_new = row[4].value
        ward_new = row[5].value

        if not prov or not dist:
            continue
            
        # Process 3-Level Entry
        code_3 = None
        if ward_raw_3 and '-' in str(ward_raw_3):
            code_3 = str(ward_raw_3).split('-')[-1].strip()
        
        # Key to avoid dupes: (prov, dist, ward, code)
        key_3 = (normalize(prov), normalize(dist), normalize(ward_raw_3) if ward_raw_3 else "", code_3)
        if key_3 not in seen:
            data.append({
                'p': normalize(prov),
                'pn': str(prov).strip(),
                'd': normalize(dist),
                'dn': str(dist).strip(),
                'w': str(ward_raw_3).strip() if ward_raw_3 else "", 
                'c': code_3 if code_3 else ""
            })
            seen.add(key_3)

        # Process 2-Level Entry (Treat as receiving generic ward name)
        # Only if we have a "New Address" ward
        if ward_new:
            # Determining Prov/Dist for 2-level. 
            # Usually Prov New is same as Old, but let's use New if present, else Old.
            p_use = prov_new if prov_new else prov
            d_use = dist # District is shared
            
            # 2-level usually doesn't have a code in the name, or uses the same code?
            # In the dump: "Phường Phước Long" (No code).
            # We treat it as a valid ward name to allow matching.
            
            key_2 = (normalize(p_use), normalize(d_use), normalize(ward_new), "")
            if key_2 not in seen:
                 data.append({
                    'p': normalize(p_use),
                    'pn': str(p_use).strip(),
                    'd': normalize(d_use),
                    'dn': str(d_use).strip(),
                    'w': str(ward_new).strip(),
                    'c': "" # No code for 2-level usually, or we lookup later.
                })
                 seen.add(key_2)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    
    print(f"Successfully converted {len(data)} items to JSON.")
except Exception as e:
    print(f"Error: {e}")

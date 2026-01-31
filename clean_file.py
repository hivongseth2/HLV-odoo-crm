import os

file_path = 'custom_addons/hlv_product_crawler/models/crawler_parsers.py'

try:
    with open(file_path, 'rb') as f:
        content = f.read()
    
    print(f"Original size: {len(content)} bytes")
    
    # Remove null bytes
    clean_content = content.replace(b'\x00', b'')
    
    # Also handle UTF-16 BOM if present
    if clean_content.startswith(b'\xff\xfe') or clean_content.startswith(b'\xfe\xff'):
        clean_content = clean_content[2:]
        
    print(f"Clean size: {len(clean_content)} bytes")
    
    with open(file_path, 'wb') as f:
        f.write(clean_content)
        
    print("File cleaned successfully.")
    
except Exception as e:
    print(f"Error: {e}")

#!/bin/bash
# Upgrade hlv_product_flow_analysis module
echo "=== Upgrading hlv_product_flow_analysis ==="
docker compose run --rm odoo odoo \
  -d test_odoo \
  -u hlv_product_flow_analysis \
  --addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/extra-addons \
  --stop-after-init
echo "=== Done ==="

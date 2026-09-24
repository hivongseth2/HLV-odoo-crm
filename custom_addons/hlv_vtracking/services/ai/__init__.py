# KHÔNG nhập file trong ``models/`` từ các service này. Gói ``services`` bị kéo vào rất
# sớm (một model nhập nó), nên nhập ngược lại một file model sẽ đăng ký lớp ``_inherit``
# trước model gốc và Odoo chết lúc nạp: "Model ... does not exist in registry".
# Hàm dùng chung đặt ở ``tools/``.
from . import context_service
from . import fleet_service
from . import order_service
from . import dispatch_service
from . import picking_service
from . import plan_service
from . import request_service

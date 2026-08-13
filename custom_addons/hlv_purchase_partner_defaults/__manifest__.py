{
    "name": "HLV Purchase Defaults from Partner",
    "version": "18.0.1.0.0",
    "category": "Purchases",
    "summary": "Store payment/delivery terms on the vendor contact and default them onto new Purchase Orders",
    "description": """
        Adds Payment Term, Delivery Term and Delivery Address fields on the
        vendor contact (res.partner). When a Purchase Order's vendor is set
        (manually on the PO form, or via the "Create Purchase Order" wizard
        from a Purchase Request), these values are copied onto the order's
        matching fields (x_studio_iu_kin_thanh_ton, x_studio_delivery_term,
        x_studio_ddgh) and remain editable by the user.
    """,
    "author": "HLV",
    "depends": ["base", "contacts", "purchase", "purchase_request"],
    "data": [
        "views/res_partner_views.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}

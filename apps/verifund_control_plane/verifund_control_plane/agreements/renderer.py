from __future__ import annotations

import html
from typing import Any

RENDERER_VERSION = "v1"


def _money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def render_agreement(terms: dict[str, Any], agreement_id: str, version: int,
                     agreement_hash: str) -> str:
    buyer = terms["parties"]["buyer"]
    seller = terms["parties"]["seller"]
    rows = []
    for item in terms["items"]:
        rows.append(
            "<tr>"
            f"<td>{html.escape(item['sku'])}</td>"
            f"<td>{html.escape(item['name'])}</td>"
            f"<td>{item['quantity']}</td>"
            f"<td>{_money(item['unit_price_cents'])}</td>"
            f"<td>{_money(item['warranty_addon_cents'])}</td>"
            f"<td>{_money(item['line_total_cents'])}</td>"
            "</tr>"
        )
    totals = terms["totals"]
    evidence = ", ".join(html.escape(e) for e in terms["evidence_required"])
    remedies = terms["remedies"]
    doc = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Agreement {html.escape(agreement_id)}</title></head>
<body>
<h1>Verifund Goods Agreement</h1>
<p>Agreement ID: {html.escape(agreement_id)} | Version: {version} | Digest: {html.escape(agreement_hash[:16])}</p>
<h2>Parties</h2>
<p>Buyer: {html.escape(buyer['display_name'])} ({html.escape(buyer['id'])})</p>
<p>Seller: {html.escape(seller['display_name'])} ({html.escape(seller['id'])})</p>
<h2>Items</h2>
<table border="1" cellpadding="4">
<tr><th>SKU</th><th>Name</th><th>Qty</th><th>Unit</th><th>Warranty</th><th>Line total</th></tr>
{''.join(rows)}
</table>
<h2>Totals ({html.escape(totals['currency'])})</h2>
<p>Subtotal: {_money(totals['subtotal_cents'])}</p>
<p>Shipping: {_money(totals['shipping_cents'])}</p>
<p>Tax: {_money(totals['tax_cents'])}</p>
<p>Fees: {_money(totals['fees_cents'])}</p>
<p><strong>Total: {_money(totals['total_cents'])}</strong></p>
<h2>Terms</h2>
<p>Delivery: {terms['delivery']['delivery_days']} days (starts {terms['delivery']['starts_on']})</p>
<p>Warranty: {terms['warranty_months']} months</p>
<p>Returns: {terms['returns_days']} days</p>
<p>Inspection: {terms['inspection']['period_hours']} hours (starts {terms['inspection']['starts_on']})</p>
<p>Evidence required: {evidence}</p>
<p>Remedies: non-delivery={remedies['non_delivery']}, late={remedies['late_delivery']}, damaged={remedies['damaged_goods']}</p>
<p>Dispute window: {terms['dispute_window_hours']} hours</p>
<footer>
<p>Renderer: {RENDERER_VERSION} | Platform terms: {html.escape(terms.get('platform_terms_version','v1'))}</p>
<p>Digest: {html.escape(agreement_hash)}</p>
</footer>
</body>
</html>"""
    return doc

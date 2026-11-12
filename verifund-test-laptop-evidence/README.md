# Verifund Sandbox Test Laptop Evidence

All files in this bundle are synthetic fixtures for `VF-TEST-001` / `AGR-TEST-001`.
They are deliberately marked as SAMPLE or SIMULATED and must never be used as proof
of a real sale, product, warranty, shipment, delivery, or buyer acceptance.

## Files
- `laptop-product-photos.jpg` — synthetic product illustration, not a photograph.
- `hardware-diagnostics.pdf` — fictional diagnostic results for 32 GB RAM and 1 TB SSD.
- `serial-number.jpg` — synthetic serial label.
- `90-day-warranty.pdf` — fictional warranty sample; no actual coverage.
- `paypal-tracking-evidence.json` — tracking fixture. Replace the placeholder PayPal order
  and capture IDs with IDs returned by your own PayPal Sandbox checkout before testing
  the Orders v2 tracking integration.
- `mock-delivery-event.json` — simulated carrier delivery event. Feed this only through
  your sandbox/mock carrier adapter; it is not a PayPal or real carrier delivery event.
- `buyer-acceptance.json` — simulated buyer acceptance fixture. In an end-to-end test,
  prefer generating this through the buyer action/API rather than trusting an uploaded file.
- `manifest.json` — file-to-requirement mapping.

## Suggested requirement IDs
`product_identity`, `hardware_specifications`, `serial_number`, `warranty`,
`shipping_delivery`, `delivery_confirmation`, `buyer_acceptance`.

## Test safety
Set `test_mode=true` in all records. Enforce sandbox mode on the backend and ensure
test evidence cannot satisfy production settlement or payout conditions.

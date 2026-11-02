# VouchFlow AI - Architecture & 3-Way Matching Foundation

## 1. What is 3-Way Matching?
In corporate finance, **3-way matching** is the internal control verification procedure used by Accounts Payable before disbursing supplier payments:

1. **Purchase Order (PO):** What our company ordered (item, agreed price, payment terms).
2. **Goods Received Note (GRN):** What our warehouse staff actually received physically.
3. **Supplier Invoice:** What the vendor is billing us for.

If all three documents agree, the invoice is classified as `verified` and routed for payment approval. If discrepancies exist, payment is paused and human inspection is requested.

```
      +---------------------+
      |   Master Contract   | (Agreed unit pricing & terms)
      +----------+----------+
                 |
                 v
      +---------------------+
      |   Purchase Order    | (Requested quantity & price)
      +----------+----------+
                 |
        +--------+--------+
        |                 |
        v                 v
+---------------+ +---------------+
|  Goods Note   | |Supplier Bill  |
|     (GRN)     | |   (Invoice)   |
+-------+-------+ +-------+-------+
        |                 |
        +--------+--------+
                 |
                 v
      +---------------------+
      |  VouchFlow Matcher  | (Phase 2 Automated Engine)
      +---------------------+
```

## 2. Foundation Database Schema
- **Suppliers:** Master profile of vendors with Indian GSTIN.
- **Contracts:** Master agreement of prices per item and net payment terms.
- **Purchase Orders & PO Items:** Internal issued orders.
- **Goods Received Notes & GRN Items:** Warehouse receipt vouchers.
- **Invoices & Invoice Items:** Vendor bills.
- **Audit Logs:** Immutable audit trail recording user and system actions for SOX/statutory compliance.

## 3. Discrepancy Scenarios Modeled in Foundation
1. **`price_mismatch`:** Invoice unit price > Agreed contract unit price.
2. **`quantity_mismatch`:** Invoice billed quantity > Warehouse GRN received quantity.
3. **`wrong_total`:** Line items sum or tax calculations do not match the grand total.
4. **`duplicate_invoice`:** Re-submission of the same invoice number.
5. **`missing_po`:** Invoice does not quote a valid purchase order.

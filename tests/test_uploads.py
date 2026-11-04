"""
Phase 3 tests: bring your own data.

- invoice uploads: wrong type, empty, fake file (wrong signature), too large -> clear errors;
  a good file lands in the user's own workspace folder
- PO / GRN / contract-price CSVs: missing columns and bad rows are reported with row
  numbers and NOTHING is imported; good files import into the own workspace only;
  the downloadable templates import cleanly
- contract documents: TXT accepted with a Supplier line, bad files refused
- "Demo data" vs "Live workspace", reset to sample data, delete workspace
"""

import pytest
from fastapi.testclient import TestClient

from backend.database.db import SessionLocal
from backend.database.models import Contract, GoodsReceivedNote, Invoice, PurchaseOrder, Supplier
from backend.main import app
from backend.services import upload_service, workspace_service
from backend.services.upload_service import UploadError
from tests.helpers import temp_user

PDF = b"%PDF-1.4\n% fake but correctly signed test invoice\n"


@pytest.fixture()
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture()
def empty_user():
    with temp_user(load_sample=False) as u:
        yield u


# ---------------------------------------------------------------------
# Invoice files
# ---------------------------------------------------------------------
@pytest.mark.parametrize("name, data, message", [
    ("virus.exe", b"MZ....", "Invalid file type"),
    ("invoice.pdf", b"", "empty"),
    ("invoice.pdf", b"this is not a pdf at all", "does not look like a real PDF"),
    ("photo.png", PDF, "does not look like a real PNG"),
    ("huge.pdf", b"%PDF-" + b"0" * (upload_service.MAX_UPLOAD_BYTES + 1), "too large"),
], ids=["wrong-type", "empty", "fake-pdf", "pdf-as-png", "too-large"])
def test_bad_invoice_files_are_refused(db, empty_user, name, data, message):
    with pytest.raises(UploadError, match=message):
        upload_service.save_invoice_file(db, empty_user.workspace_id, name, data)
    assert db.query(Invoice).filter(Invoice.workspace_id == empty_user.workspace_id).count() == 0


def test_good_invoice_lands_in_own_workspace_folder(db, empty_user):
    result = upload_service.save_invoice_file(db, empty_user.workspace_id, "My Invoice #7.pdf", PDF)
    inv = db.query(Invoice).filter(Invoice.id == result.invoice_id).one()
    assert inv.workspace_id == empty_user.workspace_id and inv.status == "needs_review"
    folder = workspace_service.workspace_dir(empty_user.workspace_id) / "invoices"
    assert (folder / result.file_name).read_bytes() == PDF
    assert inv.file_path.startswith(f"data/workspaces/{empty_user.workspace_id}/invoices/")
    assert "#" not in result.file_name and " " not in result.file_name  # safe file name


def test_api_upload_refuses_fake_pdf(empty_user):
    with TestClient(app) as client:
        r = client.post("/invoices/upload", headers=empty_user.headers,
                        files={"file": ("bill.pdf", b"not really a pdf", "application/pdf")})
    assert r.status_code == 400 and "real PDF" in r.json()["detail"]


# ---------------------------------------------------------------------
# CSV imports
# ---------------------------------------------------------------------
def _csv(text: str) -> bytes:
    return text.strip().encode("utf-8") + b"\n"


def test_po_csv_missing_columns(db, empty_user):
    with pytest.raises(UploadError, match="missing these columns: quantity, unit_price"):
        upload_service.import_purchase_orders(db, empty_user.workspace_id,
                                              _csv("po_number,supplier_name,order_date,item_name\nPO-1,A,2026-01-01,X"))


def test_po_csv_bad_rows_import_nothing(db, empty_user):
    bad = _csv("""
po_number,supplier_name,order_date,item_name,quantity,unit_price
PO-1,Acme,2026-01-01,Chair,10,4500
PO-2,Acme,31/01/2026,Desk,2,9000
PO-3,Acme,2026-01-02,Lamp,-1,500
PO-4,,2026-01-02,Pen,1,abc
""")
    with pytest.raises(UploadError) as err:
        upload_service.import_purchase_orders(db, empty_user.workspace_id, bad)
    text = str(err.value)
    assert "row 3" in text and "2026-01-31" in text          # bad date, with the row number
    assert "row 4" in text and "whole number" in text        # negative quantity
    assert "row 5" in text and "supplier_name" in text       # empty supplier
    assert db.query(PurchaseOrder).filter(PurchaseOrder.workspace_id == empty_user.workspace_id).count() == 0


def test_templates_import_into_own_workspace(db, empty_user):
    ws = empty_user.workspace_id
    t = upload_service.TEMPLATES
    po = upload_service.import_purchase_orders(db, ws, t["purchase_orders.csv"].encode())
    grn = upload_service.import_grns(db, ws, t["goods_received_notes.csv"].encode())
    prices = upload_service.import_contract_prices(db, ws, t["contract_prices.csv"].encode())
    assert (po.created, grn.created, prices.created) == (1, 1, 2)

    order = db.query(PurchaseOrder).filter(PurchaseOrder.workspace_id == ws).one()
    assert order.po_number == "PO-1001" and order.total_amount == 10 * 4500 + 5 * 1200
    assert db.query(GoodsReceivedNote).filter(GoodsReceivedNote.workspace_id == ws).one().po_id == order.id
    assert db.query(Contract).filter(Contract.workspace_id == ws).count() == 2
    assert db.query(Supplier).filter(Supplier.workspace_id == ws).count() == 1  # "Acme" reused

    with pytest.raises(UploadError, match="already exists in your workspace"):
        upload_service.import_purchase_orders(db, ws, t["purchase_orders.csv"].encode())


def test_same_po_number_allowed_in_another_workspace(db, empty_user):
    with temp_user(load_sample=False) as other:
        for user in (empty_user, other):
            upload_service.import_purchase_orders(db, user.workspace_id,
                                                  upload_service.TEMPLATES["purchase_orders.csv"].encode())
        mine = db.query(PurchaseOrder).filter(PurchaseOrder.workspace_id == empty_user.workspace_id).one()
        theirs = db.query(PurchaseOrder).filter(PurchaseOrder.workspace_id == other.workspace_id).one()
        assert mine.po_number == theirs.po_number and mine.id != theirs.id


def test_grn_needs_po_in_own_workspace(db, empty_user):
    with temp_user(load_sample=False) as other:
        upload_service.import_purchase_orders(db, other.workspace_id,
                                              upload_service.TEMPLATES["purchase_orders.csv"].encode())
        with pytest.raises(UploadError, match="PO-1001 is not in your workspace"):
            upload_service.import_grns(db, empty_user.workspace_id,
                                       upload_service.TEMPLATES["goods_received_notes.csv"].encode())


def test_csv_must_be_utf8_text(db, empty_user):
    with pytest.raises(UploadError, match="UTF-8"):
        upload_service.import_purchase_orders(db, empty_user.workspace_id, b"\xff\xfe\x00b\x00a\x00d")


# ---------------------------------------------------------------------
# Contract documents
# ---------------------------------------------------------------------
def test_contract_txt_saved_with_supplier_line(db, empty_user):
    text = b"Late delivery penalty: 2 percent per week of delay.\n\nPayment within 45 days."
    upload_service.save_contract_document(db, empty_user.workspace_id, "Acme Terms.txt", text, "Acme Supplies")
    from backend.tools.contract_finder import workspace_contracts_dir

    saved = list(workspace_contracts_dir(empty_user.workspace_id).glob("*.txt"))
    assert len(saved) == 1 and saved[0].read_text(encoding="utf-8").startswith("Supplier: Acme Supplies")


@pytest.mark.parametrize("name, data, supplier, message", [
    ("terms.docx", b"PK..", "Acme", "TXT or PDF"),
    ("terms.txt", b"short", "Acme", "No readable text"),
    ("terms.txt", b"A long enough contract text about prices.", "  ", "supplier"),
    ("terms.pdf", b"not a pdf", "Acme", "real PDF"),
])
def test_bad_contract_files(db, empty_user, name, data, supplier, message):
    with pytest.raises(UploadError, match=message):
        upload_service.save_contract_document(db, empty_user.workspace_id, name, data, supplier)


# ---------------------------------------------------------------------
# Demo data vs Live workspace, reset, delete
# ---------------------------------------------------------------------
def test_demo_flag_follows_the_data(db):
    with temp_user(load_sample=True) as user:
        ws = lambda: workspace_service.get_workspace(db, user.workspace_id)  # noqa: E731
        assert workspace_service.is_demo(ws())                       # only sample data

        upload_service.save_invoice_file(db, user.workspace_id, "mine.pdf", PDF)
        db.expire_all()
        assert not workspace_service.is_demo(ws())                   # own data -> Live workspace
        folder = workspace_service.workspace_dir(user.workspace_id)
        assert any(folder.rglob("*.pdf"))

        workspace_service.load_sample_data(db, user.workspace_id)    # "Reset to sample data"
        db.expire_all()
        assert workspace_service.is_demo(ws())
        assert not any(folder.rglob("*.pdf"))                         # uploads removed
        assert db.query(Invoice).filter(Invoice.workspace_id == user.workspace_id).count() == len(user.ids)


def test_empty_workspace_is_live_not_demo(db, empty_user):
    assert not workspace_service.is_demo(workspace_service.get_workspace(db, empty_user.workspace_id))


def test_delete_workspace_removes_files_and_account(db):
    with temp_user(load_sample=False) as user:
        upload_service.save_invoice_file(db, user.workspace_id, "mine.pdf", PDF)
        folder = workspace_service.workspace_dir(user.workspace_id)
        assert folder.exists()
        workspace_service.delete_workspace(db, user.workspace_id)
        assert not folder.exists()
        assert workspace_service.get_workspace(db, user.workspace_id) is None

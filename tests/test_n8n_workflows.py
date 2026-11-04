"""
n8n workflow files (Phase 5): structural checks.

The files are plain JSON that n8n imports. These tests cannot run n8n itself, but they catch
the mistakes that break an import: invalid JSON, a connection to a node that does not exist,
duplicate names/ids, the wrong node types - and the mistake that matters most for safety:
a SECRET inside the file. Keys and tokens must come from n8n credentials, never from the JSON.
"""

import json
import re
import uuid
from pathlib import Path

import pytest

N8N_DIR = Path(__file__).resolve().parent.parent / "n8n"
FILES = ["invoice_workflow.json", "webhook_workflow.json"]


def load(name):
    return json.loads((N8N_DIR / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", FILES)
def test_valid_structure(name):
    wf = load(name)
    nodes = wf["nodes"]
    names = [n["name"] for n in nodes]
    ids = [n["id"] for n in nodes]
    assert len(set(names)) == len(names) and len(set(ids)) == len(ids)
    for n in nodes:
        uuid.UUID(n["id"])  # raises if not a UUID
        assert {"type", "typeVersion", "position", "parameters"} <= set(n)
        assert len(n["position"]) == 2
    for source, outputs in wf["connections"].items():
        assert source in names, source
        for branch in outputs["main"]:
            for link in branch:
                assert link["node"] in names, f"{source} -> {link['node']}"
    assert wf["settings"]["executionOrder"] == "v1"
    assert wf["active"] is False  # the user switches it on after setting it up


def test_invoice_workflow_flow():
    wf = load("invoice_workflow.json")
    types = {n["name"]: n["type"] for n in wf["nodes"]}
    assert types["Gmail Trigger"] == "n8n-nodes-base.gmailTrigger"
    assert types["VouchFlow ingest"] == "n8n-nodes-base.httpRequest"
    assert types["Mismatch or needs review?"] == "n8n-nodes-base.if"
    assert sum(t == "n8n-nodes-base.telegram" for t in types.values()) == 3  # problem, verified, failed

    c = wf["connections"]
    assert c["Gmail Trigger"]["main"][0][0]["node"] == "Settings"
    assert c["Split attachments"]["main"][0][0]["node"] == "VouchFlow ingest"
    # success output -> IF, error output -> failure message
    assert c["VouchFlow ingest"]["main"][0][0]["node"] == "Mismatch or needs review?"
    assert c["VouchFlow ingest"]["main"][1][0]["node"] == "Telegram: ingest failed"
    # IF: true -> problem alert, false -> short verified message
    assert c["Mismatch or needs review?"]["main"][0][0]["node"] == "Telegram: problem found"
    assert c["Mismatch or needs review?"]["main"][1][0]["node"] == "Telegram: verified"

    cond = next(n for n in wf["nodes"] if n["name"] == "Mismatch or needs review?")["parameters"]["conditions"]
    assert {x["rightValue"] for x in cond["conditions"]} == {"mismatch_detected", "needs_review"}
    assert cond["combinator"] == "or"


def test_webhook_workflow_flow():
    wf = load("webhook_workflow.json")
    types = {n["name"]: n["type"] for n in wf["nodes"]}
    assert types["Webhook"] == "n8n-nodes-base.webhook"
    assert "n8n-nodes-base.telegram" not in types.values()  # the simple one needs no Telegram
    webhook = next(n for n in wf["nodes"] if n["name"] == "Webhook")["parameters"]
    assert webhook["httpMethod"] == "POST" and webhook["responseMode"] == "responseNode"
    c = wf["connections"]["VouchFlow ingest"]["main"]
    assert c[0][0]["node"] == "Answer with the result" and c[1][0]["node"] == "Answer with the error"


@pytest.mark.parametrize("name", FILES)
def test_ingest_call_uses_a_credential_not_an_inline_key(name):
    node = next(n for n in load(name)["nodes"] if n["name"] == "VouchFlow ingest")
    p = node["parameters"]
    assert p["method"] == "POST" and p["url"].endswith("/api/invoices/ingest")
    assert p["authentication"] == "genericCredentialType" and p["genericAuthType"] == "httpHeaderAuth"
    assert "httpHeaderAuth" in node["credentials"]
    assert p["contentType"] == "multipart-form-data"
    assert p["bodyParameters"]["parameters"][0]["parameterType"] == "formBinaryData"
    assert "headerParameters" not in p  # nothing typed into the node


@pytest.mark.parametrize("name", FILES)
def test_no_secrets_in_the_file(name):
    text = (N8N_DIR / name).read_text(encoding="utf-8")
    assert not re.search(r"vf_[A-Za-z0-9_-]{20,}", text)                     # VouchFlow API key
    assert not re.search(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b", text)           # Telegram bot token
    assert not re.search(r"AIza[0-9A-Za-z_-]{30,}", text)                    # Google key
    assert not re.search(r"https?://[^\s\"']*\.(onrender|neon)\.", text)     # real hosts
    for cred in re.findall(r'"credentials":\s*\{[^{}]*\{[^{}]*\}', text):
        assert '"id"' not in cred                                            # no credential ids, names only


@pytest.mark.parametrize("name", FILES)
def test_code_nodes_are_plain_javascript_strings(name):
    for n in load(name)["nodes"]:
        if n["type"] == "n8n-nodes-base.code":
            code = n["parameters"]["jsCode"]
            assert "return " in code and "fetch(" not in code and "require(" not in code

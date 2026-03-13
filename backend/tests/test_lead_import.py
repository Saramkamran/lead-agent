"""Tests for CSV lead import: parsing, deduplication, and validation."""

import io

from httpx import AsyncClient


def make_csv(*rows: str) -> bytes:
    header = "email,first_name,last_name,company,title,website,industry,company_size"
    lines = [header] + list(rows)
    return "\n".join(lines).encode("utf-8")


async def test_import_valid_csv(client: AsyncClient, auth_headers: dict):
    csv_data = make_csv(
        "alice@example.com,Alice,Smith,Acme Corp,CEO,acme.com,SaaS,100-499",
        "bob@example.com,Bob,Jones,PropTech,VP Sales,,Real Estate,50-200",
    )
    resp = await client.post(
        "/leads/import",
        files={"file": ("leads.csv", io.BytesIO(csv_data), "text/csv")},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["imported"] == 2
    assert data["skipped"] == 0
    assert data["errors"] == []


async def test_import_skips_intra_csv_duplicates(client: AsyncClient, auth_headers: dict):
    csv_data = make_csv(
        "dup@example.com,A,B,Co,CEO,,SaaS,10-49",
        "dup@example.com,A,B,Co,CEO,,SaaS,10-49",
    )
    resp = await client.post(
        "/leads/import",
        files={"file": ("leads.csv", io.BytesIO(csv_data), "text/csv")},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["imported"] == 1
    assert data["skipped"] == 1


async def test_import_skips_existing_db_leads(client: AsyncClient, auth_headers: dict):
    csv_data = make_csv("existing@example.com,X,Y,Co,CTO,,Tech,500+")
    await client.post(
        "/leads/import",
        files={"file": ("leads.csv", io.BytesIO(csv_data), "text/csv")},
        headers=auth_headers,
    )
    resp = await client.post(
        "/leads/import",
        files={"file": ("leads.csv", io.BytesIO(csv_data), "text/csv")},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["imported"] == 0
    assert data["skipped"] == 1


async def test_import_missing_email(client: AsyncClient, auth_headers: dict):
    csv_data = make_csv(",Alice,Smith,Acme Corp,CEO,,SaaS,100-499")
    resp = await client.post(
        "/leads/import",
        files={"file": ("leads.csv", io.BytesIO(csv_data), "text/csv")},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["imported"] == 0
    assert len(data["errors"]) == 1
    assert "missing email" in data["errors"][0]


async def test_import_invalid_email_format(client: AsyncClient, auth_headers: dict):
    csv_data = make_csv("not-an-email,Alice,Smith,Acme Corp,CEO,,SaaS,100-499")
    resp = await client.post(
        "/leads/import",
        files={"file": ("leads.csv", io.BytesIO(csv_data), "text/csv")},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["imported"] == 0
    assert len(data["errors"]) == 1
    assert "invalid email" in data["errors"][0]


async def test_import_empty_csv(client: AsyncClient, auth_headers: dict):
    header = b"email,first_name,last_name,company,title,website,industry,company_size\n"
    resp = await client.post(
        "/leads/import",
        files={"file": ("leads.csv", io.BytesIO(header), "text/csv")},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["imported"] == 0
    assert data["skipped"] == 0


async def test_import_utf8_bom(client: AsyncClient, auth_headers: dict):
    """CSV files exported from Excel often carry a UTF-8 BOM marker."""
    header = "email,first_name,last_name,company,title,website,industry,company_size"
    row = "bom@example.com,BOM,Test,Corp,Manager,,Tech,10-49"
    csv_data = (header + "\n" + row).encode("utf-8-sig")  # utf-8-sig adds the BOM automatically
    resp = await client.post(
        "/leads/import",
        files={"file": ("leads.csv", io.BytesIO(csv_data), "text/csv")},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["imported"] == 1


async def test_import_mixed_valid_and_invalid(client: AsyncClient, auth_headers: dict):
    csv_data = make_csv(
        "good@example.com,Good,Lead,Corp,CEO,,SaaS,100-499",
        "bad-email,Bad,Lead,Corp,CEO,,SaaS,100-499",
        ",Missing,Email,Corp,CEO,,SaaS,100-499",
    )
    resp = await client.post(
        "/leads/import",
        files={"file": ("leads.csv", io.BytesIO(csv_data), "text/csv")},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["imported"] == 1
    assert len(data["errors"]) == 2


async def test_import_requires_auth(client: AsyncClient):
    csv_data = make_csv("x@example.com,,,,,,,")
    resp = await client.post(
        "/leads/import",
        files={"file": ("leads.csv", io.BytesIO(csv_data), "text/csv")},
    )
    assert resp.status_code in (401, 403)

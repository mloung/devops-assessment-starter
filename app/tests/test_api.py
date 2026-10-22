from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_create_and_list_order():
    created = client.post("/orders", json={"amount": 42.5, "status": "pending", "currency": "USD"})
    assert created.status_code == 200
    assert created.json()["currency"] == "USD"
    order_id = created.json()["id"]

    orders = client.get("/orders")
    assert orders.status_code == 200
    assert any(o["id"] == order_id and o["amount"] == 42.5 and o["currency"] == "USD" for o in orders.json())


def test_create_order_without_currency_defaults_to_zar():
    # Old-shaped request payload (no currency field) must still work --
    # this is the backward-compatibility guarantee the expand phase provides.
    created = client.post("/orders", json={"amount": 10.0, "status": "pending"})
    assert created.status_code == 200
    assert created.json()["currency"] == "ZAR"


def test_response_includes_request_id_header():
    resp = client.get("/health")
    assert "x-request-id" in resp.headers


def test_metrics_endpoint_exposes_prometheus_data():
    client.get("/health")
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert b"http_requests_total" in resp.content

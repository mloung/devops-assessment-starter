from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_create_and_list_order():
    created = client.post("/orders", json={"amount": 42.5, "status": "pending"})
    assert created.status_code == 200
    order_id = created.json()["id"]

    orders = client.get("/orders")
    assert orders.status_code == 200
    assert any(o["id"] == order_id and o["amount"] == 42.5 for o in orders.json())

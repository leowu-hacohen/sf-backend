BASE = "/api/v1/contacts"


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "sqlite"


def test_create_contact(client, payload):
    response = client.post(BASE, json=payload)
    assert response.status_code == 201
    body = response.json()
    assert body["id"] > 0
    assert body["email"] == "ada@example.com"
    assert body["full_name"] == "Ada Lovelace"
    assert body["created_at"] and body["updated_at"]


def test_create_requires_valid_email(client, payload):
    response = client.post(BASE, json={**payload, "email": "not-an-email"})
    assert response.status_code == 422


def test_create_requires_names(client, payload):
    response = client.post(BASE, json={**payload, "first_name": ""})
    assert response.status_code == 422


def test_duplicate_email_conflicts(client, payload):
    assert client.post(BASE, json=payload).status_code == 201
    response = client.post(BASE, json={**payload, "email": "ADA@example.com"})
    assert response.status_code == 409


def test_get_contact(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.get(f"{BASE}/{contact_id}")
    assert response.status_code == 200
    assert response.json()["id"] == contact_id


def test_get_missing_contact_returns_404(client):
    assert client.get(f"{BASE}/9999").status_code == 404


def test_list_pagination_and_total(client, payload):
    for index in range(5):
        client.post(BASE, json={**payload, "email": f"user{index}@example.com"})

    response = client.get(BASE, params={"limit": 2, "offset": 2})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["limit"] == 2 and body["offset"] == 2


def test_list_search(client, payload):
    client.post(BASE, json=payload)
    client.post(
        BASE,
        json={**payload, "first_name": "Grace", "last_name": "Hopper", "email": "grace@example.com", "company": "US Navy"},
    )

    hits = client.get(BASE, params={"search": "hopper"}).json()
    assert hits["total"] == 1
    assert hits["items"][0]["last_name"] == "Hopper"

    by_company = client.get(BASE, params={"search": "navy"}).json()
    assert by_company["total"] == 1

    misses = client.get(BASE, params={"search": "nobody"}).json()
    assert misses["total"] == 0


def test_list_sorting(client, payload):
    client.post(BASE, json={**payload, "last_name": "Zhang", "email": "z@example.com"})
    client.post(BASE, json={**payload, "last_name": "Adams", "email": "a@example.com"})

    names = [
        item["last_name"]
        for item in client.get(BASE, params={"sort_by": "last_name", "order": "asc"}).json()["items"]
    ]
    assert names == ["Adams", "Zhang"]


def test_list_rejects_bad_sort_field(client):
    assert client.get(BASE, params={"sort_by": "; DROP TABLE contacts"}).status_code == 422


def test_patch_updates_only_sent_fields(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.patch(f"{BASE}/{contact_id}", json={"phone": "+1-000-000-0000"})
    assert response.status_code == 200
    body = response.json()
    assert body["phone"] == "+1-000-000-0000"
    assert body["first_name"] == "Ada"
    assert body["company"] == "Analytical Engines"


def test_patch_duplicate_email_conflicts(client, payload):
    first = client.post(BASE, json=payload).json()["id"]
    client.post(BASE, json={**payload, "email": "grace@example.com"})
    response = client.patch(f"{BASE}/{first}", json={"email": "grace@example.com"})
    assert response.status_code == 409


def test_patch_same_email_is_allowed(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.patch(f"{BASE}/{contact_id}", json={"email": payload["email"]})
    assert response.status_code == 200


def test_put_replaces_contact(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.put(
        f"{BASE}/{contact_id}",
        json={"first_name": "Grace", "last_name": "Hopper", "email": "grace@example.com"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["full_name"] == "Grace Hopper"
    assert body["company"] is None  # omitted fields are cleared by PUT


def test_put_missing_contact_returns_404(client):
    response = client.put(
        f"{BASE}/9999",
        json={"first_name": "A", "last_name": "B", "email": "ab@example.com"},
    )
    assert response.status_code == 404


def test_delete_contact(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    assert client.delete(f"{BASE}/{contact_id}").status_code == 204
    assert client.get(f"{BASE}/{contact_id}").status_code == 404
    assert client.delete(f"{BASE}/{contact_id}").status_code == 404


def test_root_lists_entrypoints(client):
    body = client.get("/").json()
    assert body["contacts"] == BASE


def test_create_contact_with_photo_url(client, payload):
    photo = "https://i.pravatar.cc/150?img=47"
    response = client.post(BASE, json={**payload, "photo_url": photo})
    assert response.status_code == 201
    assert response.json()["photo_url"] == photo


def test_photo_url_defaults_to_none(client, payload):
    response = client.post(BASE, json=payload)
    assert response.status_code == 201
    assert response.json()["photo_url"] is None


def test_photo_url_rejects_non_http_schemes_and_hostless_urls(client, payload):
    for bad in (
        "javascript:alert(1)",
        "ftp://example.com/a.png",
        "not a url",
        "https://",
        "http:///path",
        "https://@/x",
        "https://:443/x",
    ):
        response = client.post(BASE, json={**payload, "photo_url": bad})
        assert response.status_code == 422


def test_photo_url_scheme_is_case_insensitive(client, payload):
    response = client.post(BASE, json={**payload, "photo_url": "HTTPS://example.com/me.png"})
    assert response.status_code == 201


def test_patch_can_set_and_clear_photo_url(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    photo = "https://i.pravatar.cc/150?img=5"
    assert client.patch(f"{BASE}/{contact_id}", json={"photo_url": photo}).json()["photo_url"] == photo
    assert client.patch(f"{BASE}/{contact_id}", json={"photo_url": None}).json()["photo_url"] is None


def test_init_db_adds_photo_url_to_legacy_table(client):
    from sqlalchemy import inspect, text

    from app.database import engine, init_db

    # Simulate a database created before photo_url existed.
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE contacts DROP COLUMN photo_url"))

    init_db()

    columns = {column["name"] for column in inspect(engine).get_columns("contacts")}
    assert "photo_url" in columns


def _address_count() -> int:
    from sqlalchemy import func, select

    from app.database import SessionLocal
    from app.models import Address

    with SessionLocal() as db:
        return db.execute(select(func.count()).select_from(Address)).scalar_one()


def test_create_contact_with_addresses(client, payload):
    body = client.post(BASE, json=payload).json()
    assert [(a["type"], a["city"]) for a in body["addresses"]] == [
        ("home", "London"),
        ("work", "San Francisco"),
    ]
    assert all(a["id"] > 0 for a in body["addresses"])


def test_addresses_default_to_empty_list(client, payload):
    body = client.post(BASE, json={**payload, "addresses": []}).json()
    assert body["addresses"] == []


def test_address_type_is_validated(client, payload):
    bad = {**payload, "addresses": [{"type": "vacation", "city": "Maui"}]}
    assert client.post(BASE, json=bad).status_code == 422


def test_patch_without_addresses_keeps_them(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]

    body = client.patch(f"{BASE}/{contact_id}", json={"company": "Acme"}).json()

    assert body["company"] == "Acme"
    assert len(body["addresses"]) == 2


def test_patch_with_addresses_replaces_the_list(client, payload):
    created = client.post(BASE, json=payload).json()
    old_ids = {a["id"] for a in created["addresses"]}

    body = client.patch(
        f"{BASE}/{created['id']}",
        json={"addresses": [{"type": "other", "city": "Cambridge"}]},
    ).json()

    assert [(a["type"], a["city"]) for a in body["addresses"]] == [("other", "Cambridge")]
    assert old_ids.isdisjoint(a["id"] for a in body["addresses"])
    assert _address_count() == 1  # replaced rows are deleted, not orphaned


def test_patch_null_addresses_clears_the_list(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    body = client.patch(f"{BASE}/{contact_id}", json={"addresses": None}).json()
    assert body["addresses"] == []
    assert _address_count() == 0


def test_put_replaces_addresses(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]

    replacement = {**payload, "addresses": [{"type": "work", "city": "Zurich"}]}
    body = client.put(f"{BASE}/{contact_id}", json=replacement).json()

    assert [(a["type"], a["city"]) for a in body["addresses"]] == [("work", "Zurich")]
    assert _address_count() == 1


def test_deleting_contact_deletes_addresses(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    assert _address_count() == 2

    assert client.delete(f"{BASE}/{contact_id}").status_code == 204
    assert _address_count() == 0


def test_init_db_migrates_legacy_flat_addresses(client):
    from sqlalchemy import text

    from app.database import engine, init_db

    with engine.begin() as connection:
        for ddl in (
            "ALTER TABLE contacts ADD COLUMN address VARCHAR(300)",
            "ALTER TABLE contacts ADD COLUMN city VARCHAR(120)",
            "ALTER TABLE contacts ADD COLUMN state VARCHAR(120)",
            "ALTER TABLE contacts ADD COLUMN postal_code VARCHAR(20)",
            "ALTER TABLE contacts ADD COLUMN country VARCHAR(120)",
        ):
            connection.execute(text(ddl))
        connection.execute(
            text(
                "INSERT INTO contacts (first_name, last_name, email, city, country, created_at, updated_at) "
                "VALUES ('Old', 'Timer', 'old@example.com', 'Boston', 'USA', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )

    init_db()

    contact = client.get(BASE).json()["items"][0]
    assert [(a["type"], a["city"], a["country"]) for a in contact["addresses"]] == [
        ("home", "Boston", "USA")
    ]

    # Idempotent: another startup must not duplicate the migrated row.
    init_db()
    assert len(client.get(f"{BASE}/{contact['id']}").json()["addresses"]) == 1

    # Move, not copy: clearing the list must survive the next startup.
    client.patch(f"{BASE}/{contact['id']}", json={"addresses": []})
    init_db()
    assert client.get(f"{BASE}/{contact['id']}").json()["addresses"] == []


def test_legacy_migration_covers_contacts_missed_earlier(client, payload):
    from sqlalchemy import text

    from app.database import engine, init_db

    already_normalized = client.post(BASE, json=payload).json()

    with engine.begin() as connection:
        for ddl in (
            "ALTER TABLE contacts ADD COLUMN address VARCHAR(300)",
            "ALTER TABLE contacts ADD COLUMN city VARCHAR(120)",
            "ALTER TABLE contacts ADD COLUMN state VARCHAR(120)",
            "ALTER TABLE contacts ADD COLUMN postal_code VARCHAR(20)",
            "ALTER TABLE contacts ADD COLUMN country VARCHAR(120)",
        ):
            connection.execute(text(ddl))
        connection.execute(
            text(
                "INSERT INTO contacts (first_name, last_name, email, city, created_at, updated_at) "
                "VALUES ('Old', 'Timer', 'old@example.com', 'Boston', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )

    init_db()

    items = client.get(BASE).json()["items"]
    by_email = {c["email"]: c["addresses"] for c in items}
    # The legacy-only contact was migrated even though other rows already existed...
    assert [a["city"] for a in by_email["old@example.com"]] == ["Boston"]
    # ...and the already-normalized contact was left exactly as it was.
    assert by_email[already_normalized["email"]] == already_normalized["addresses"]

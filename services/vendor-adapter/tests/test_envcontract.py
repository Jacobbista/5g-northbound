from app.envcontract import discover_mapping_coverage, mapping_coverage, vendor_env
from app.schema import Schema


def test_no_schema_means_no_vendor_variables():
    # An unbound instance announces nothing. The caller reports configured:false
    # rather than presenting an example as its configuration.
    assert vendor_env(None) == []


def test_names_come_from_the_schema_not_from_this_image(wittra_schema):
    names = [e["name"] for e in vendor_env(wittra_schema)]
    assert names == [
        "WITTRA_API_KEY",
        "WITTRA_BASE_URL",
        "WITTRA_ORG_ID",
        "WITTRA_PROJECT_ID",
    ]


def test_a_name_used_at_several_sites_appears_once(wittra_schema):
    # WITTRA_ORG_ID is a path var, the basic-auth username, a discover path var
    # and a diagnostics path var, and is a secret at none of them.
    org = [e for e in vendor_env(wittra_schema) if e["name"] == "WITTRA_ORG_ID"]
    assert len(org) == 1
    assert org[0]["sensitive"] is False
    assert org[0]["declared_at"] == [
        "pathVars.org_id",
        "auth.username",
        "discover.pathVars.org_id",
        "diagnostics.onDemand[0].pathVars.org_id",
    ]


def test_the_auth_credential_is_the_only_secret(wittra_schema):
    secrets = [e["name"] for e in vendor_env(wittra_schema) if e["sensitive"]]
    assert secrets == ["WITTRA_API_KEY"]


def test_entries_carry_no_values(wittra_schema):
    for entry in vendor_env(wittra_schema):
        assert "default" not in entry
        assert "example" not in entry


def test_the_base_url_variable_is_typed_as_a_url(wittra_schema):
    entry = [e for e in vendor_env(wittra_schema) if e["name"] == "WITTRA_BASE_URL"]
    assert entry and entry[0]["type"] == "url"
    assert entry[0]["declared_at"] == ["baseUrl"]


def test_an_open_vendor_asks_for_no_credentials(wittra_schema_dict):
    doc = dict(wittra_schema_dict)
    doc["auth"] = {"scheme": "none"}
    doc["pathVars"] = {}
    doc["path"] = "/devices/{device_id}"
    doc.pop("discover", None)
    doc.pop("diagnostics", None)
    names = [e["name"] for e in vendor_env(Schema.model_validate(doc))]
    assert names == ["WITTRA_BASE_URL"]


def test_unmapped_reports_supported_fields_the_document_does_not_map(wittra_schema_dict):
    doc = dict(wittra_schema_dict)
    doc["mapping"] = {k: v for k, v in doc["mapping"].items() if k != "lastSeen"}
    cov = mapping_coverage(Schema.model_validate(doc))
    assert "lastSeen" in cov["supported"]
    assert "lastSeen" in cov["unmapped"]
    assert "lastSeen" not in cov["mapped"]
    assert "latitude" in cov["mapped"]


def test_the_reference_document_maps_every_supported_field_but_accuracy(wittra_schema):
    # The committed example is what an integrator copies, so it exercises the
    # whole mapping surface - except `accuracy`, deliberately: this real
    # account's "accuracy" field is a [0,1] confidence score, not a metres
    # radius (mapped to `confidence` instead), so the example demonstrates
    # the one legitimate reason to leave accuracy unmapped rather than
    # fabricate one.
    assert mapping_coverage(wittra_schema)["unmapped"] == ["accuracy"]
    assert discover_mapping_coverage(wittra_schema)["unmapped"] == []


def test_discover_coverage_is_absent_without_a_discover_block(wittra_schema_dict):
    doc = dict(wittra_schema_dict)
    doc.pop("discover", None)
    assert discover_mapping_coverage(Schema.model_validate(doc)) is None

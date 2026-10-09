import base64

from a2a.types import AgentCard
from google.protobuf.json_format import ParseDict

from a2a_workbench.core.auth.apply import build_auth_plan
from a2a_workbench.core.auth.requirements import choose_requirement, requirement_alternatives


def card(schemes, requirements, skills=None):
    return ParseDict(
        {
            "name": "x",
            "securitySchemes": schemes,
            "securityRequirements": [
                {"schemes": {k: {"list": v} for k, v in r.items()}} for r in requirements
            ],
            "skills": skills or [],
        },
        AgentCard(),
    )


SCHEMES = {
    "hdr": {"apiKeySecurityScheme": {"location": "header", "name": "X-API-Key"}},
    "qry": {"apiKeySecurityScheme": {"location": "query", "name": "api_key"}},
    "ck1": {"apiKeySecurityScheme": {"location": "cookie", "name": "session"}},
    "ck2": {"apiKeySecurityScheme": {"location": "cookie", "name": "tenant"}},
    "basic": {"httpAuthSecurityScheme": {"scheme": "Basic"}},
    "bearer": {"httpAuthSecurityScheme": {"scheme": "bearer", "bearerFormat": "JWT"}},
    "oauth": {
        "oauth2SecurityScheme": {
            "flows": {"clientCredentials": {"tokenUrl": "http://idp/token", "scopes": {}}}
        }
    },
    "oidc": {
        "openIdConnectSecurityScheme": {
            "openIdConnectUrl": "http://idp/.well-known/openid-configuration"
        }
    },
    "mtls": {"mtlsSecurityScheme": {}},
}

CREDS = {
    "hdr": {"kind": "api_key", "value": "K1"},
    "qry": {"kind": "api_key", "value": "Q1"},
    "ck1": {"kind": "api_key", "value": "S1"},
    "ck2": {"kind": "api_key", "value": "T1"},
    "basic": {"kind": "http_basic", "username": "u", "password": "p"},
    "bearer": {"kind": "http_bearer", "token": "B1"},
    "oauth": {"kind": "oauth2", "access_token": "O1"},
    "oidc": {"kind": "oauth2", "access_token": "I1"},
    "mtls": {"kind": "mtls", "cert_pem": "CERT", "key_pem": "KEY", "ca_pem": "CA"},
}


def plan(requirements, creds=CREDS, skills=None, skill_id=None):
    return build_auth_plan(card(SCHEMES, requirements, skills), creds, skill_id=skill_id)


def test_each_scheme_maps_to_the_right_place():
    assert plan([{"hdr": []}]).headers == {"X-API-Key": "K1"}
    assert plan([{"qry": []}]).query == {"api_key": "Q1"}
    assert plan([{"basic": []}]).headers == {
        "Authorization": "Basic " + base64.b64encode(b"u:p").decode()
    }
    assert plan([{"bearer": []}]).headers == {"Authorization": "Bearer B1"}
    assert plan([{"oauth": ["read"]}]).headers == {"Authorization": "Bearer O1"}
    assert plan([{"oidc": []}]).headers == {"Authorization": "Bearer I1"}
    tls = plan([{"mtls": []}]).tls
    assert (tls.cert_pem, tls.key_pem, tls.ca_pem) == ("CERT", "KEY", "CA")


def test_and_requirement_applies_every_scheme():
    p = plan([{"hdr": [], "oauth": ["read"], "ck1": [], "ck2": []}])
    assert p.headers["X-API-Key"] == "K1" and p.headers["Authorization"] == "Bearer O1"
    assert p.headers["Cookie"] == "session=S1; tenant=T1"
    assert sorted(p.scheme_names) == ["ck1", "ck2", "hdr", "oauth"] and p.missing == []


def test_or_falls_back_to_first_satisfiable_alternative():
    creds = {"bearer": CREDS["bearer"]}
    p = plan([{"oauth": []}, {"bearer": []}], creds=creds)
    assert p.headers == {"Authorization": "Bearer B1"} and p.scheme_names == ["bearer"]


def test_missing_credentials_are_reported():
    p = plan([{"oauth": [], "hdr": []}], creds={"hdr": CREDS["hdr"]})
    assert p.headers == {} and p.missing == ["oauth"]


def test_no_requirements_means_no_auth():
    p = plan([])
    assert (p.headers, p.query, p.tls, p.missing) == ({}, {}, None, [])


def test_skill_requirements_override_the_card():
    skills = [
        {
            "id": "hold",
            "name": "Hold",
            "securityRequirements": [{"schemes": {"oauth": {"list": ["booking.write"]}}}],
        }
    ]
    p = plan([{"hdr": []}], skills=skills, skill_id="hold")
    assert p.headers == {"Authorization": "Bearer O1"}


def test_wrong_credential_kind_counts_as_missing():
    p = plan([{"basic": []}], creds={"basic": {"kind": "api_key", "value": "nope"}})
    assert p.missing == ["basic"]


def test_requirement_helpers():
    c = card(SCHEMES, [{"hdr": []}, {"oauth": ["a", "b"]}])
    alts = requirement_alternatives(c)
    assert alts == [{"hdr": []}, {"oauth": ["a", "b"]}]
    assert choose_requirement(alts, {"oauth"}) == {"oauth": ["a", "b"]}
    assert choose_requirement(alts, set()) is None
    assert choose_requirement([], set()) == {}

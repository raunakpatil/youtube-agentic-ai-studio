"""The local server must only obey its own page — not other websites in the same browser."""
import os
import subprocess

import pytest

import gui

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SELF = "http://localhost"          # Flask's test client sends Host: localhost
SEO = {"title": "Why time slows down", "description": "", "tags": []}


@pytest.fixture
def client():
    gui.app.config["TESTING"] = True
    return gui.app.test_client()


def test_own_page_can_write(client):
    r = client.post("/api/seo", json=SEO, headers={"Origin": SELF})
    assert r.status_code == 200 and "score" in r.get_json()


def test_other_website_cannot_write(client):
    r = client.post("/api/seo", json=SEO, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_sandboxed_null_origin_is_blocked(client):
    assert client.post("/api/seo", json=SEO, headers={"Origin": "null"}).status_code == 403


def test_other_port_on_localhost_is_blocked(client):
    # a different local dev server is a different site
    r = client.post("/api/seo", json=SEO, headers={"Origin": "http://localhost:3000"})
    assert r.status_code == 403


def test_cross_site_referer_is_blocked_when_origin_missing(client):
    r = client.post("/api/seo", json=SEO, headers={"Referer": "https://evil.example/page"})
    assert r.status_code == 403


def test_text_plain_post_is_refused(client):
    # the classic CSRF shape: a "simple" request that skips the CORS preflight
    r = client.post("/api/seo", data='{"title": "x"}', content_type="text/plain")
    assert r.status_code == 415


def test_command_line_tools_still_work(client):
    # curl / scripts send no Origin and can't be driven by a webpage
    assert client.post("/api/seo", json=SEO).status_code == 200


def test_cross_site_delete_is_blocked(client):
    r = client.delete("/api/library/does-not-exist", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    r = client.delete("/api/library/does-not-exist", headers={"Origin": SELF})
    assert r.status_code == 200 and r.get_json()["ok"] is False   # allowed, just not found


@pytest.mark.parametrize("host", ["evil.example", "evil.example:7070", "192.168.1.20:7070"])
def test_dns_rebinding_is_blocked(client, host):
    assert client.get("/api/banned-topics", headers={"Host": host}).status_code == 403


@pytest.mark.parametrize("host", ["localhost:7070", "127.0.0.1:7070", "[::1]:7070"])
def test_local_hosts_are_allowed(client, host):
    assert client.get("/api/banned-topics", headers={"Host": host}).status_code == 200


@pytest.mark.parametrize("netloc, name", [
    ("localhost:7070", "localhost"), ("127.0.0.1", "127.0.0.1"),
    ("[::1]:7070", "[::1]"), ("LOCALHOST:80", "localhost"),
])
def test_hostname_parsing(netloc, name):
    assert gui._hostname(netloc) == name


def test_real_oauth_secret_is_never_committed():
    ignored = subprocess.run(["git", "check-ignore", "-q", "client_secret.json"], cwd=ROOT)
    assert ignored.returncode == 0, "client_secret.json must be git-ignored"
    example = subprocess.run(["git", "check-ignore", "-q", "client_secret.example.json"], cwd=ROOT)
    assert example.returncode == 1, "the example file should stay tracked"

"""La pasarela anti-bots de Cornell se reconoce y se nombra, no se rodea.

Desde el 2026-08-30 search.macaulaylibrary.org, y desde el 2026-09-22
ebird.org, contestan a cualquier User-Agent con un 200 que lleva el reto
de Anubis en vez de contenido. El reto de ebird.org trae además la
descripción genérica de eBird, así que hasta ahora se registraba como
"página genérica" y el de Macaulay como un JSON malformado, una vez por
especie y por llamada. Ahora cada host se avisa una sola vez por run,
diciendo lo que es, y las peticiones se siguen haciendo para que las
estrategias vuelvan solas el día que Cornell levante la pasarela.
"""

import logging

from scripts import content_scraper, image_fetcher

_ANUBIS = (
    '<!doctype html><html lang="en"><head>'
    "<title>Making sure you&#39;re not a bot!</title>"
    '<meta property="og:description" content="eBird transforms your bird '
    'sightings into science and conservation.">'
    '<script id="anubis_version" type="application/json">"1.0"</script>'
    "</head><body>Loading...</body></html>"
)


class _Resp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass

    def json(self):
        raise ValueError("Expecting value: line 1 column 1 (char 0)")


class _Session:
    def __init__(self, text=_ANUBIS):
        self.text = text
        self.urls = []

    def get(self, url, params=None, timeout=None, **kwargs):
        self.urls.append(url)
        return _Resp(self.text)


def _fresh():
    image_fetcher._bot_gates_reported.clear()


def test_the_challenge_is_recognised_and_plain_html_is_not():
    assert image_fetcher.is_bot_gate(_ANUBIS)
    assert image_fetcher.is_bot_gate("<html><title>Anubis</title></html>")
    assert not image_fetcher.is_bot_gate("<html><title>eBird</title></html>")
    assert not image_fetcher.is_bot_gate("")


def test_macaulay_names_the_gate_once_per_run(caplog):
    _fresh()
    session = _Session()
    with caplog.at_level(logging.DEBUG, logger="scripts.image_fetcher"):
        assert image_fetcher._try_macaulay_api("eucdov", session) is None
        assert image_fetcher._try_macaulay_api("gobfly2", session) is None
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "search.macaulaylibrary.org" in warnings[0].getMessage()
    assert "bot gate" in warnings[0].getMessage()
    assert "Expecting value" not in caplog.text
    # The second species is still asked: the strategy heals itself the
    # day the gate is lifted.
    assert len(session.urls) == 2


def test_ebird_hero_names_the_gate_instead_of_a_generic_page(caplog):
    _fresh()
    with caplog.at_level(logging.DEBUG, logger="scripts.image_fetcher"):
        assert image_fetcher._try_ebird_og_image("eucdov", _Session()) is None
    assert "generic page" not in caplog.text
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert [r for r in warnings if "ebird.org" in r.getMessage()]


def test_each_host_is_reported_on_its_own(caplog):
    _fresh()
    session = _Session()
    with caplog.at_level(logging.WARNING, logger="scripts.image_fetcher"):
        image_fetcher._try_ebird_og_image("eucdov", session)
        image_fetcher._try_macaulay_api("eucdov", session)
        image_fetcher._try_ebird_og_image("gobfly2", session)
        image_fetcher._try_macaulay_api("gobfly2", session)
    hosts = sorted(r.getMessage().split(" ")[0] for r in caplog.records)
    assert hosts == ["ebird.org", "search.macaulaylibrary.org"]


def test_the_scraper_takes_no_text_from_the_challenge(caplog):
    with caplog.at_level(logging.INFO, logger="scripts.content_scraper"):
        assert content_scraper._fetch_ebird_og_description("eucdov", _Session()) == ""
    assert "generic page" not in caplog.text
    assert "bot gate" in caplog.text


def test_a_real_json_error_is_still_reported_as_such(caplog):
    _fresh()
    session = _Session(text="<html><title>502 Bad Gateway</title></html>")
    with caplog.at_level(logging.WARNING, logger="scripts.image_fetcher"):
        assert image_fetcher._try_macaulay_api("eucdov", session) is None
    assert "ML search API unavailable for eucdov" in caplog.text

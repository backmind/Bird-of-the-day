"""El héroe de eBird no siempre trae foto, y publicar eso rompe la lámina.

eBird emite la etiqueta ``og:image`` incluso para especies de las que no
tiene héroe curado, con el id del asset vacío. La URL resultante,
``.../api/v2/asset//900``, es un 404 que el lector ve como un hueco. Pasó
en producción dos veces, el 2026-06-21 y el 2026-08-30, antes de que
existiera esta guarda.
"""

from scripts import image_fetcher
from scripts.image_fetcher import CDN_BASE, ImageResult


class _PageSession:
    """Sesión falsa que devuelve una página de especie de eBird."""

    def __init__(self, html):
        self.html = html
        self.urls = []

    def get(self, url, timeout=None, **kwargs):
        self.urls.append(url)
        html = self.html

        class _Resp:
            text = html

            def raise_for_status(self):
                pass

        return _Resp()


def _page(og_image):
    return f'<html><head><meta property="og:image" content="{og_image}"/>' \
           '<meta property="og:image:alt" content="Ave - Fotografo"/>' \
           "</head><body></body></html>"


def test_hero_without_an_asset_id_is_declined():
    session = _PageSession(_page(f"{CDN_BASE}//900"))
    assert image_fetcher._try_ebird_og_image("vilbrf1", session) is None


def test_hero_with_an_asset_id_is_used():
    session = _PageSession(_page(f"{CDN_BASE}/255114031/1200"))
    result = image_fetcher._try_ebird_og_image("cometi1", session)
    assert result.asset_id == "255114031"
    assert result.photographer == "Fotografo"


def test_an_idless_hero_falls_through_to_macaulay(monkeypatch):
    """La consecuencia que importa: se publica la foto de la otra vía."""
    session = _PageSession(_page(f"{CDN_BASE}//900"))
    rated = ImageResult(
        url=f"{CDN_BASE}/777/1200", asset_id="777", photographer="R",
        attribution="R / Macaulay Library", search_url="s",
    )
    monkeypatch.setattr(
        image_fetcher, "_try_macaulay_api", lambda *a, **k: rated
    )
    result = image_fetcher.fetch_image("vilbrf1", session)
    assert result.asset_id == "777"


def test_no_photo_at_all_beats_a_broken_one(monkeypatch):
    """Sin ninguna vía, la entrada sale sin foto y con enlace de búsqueda,
    que es un hueco honesto en vez de una imagen rota."""
    session = _PageSession(_page(f"{CDN_BASE}//900"))
    monkeypatch.setattr(image_fetcher, "_try_macaulay_api", lambda *a, **k: None)
    result = image_fetcher.fetch_image("vilbrf1", session)
    assert result.url is None
    assert result.search_url

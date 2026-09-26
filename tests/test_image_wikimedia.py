"""Cuando Cornell no contesta, la foto sale de Wikimedia Commons.

Desde el 2026-09-22 la página de especie de eBird devuelve al runner la
portada genérica de eBird casi siempre, y la API de Macaulay lleva detrás
de una pasarela anti-bots desde el 2026-08-30. Tres de cuatro entradas
seguidas salieron sin foto tras agotar 50 re-tiradas. Commons no depende
de Cornell, y su imagen principal de cada artículo viene con autor y
licencia.

Esa imagen principal resultó ser, para gobfly2, una piel de museo con la
autoridad taxonómica como autor. Ahora va antes iNaturalist, cuya foto
por defecto es de un ave viva, y de Commons solo se aceptan fotografías
JPEG con licencia que no sean especímenes, huevos, láminas, mapas ni
sellos.
"""

from bs4 import BeautifulSoup

from scripts import content_scraper, image_fetcher
from scripts.image_fetcher import CDN_BASE


class _Resp:
    def __init__(self, payload=None, text=""):
        self._payload = payload
        self.text = text

    def raise_for_status(self):
        pass

    def json(self):
        if self._payload is None:
            raise ValueError("no JSON")
        return self._payload


_LIVE_BIRD = "Microeca_hemixantha.jpg"
_SKIN = (
    "Naturalis_Biodiversity_Center_-_RMNH.AVES.84382_1_-_Microeca_hemixantha"
    "_Sclater,_1883_-_Eopsaltriidae_-_bird_skin_specimen.jpeg"
)


def _file(artist='<a href="//x">Ana <b>Pérez</b></a>', licence="CC BY-SA 4.0",
          mime="image/jpeg", thumb="https://upload.wikimedia.org/900px.jpg",
          **extra):
    meta = {"Artist": {"value": artist}}
    if licence:
        meta["LicenseShortName"] = {"value": licence}
    for key, value in extra.items():
        meta[key] = {"value": value}
    return {"url": "https://upload.wikimedia.org/full.jpg", "thumburl": thumb,
            "mime": mime, "extmetadata": meta}


class _WikiSession:
    """Contesta la API de MediaWiki y, si se le da, la de iNaturalist; todo
    lo demás, con la portada genérica de eBird o con HTML en vez de JSON,
    como hace hoy Cornell.

    ``lead`` es la imagen principal del artículo, ``others`` el resto de
    ficheros que usa y ``files`` los metadatos de cada fichero."""

    def __init__(self, lead=_LIVE_BIRD, others=(), files=None, inat=None,
                 inat_photos=()):
        self.lead = lead
        self.others = list(others)
        self.files = files if files is not None else {_LIVE_BIRD: _file()}
        self.inat = inat
        self.inat_photos = list(inat_photos)
        self.calls = []

    def get(self, url, params=None, timeout=None, **kwargs):
        params = dict(params or {})
        self.calls.append((url, params))
        if "wikipedia.org/w/api.php" in url:
            if params.get("prop") == "pageimages|images":
                page = {"title": "Microeca hemixantha", "images": [
                    {"ns": 6, "title": "File:" + n.replace("_", " ")}
                    for n in self.others
                ]}
                if self.lead:
                    page["pageimage"] = self.lead
                return _Resp({"query": {"pages": [page]}})
            pages = []
            for title in params["titles"].split("|"):
                name = title.split(":", 1)[1]
                info = next((v for k, v in self.files.items()
                             if k.replace("_", " ") == name), None)
                page = {"title": title}
                if info:
                    page["imageinfo"] = [info]
                pages.append(page)
            return _Resp({"query": {"pages": pages}})
        if "api.inaturalist.org/v1/taxa/" in url:
            return _Resp({"results": [{"id": 1, "taxon_photos": [
                {"photo": p} for p in self.inat_photos
            ]}]})
        if "api.inaturalist.org" in url and self.inat is not None:
            return _Resp({"results": self.inat})
        if "ebird.org/species/" in url:
            return _Resp(text=_GENERIC_EBIRD)
        return _Resp(text="<html>challenge</html>")


def _taxon(name="Microeca hemixantha", licence="cc-by-nc",
           attribution="(c) Ana Pérez, some rights reserved (CC BY-NC)",
           url="https://inaturalist-open-data.s3.amazonaws.com/photos/42/medium.jpg"):
    return {"id": 1, "name": name, "rank": "species", "is_active": True, "default_photo": {
        "license_code": licence, "attribution": attribution, "medium_url": url,
    }}


_GENERIC_EBIRD = (
    '<html><head>'
    '<meta property="og:description" content="eBird transforms your bird '
    'sightings into science and conservation. Plan trips, find birds."/>'
    f'<meta property="og:image" content="{CDN_BASE}/123456/1200"/>'
    '<meta property="og:url" content="https://ebird.org/home"/>'
    '</head><body></body></html>'
)


def test_commons_answers_when_cornell_does_not():
    session = _WikiSession()
    result = image_fetcher.fetch_image(
        "gobfly2", session, scientific_name="Microeca hemixantha"
    )
    assert result.url == "https://upload.wikimedia.org/900px.jpg"
    assert result.photographer == "Ana Pérez"
    assert result.attribution == "Ana Pérez / Wikimedia Commons (CC BY-SA 4.0)"
    assert "gobfly2" in result.search_url


def test_the_generic_ebird_hero_is_not_this_bird():
    """La portada genérica trae un og:image con id. Usarlo publicaría la
    foto de otra ave: tiene que caer a la siguiente vía."""
    session = _WikiSession()
    assert image_fetcher._try_ebird_og_image("gobfly2", session) is None


def test_a_file_without_a_licence_is_not_published():
    session = _WikiSession(files={_LIVE_BIRD: _file(licence="")})
    result = image_fetcher.fetch_image(
        "gobfly2", session, scientific_name="Microeca hemixantha"
    )
    assert result.url is None


def test_an_article_without_a_lead_image_leaves_the_gap():
    session = _WikiSession(lead=None)
    result = image_fetcher.fetch_image(
        "gobfly2", session, scientific_name="Microeca hemixantha"
    )
    assert result.url is None
    assert result.search_url


def test_no_scientific_name_skips_commons():
    session = _WikiSession()
    result = image_fetcher.fetch_image("gobfly2", session)
    assert result.url is None
    assert not any("wikipedia" in url for url, _ in session.calls)


def test_the_generic_ebird_description_is_not_cached_as_text():
    """El eslogan de eBird acabó en 140 cachés como fallback_text."""
    assert content_scraper._fetch_ebird_og_description(
        "gobfly2", _WikiSession(), locale="es"
    ) == ""


def _soup(head):
    return BeautifulSoup(f"<html><head>{head}</head></html>", "html.parser")


def test_species_page_detection():
    ok = '<meta property="og:url" content="https://ebird.org/species/eurrob1"/>'
    other = '<link rel="canonical" href="https://ebird.org/home"/>'
    assert image_fetcher.is_ebird_species_page(_soup(ok), "eurrob1")
    assert not image_fetcher.is_ebird_species_page(_soup(other), "eurrob1")
    # Una página que no dice nada de sí misma se acepta, como antes.
    assert image_fetcher.is_ebird_species_page(_soup(""), "eurrob1")


# --- Commons: solo fotografías de aves vivas -------------------------------
#
# El 2026-09-25 la reparación automática publicó para gobfly2 la imagen
# principal de su artículo, que es una piel de museo de Naturalis, con el
# crédito «Sclater, 1883» (la autoridad taxonómica, no un fotógrafo) y una
# URL con parámetros utm.


def test_a_museum_skin_is_declined_and_the_next_photo_is_taken():
    """La piel no se publica; la siguiente imagen del artículo, sí."""
    session = _WikiSession(
        lead=_SKIN,
        others=[_SKIN, "Microeca hemixantha map.png", _LIVE_BIRD],
        files={
            _SKIN: _file(artist="Sclater, 1883", licence="CC0"),
            _LIVE_BIRD: _file(),
        },
    )
    result = image_fetcher.fetch_image(
        "gobfly2", session, scientific_name="Microeca hemixantha"
    )
    assert result.url == "https://upload.wikimedia.org/900px.jpg"
    assert result.attribution == "Ana Pérez / Wikimedia Commons (CC BY-SA 4.0)"


def test_only_a_specimen_leaves_the_gap():
    session = _WikiSession(lead=_SKIN, files={_SKIN: _file(licence="CC0")})
    result = image_fetcher.fetch_image(
        "gobfly2", session, scientific_name="Microeca hemixantha"
    )
    assert result.url is None


def test_description_and_categories_are_read_too():
    """Un nombre de fichero anodino no basta: la descripción y las
    categorías también cuentan."""
    for extra in (
        {"ImageDescription": "Eggs of <i>Microeca hemixantha</i>"},
        {"Categories": "Microeca hemixantha|Range maps of Petroicidae"},
        {"ImageDescription": "Plate 12 from <i>The Birds of New Guinea</i>"},
        {"Categories": "Birds on stamps of Indonesia"},
    ):
        session = _WikiSession(files={_LIVE_BIRD: _file(**extra)})
        assert image_fetcher._try_wikimedia("Microeca hemixantha", session) is None, extra


def test_a_file_of_another_species_is_declined():
    """El artículo de Microeca hemixantha usaba «SouthIslandTomtit.jpg», una
    Petroica (2026-09-25). Fuera de la imagen principal, el fichero tiene
    que nombrar la especie."""
    tomtit = "SouthIslandTomtit.jpg"
    session = _WikiSession(
        lead=_SKIN, others=[tomtit],
        files={_SKIN: _file(licence="CC0"), tomtit: _file()},
    )
    assert image_fetcher._try_wikimedia("Microeca hemixantha", session) is None

    # El mismo fichero vale si su descripción o sus categorías la nombran.
    session = _WikiSession(
        lead=_SKIN, others=[tomtit],
        files={_SKIN: _file(licence="CC0"),
               tomtit: _file(Categories="Microeca hemixantha|Birds of Tanimbar")},
    )
    assert image_fetcher._try_wikimedia("Microeca hemixantha", session) is not None


def test_whole_words_only():
    """«range» no excluye «orange», ni «plate» al Tucán Piquiplano, ni la
    categoría de mantenimiento «Pages with maps» a una foto geolocalizada."""
    session = _WikiSession(files={_LIVE_BIRD: _file(
        ImageDescription="Orange-footed bird, Plate-billed toucan nearby",
        Categories="Pages with maps|Microeca hemixantha|Birds of Tanimbar",
    )})
    assert image_fetcher._try_wikimedia("Microeca hemixantha", session) is not None


def test_only_jpeg():
    session = _WikiSession(
        lead="Microeca hemixantha.png", others=["Microeca hemixantha.png"],
        files={"Microeca hemixantha.png": _file(mime="image/png")},
    )
    assert image_fetcher._try_wikimedia("Microeca hemixantha", session) is None
    # Ni siquiera se piden metadatos de un fichero que no es JPEG.
    assert len(session.calls) == 1


def test_a_jpeg_name_with_another_mime_is_declined():
    session = _WikiSession(files={_LIVE_BIRD: _file(mime="image/tiff")})
    assert image_fetcher._try_wikimedia("Microeca hemixantha", session) is None


def test_the_url_carries_no_tracking_parameters():
    thumb = (
        "https://thumb.wikimedia.org/wikipedia/commons/thumb/6/68/X.jpeg/"
        "960px-X.jpeg?utm_source=en.wikipedia.org&utm_campaign=imageinfo"
        "&utm_content=thumbnail"
    )
    session = _WikiSession(files={_LIVE_BIRD: _file(thumb=thumb)})
    result = image_fetcher._try_wikimedia("Microeca hemixantha", session)
    assert result.url == (
        "https://thumb.wikimedia.org/wikipedia/commons/thumb/6/68/X.jpeg/"
        "960px-X.jpeg"
    )
    assert "utm" not in result.url


def test_a_taxonomic_authority_is_not_a_photographer():
    """Si Artist es la autoridad taxonómica, se usa Credit; si Credit es
    una fuente y no una persona, solo se acredita Commons y la licencia."""
    session = _WikiSession(files={_LIVE_BIRD: _file(
        artist="Sclater, 1883", Credit="Bernard Dupont",
    )})
    result = image_fetcher._try_wikimedia("Microeca hemixantha", session)
    assert result.photographer == "Bernard Dupont"
    assert result.attribution == "Bernard Dupont / Wikimedia Commons (CC BY-SA 4.0)"

    session = _WikiSession(files={_LIVE_BIRD: _file(
        artist="(Linnaeus, 1758)", Credit="Own work",
    )})
    result = image_fetcher._try_wikimedia("Microeca hemixantha", session)
    assert result.photographer == ""
    assert result.attribution == "Wikimedia Commons (CC BY-SA 4.0)"


def test_a_link_next_to_the_name_is_dropped():
    session = _WikiSession(files={_LIVE_BIRD: _file(
        artist="JJ Harrison (https://www.jjharrison.com.au/)",
    )})
    result = image_fetcher._try_wikimedia("Microeca hemixantha", session)
    assert result.photographer == "JJ Harrison"


# --- iNaturalist -----------------------------------------------------------


def test_inaturalist_goes_before_commons():
    session = _WikiSession(inat=[_taxon()])
    result = image_fetcher.fetch_image(
        "gobfly2", session, scientific_name="Microeca hemixantha"
    )
    assert result.url == (
        "https://inaturalist-open-data.s3.amazonaws.com/photos/42/large.jpg"
    )
    assert result.photographer == "Ana Pérez"
    # El sitio ya antepone «© »: el «(c)» de iNaturalist no se repite.
    assert result.attribution == "Ana Pérez / iNaturalist (CC BY-NC)"
    assert "gobfly2" in result.search_url
    assert not any("wikipedia" in url for url, _ in session.calls)


def test_inaturalist_without_a_licence_falls_through_to_commons():
    """Sin licencia es «todos los derechos reservados»: no se publica."""
    session = _WikiSession(inat=[_taxon(
        licence=None, attribution="(c) Ana Pérez, all rights reserved",
        url="https://static.inaturalist.org/photos/42/medium.jpg",
    )])
    result = image_fetcher.fetch_image(
        "gobfly2", session, scientific_name="Microeca hemixantha"
    )
    assert "inaturalist" not in result.url
    assert result.url == "https://upload.wikimedia.org/900px.jpg"


def test_inaturalist_walks_the_taxon_photos_when_the_default_is_reserved():
    """Si la foto por defecto no tiene licencia, sirve la primera con
    licencia entre las fotos del taxón (sopsku1 y gobfly2, 2026-09-25)."""
    session = _WikiSession(
        inat=[_taxon(licence=None, attribution="(c) X, all rights reserved")],
        inat_photos=[
            {"license_code": None, "attribution": "(c) Y, all rights reserved",
             "medium_url": "https://static.inaturalist.org/photos/7/medium.jpg"},
            {"license_code": "cc-by", "attribution": "(c) Zoe, some rights reserved (CC BY)",
             "url": "https://inaturalist-open-data.s3.amazonaws.com/photos/8/square.jpg"},
        ],
    )
    result = image_fetcher._try_inaturalist("Microeca hemixantha", session)
    assert result.url == (
        "https://inaturalist-open-data.s3.amazonaws.com/photos/8/large.jpg"
    )
    assert result.attribution == "Zoe / iNaturalist (CC BY)"


def test_inaturalist_takes_only_an_exact_name():
    """``q`` es una búsqueda aproximada: la especie vecina no vale."""
    session = _WikiSession(inat=[_taxon(name="Microeca flavigaster")])
    assert image_fetcher._try_inaturalist("Microeca hemixantha", session) is None
    session = _WikiSession(inat=[_taxon(name="microeca HEMIXANTHA")])
    assert image_fetcher._try_inaturalist("Microeca hemixantha", session) is not None


def test_inaturalist_licence_labels():
    for code, attribution, expected in (
        ("cc0", "(c) Ana Pérez, no rights reserved (CC0)",
         "Ana Pérez / iNaturalist (CC0)"),
        ("cc-by-nc-sa", "(c) J. Smith, some rights reserved (CC BY-NC-SA)",
         "J. Smith / iNaturalist (CC BY-NC-SA)"),
        ("cc-by", "something unexpected", "iNaturalist (CC BY)"),
    ):
        session = _WikiSession(inat=[_taxon(licence=code, attribution=attribution)])
        result = image_fetcher._try_inaturalist("Microeca hemixantha", session)
        assert result.attribution == expected


def test_inaturalist_url_loses_its_query_and_grows_to_large():
    session = _WikiSession(inat=[_taxon(
        url="https://inaturalist-open-data.s3.amazonaws.com/photos/42/medium.jpeg?1700000000",
    )])
    result = image_fetcher._try_inaturalist("Microeca hemixantha", session)
    assert result.url == (
        "https://inaturalist-open-data.s3.amazonaws.com/photos/42/large.jpeg"
    )

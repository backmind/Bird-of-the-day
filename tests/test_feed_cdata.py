"""Tests for feed_builder CDATA wrapping and round-trip."""

from scripts.feed_builder import _wrap_cdata


def test_wrap_cdata_basic():
    xml = "<content:encoded>&lt;h2&gt;Hello&lt;/h2&gt;</content:encoded>"
    result = _wrap_cdata(xml)
    assert "<![CDATA[" in result
    assert "<h2>Hello</h2>" in result


def test_wrap_cdata_unescapes_entities():
    xml = "<content:encoded>&amp; &lt; &gt; &quot;</content:encoded>"
    result = _wrap_cdata(xml)
    # The HTML entities should be unescaped inside CDATA
    assert '& < > "' in result


def test_wrap_cdata_preserves_surrounding():
    xml = '<item><title>Bird</title><content:encoded>&lt;p&gt;text&lt;/p&gt;</content:encoded></item>'
    result = _wrap_cdata(xml)
    assert "<title>Bird</title>" in result
    assert "<![CDATA[<p>text</p>]]>" in result


def test_wrap_cdata_multiple_entries():
    xml = (
        "<content:encoded>&lt;p&gt;one&lt;/p&gt;</content:encoded>"
        "<content:encoded>&lt;p&gt;two&lt;/p&gt;</content:encoded>"
    )
    result = _wrap_cdata(xml)
    assert result.count("<![CDATA[") == 2

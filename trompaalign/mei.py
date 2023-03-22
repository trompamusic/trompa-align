import hashlib
from io import BytesIO
from lxml import etree


def get_metadata_for_mei(mei_text):
    s = BytesIO(mei_text.encode())
    tree = etree.parse(s)
    ns = {"mei": "http://www.music-encoding.org/ns/mei"}
    e = tree.find("//mei:titleStmt", namespaces=ns)
    str_title = ""
    str_composer = ""
    if e is not None:
        title = e.find(".//mei:title", namespaces=ns)
        composer = e.find('.//mei:persName[@role="composer"]', namespaces=ns)
        if title is not None:
            str_title = title.text
        if composer is not None:
            str_composer = composer.text
    return {
        "title": str_title,
        "composer": str_composer
    }


def compute_sha256_for_mei(mei_text):
    if isinstance(mei_text, str):
        mei_text = mei_text.encode()
    sha = hashlib.sha256()
    sha.update(mei_text)
    return sha.hexdigest()

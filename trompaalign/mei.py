import hashlib
from io import BytesIO
from lxml import etree


def mei_is_valid(mei_text):
    """Check if the MEI file is valid.
    If the file is unable to be parsed, return False.
    """
    s = BytesIO(mei_text.encode())
    try:
        etree.parse(s)
        return True
    except etree.XMLSyntaxError as e:
        return False


def get_metadata_for_mei(mei_text):
    """Get the Title and Composer from an MEI file.
    If the file is unable to be parsed, return None.
    """
    s = BytesIO(mei_text.encode())
    try:
        tree = etree.parse(s)
    except etree.XMLSyntaxError as e:
        return None
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
    return {"title": str_title, "composer": str_composer}


def compute_sha256_for_mei(mei_text):
    if isinstance(mei_text, str):
        mei_text = mei_text.encode()
    sha = hashlib.sha256()
    sha.update(mei_text)
    return sha.hexdigest()

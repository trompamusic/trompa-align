import hashlib
from io import BytesIO
from lxml import etree
from dataclasses import dataclass


@dataclass
class Expansion:
    """An expansion in an MEI file."""

    id: str
    elements: list[str]


def mei_is_valid(mei_text):
    """Check if the MEI file is valid.
    If the file is unable to be parsed, return False.
    """
    s = BytesIO(mei_text.encode())
    try:
        etree.parse(s)
        return True
    except etree.XMLSyntaxError:
        return False


def get_metadata_for_mei(mei_text):
    """Get the Title and Composer from an MEI file.
    If the file is unable to be parsed, return None.
    """
    s = BytesIO(mei_text.encode())
    try:
        tree = etree.parse(s)
    except etree.XMLSyntaxError:
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


def get_expansions_from_mei(mei_text):
    """Get the expansions from an MEI file."""
    s = BytesIO(mei_text.encode())
    try:
        tree = etree.parse(s)
    except etree.XMLSyntaxError:
        return None
    xml_ns = "http://www.w3.org/XML/1998/namespace"
    ns = {"mei": "http://www.music-encoding.org/ns/mei", "xml": xml_ns}
    e = tree.findall("//mei:expansion", namespaces=ns)
    expansions = []
    for expansion in e:
        id = expansion.get("{%s}id" % xml_ns)
        elements = expansion.get("plist")
        element_parts = elements.split(" ")
        expansions.append(Expansion(id, element_parts))
    return expansions


def resolve_expansion_elements(expansion_map, expansion_id, visited=None):
    """Recursively resolve expansion elements to get final section IDs."""
    if visited is None:
        visited = set()

    if expansion_id in visited:
        return []

    visited.add(expansion_id)

    if expansion_id not in expansion_map:
        return []

    expansion = expansion_map[expansion_id]
    section_ids = []

    for element in expansion.elements:
        if element.startswith("#") and element[1:] in expansion_map:
            # This is another expansion, recurse into it
            section_ids.extend(resolve_expansion_elements(expansion_map, element[1:], visited.copy()))
        elif element.startswith("#"):
            # This is a section ID
            section_ids.append(element)

    return section_ids


def count_notes_in_expansions(mei_text):
    """Count the number of notes in an expansion."""
    expansions = get_expansions_from_mei(mei_text)
    if expansions is None:
        return 0

    expansion_map = {expansion.id: expansion for expansion in expansions}

    # Parse the MEI text to get the XML tree for section lookups
    s = BytesIO(mei_text.encode())
    try:
        tree = etree.parse(s)
    except etree.XMLSyntaxError:
        return 0

    xml_ns = "http://www.w3.org/XML/1998/namespace"
    ns = {"mei": "http://www.music-encoding.org/ns/mei", "xml": xml_ns}

    expansion_counts = {}

    for expansion_id, expansion in expansion_map.items():
        # Get all section IDs for the given expansion
        section_ids = resolve_expansion_elements(expansion_map, expansion_id)

        # Count notes in each section
        total_notes = 0
        for section_id in section_ids:
            # Remove the # prefix
            actual_id = section_id[1:] if section_id.startswith("#") else section_id

            # Find the element with this ID and count notes in it
            xpath = f"//*[@xml:id='{actual_id}']//mei:note"
            notes = tree.xpath(xpath, namespaces=ns)
            total_notes += len(notes)
        expansion_counts[expansion_id] = total_notes
    return expansion_counts

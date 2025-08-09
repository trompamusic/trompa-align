#!/usr/bin/env python3
"""
Comprehensive test suite for score_to_graph function to ensure behavior is preserved
during refactoring from mixed string/rdflib approach to pure rdflib approach.
"""

from scripts.convert_to_rdf import score_to_graph


class TestScoreToGraph:
    def setup_method(self):
        self.score_uri = "http://example.org/score/1"
        self.seg_uri = "http://example.org/segments/1"
        self.performance_resource = "http://example.org/performance/1"
        self.mei_uri = "http://example.org/mei/1"
        self.mei_copy_uri = "http://example.org/mei/copy/1"
        self.title = "Test Score"

    def test_score_to_graph(self):
        """Test basic score_to_graph functionality without expansions."""
        graph = score_to_graph(
            self.score_uri, self.seg_uri, self.performance_resource, self.mei_uri, self.mei_copy_uri, self.title
        )

        turtle_output = graph.serialize(format="n3")

        expected = """@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix meld: <https://meld.linkedmusic.org/terms/> .
@prefix mo: <http://purl.org/ontology/mo/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .

<http://example.org/mei/copy/1> a mo:PublishedScore ;
    skos:exactMatch <http://example.org/mei/1> .

<http://example.org/score/1> a mo:Score ;
    dcterms:title "Test Score" ;
    mo:published_as <http://example.org/mei/1> ;
    skos:related <http://example.org/performance/1> ;
    meld:segments <http://example.org/segments/1> .

<http://example.org/mei/1> a mo:PublishedScore .

"""

        assert expected == turtle_output

    def test_with_expansions(self):
        """Test score_to_graph with both expansions and note counts."""
        expansions = {"expansion-default": 120, "expansion-minimal": 60, "expansion-nested": 180}

        graph = score_to_graph(
            self.score_uri,
            self.seg_uri,
            self.performance_resource,
            self.mei_uri,
            self.mei_copy_uri,
            self.title,
            expansions=expansions,
        )

        # Use longturtle because the output is more deterministic
        # TODO: longturtle doesn't seem to use our bound namespace aliases for meld and mo, but it does for
        #  ones that are built in to rdflib (skos, dcterms). "n3" and "turtle" do, so likely a bug in longturtle.
        #  https://github.com/RDFLib/rdflib/issues/3105
        turtle_output = graph.serialize(format="longturtle")

        expected = (
            """PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX ns1: <https://meld.linkedmusic.org/terms/>
PREFIX ns2: <http://purl.org/ontology/mo/>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

<http://example.org/mei/copy/1>
    a ns2:PublishedScore ;
    skos:exactMatch <http://example.org/mei/1> ;
.

<http://example.org/score/1>
    a ns2:Score ;
    dcterms:title "Test Score" ;
    ns2:published_as <http://example.org/mei/1> ;
    skos:related <http://example.org/performance/1> ;
    ns1:expansion
        "expansion-default" ,
        "expansion-minimal" ,
        "expansion-nested" ;
    ns1:expansionNoteCount """  # Whitespace is significant here, so split into two strings
            + """
        [
            ns1:expansionId "expansion-minimal" ;
            ns1:noteCount 60 ;
        ] ,
        [
            ns1:expansionId "expansion-nested" ;
            ns1:noteCount 180 ;
        ] ,
        [
            ns1:expansionId "expansion-default" ;
            ns1:noteCount 120 ;
        ] ;
    ns1:segments <http://example.org/segments/1> ;
.

<http://example.org/mei/1>
    a ns2:PublishedScore ;
.
"""
        )
        assert expected == turtle_output

    def test_special_characters_in_title(self):
        special_title = "Test \"Score\" with & special <characters> and 'quotes'"

        graph = score_to_graph(
            self.score_uri, self.seg_uri, self.performance_resource, self.mei_uri, self.mei_copy_uri, special_title
        )
        turtle_output = graph.serialize(format="n3")

        assert """dcterms:title "Test \\"Score\\" with & special <characters> and 'quotes'" ;""" in turtle_output

"""
Comprehensive test suite for score_to_graph function to ensure behavior is preserved
during refactoring from mixed string/rdflib approach to pure rdflib approach.
"""

from rdflib import Graph
from rdflib.compare import isomorphic

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

        # Compare graphs rather than serialised text: the blank nodes used for expansionNoteCount
        # are emitted in a non-deterministic order by every serialiser, so a string comparison is flaky.
        expected = Graph()
        expected.parse(
            format="turtle",
            data="""
            PREFIX dcterms: <http://purl.org/dc/terms/>
            PREFIX meld: <https://meld.linkedmusic.org/terms/>
            PREFIX mo: <http://purl.org/ontology/mo/>
            PREFIX skos: <http://www.w3.org/2004/02/skos/core#>

            <http://example.org/mei/copy/1>
                a mo:PublishedScore ;
                skos:exactMatch <http://example.org/mei/1> .

            <http://example.org/mei/1> a mo:PublishedScore .

            <http://example.org/score/1>
                a mo:Score ;
                dcterms:title "Test Score" ;
                mo:published_as <http://example.org/mei/1> ;
                skos:related <http://example.org/performance/1> ;
                meld:segments <http://example.org/segments/1> ;
                meld:expansion "expansion-default", "expansion-minimal", "expansion-nested" ;
                meld:expansionNoteCount
                    [ meld:expansionId "expansion-default" ; meld:noteCount 120 ],
                    [ meld:expansionId "expansion-minimal" ; meld:noteCount 60 ],
                    [ meld:expansionId "expansion-nested" ; meld:noteCount 180 ] .
            """,
        )

        assert isomorphic(expected, graph)

    def test_special_characters_in_title(self):
        special_title = "Test \"Score\" with & special <characters> and 'quotes'"

        graph = score_to_graph(
            self.score_uri, self.seg_uri, self.performance_resource, self.mei_uri, self.mei_copy_uri, special_title
        )
        turtle_output = graph.serialize(format="n3")

        assert """dcterms:title "Test \\"Score\\" with & special <characters> and 'quotes'" ;""" in turtle_output

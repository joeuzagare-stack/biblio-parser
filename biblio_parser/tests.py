import pytest
from biblio_parser.parser import ReferenceParser
from biblio_parser.models import Reference

def test_regex_segmentation():
    parser = ReferenceParser()
    raw = """
    1. Smith J. A test paper. 2020.
    [2] Doe A. Another paper.
    • Johnson, R. Bullet point paper.
    """
    refs = parser.segment_references(raw)
    assert len(refs) == 3
    assert "Smith J" in refs[0]
    assert "Doe A" in refs[1]
    assert "Johnson, R" in refs[2]

def test_heuristic_parser():
    parser = ReferenceParser()
    ref_text = "Smith J, Brown P. Machine Learning Applications. Journal of AI. 2021. pp 1-10. doi:10.1016/j.cell.2020.05.001."
    
    ref = parser.parse(ref_text)
    
    assert ref.year.value == "2021"
    assert ref.doi.value == "10.1016/j.cell.2020.05.001"
    assert "Smith, J" in ref.authors
    assert "Machine Learning Applications" in ref.title.value
    assert "Journal of AI" in ref.journal.value
    assert ref.pages.value == "1--10"
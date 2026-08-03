import re
from enum import Enum
from typing import List, Optional, Any
from pydantic import BaseModel, Field, field_validator
from unidecode import unidecode
import uuid

class EntryType(str, Enum):
    ARTICLE = "article"
    BOOK = "book"
    INPROCEEDINGS = "inproceedings"
    THESIS = "thesis"
    REPORT = "report"
    MISC = "misc"

class ParsedField(BaseModel):
    value: str
    confidence: float = Field(ge=0.0, le=1.0)

class Reference(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    raw_text: str
    entry_type: EntryType = EntryType.ARTICLE
    authors: List[str] = Field(default_factory=list)
    title: Optional[ParsedField] = None
    journal: Optional[ParsedField] = None
    year: Optional[ParsedField] = None
    volume: Optional[ParsedField] = None
    issue: Optional[ParsedField] = None
    pages: Optional[ParsedField] = None
    doi: Optional[ParsedField] = None
    url: Optional[ParsedField] = None
    publisher: Optional[ParsedField] = None
    pmid: Optional[ParsedField] = None
    issn: Optional[ParsedField] = None
    isbn: Optional[ParsedField] = None
    
    # --- New Comprehensive Fields ---
    abstract: Optional[ParsedField] = None
    pmcid: Optional[ParsedField] = None
    eprint: Optional[ParsedField] = None
    editor: Optional[List[str]] = Field(default_factory=list)
    booktitle: Optional[ParsedField] = None
    institution: Optional[ParsedField] = None
    organization: Optional[ParsedField] = None
    school: Optional[ParsedField] = None
    address: Optional[ParsedField] = None
    month: Optional[ParsedField] = None
    keywords: Optional[ParsedField] = None
    series: Optional[ParsedField] = None
    edition: Optional[ParsedField] = None
    chapter: Optional[ParsedField] = None
    language: Optional[ParsedField] = None
    
    enriched: bool = False

    def generate_citation_key(self, existing_keys: set) -> str:
        """Generates a standard FirstAuthorYearTitle citation key."""
        author_part = "Unknown"
        if self.authors:
            # Extract last name of first author and normalize accents
            normalized_author = unidecode(self.authors[0].split(',')[-1])
            author_part = re.sub(r'[^a-zA-Z]', '', normalized_author).capitalize()
        
        year_part = self.year.value if self.year else "NoYear"
        
        title_part = ""
        if self.title:
            normalized_title = unidecode(self.title.value)
            words = [w for w in re.split(r'\W+', normalized_title) if len(w) > 3]
            if words:
                title_part = words[0].capitalize()

        base_key = f"{author_part}{year_part}{title_part}"
        key = base_key
        suffix = ord('a')
        while key in existing_keys:
            key = f"{base_key}{chr(suffix)}"
            suffix += 1
            if suffix > ord('z'):
                break
        return key

class ParseReport(BaseModel):
    total_references: int
    successfully_parsed: int
    failed: int
    average_confidence: float
    enriched_count: int
    duplicates_removed: int
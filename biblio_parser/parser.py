import re
from typing import List
from loguru import logger
from .models import Reference, ParsedField, EntryType
from .utils import normalize_whitespace, normalize_author

try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError as e:
    logger.error(f"PyMuPDF import failed: {e}")
    PYMUPDF_AVAILABLE = False

try:
    import docx
    DOCX_AVAILABLE = True
except ImportError as e:
    logger.error(f"python-docx import failed: {e}")
    DOCX_AVAILABLE = False

class DocumentReader:
    @staticmethod
    def read_pdf(filepath: str) -> str:
        """Reads a PDF backwards to guarantee the reference section is found."""
        if not PYMUPDF_AVAILABLE:
            raise RuntimeError("PDF parsing disabled: PyMuPDF missing.")
        
        doc = fitz.open(filepath)
        
        # If it's a tiny document, just assume the whole thing is references
        if len(doc) <= 3:
            return "\n\n".join([page.get_text("text") for page in doc])
            
        ref_text = []
        found_header = False
        
        # Scan backwards starting from the last page
        for i in range(len(doc)-1, -1, -1):
            page = doc[i]
            blocks = page.get_text("blocks")
            blocks.sort(key=lambda b: (b[0] // 150, b[1])) 
            
            page_content = []
            for b in blocks:
                text = b[4].strip()
                if not text: continue
                # Strip publisher stamps and headers
                if re.match(r'^(?:\[Page \d+\]|Made with Xodo|.*WILEY\s+.*|SEPTEMBER \d+ VOLUME)', text, re.IGNORECASE):
                    continue
                page_content.append(text)
                
            page_str = "\n\n".join(page_content)
            
            # Check for standard reference headers
            header_match = re.search(r'(?:^|\n)\s*(?:References|Bibliography|Literature Cited|Works cited)\s*(?:\n|$)', page_str, re.IGNORECASE)
            
            if header_match:
                # We found the header! Keep everything after it and stop scanning backwards.
                ref_text.insert(0, page_str[header_match.end():])
                found_header = True
                break
            else:
                ref_text.insert(0, page_str)
                
            # Stop looking if we've gone back more than 35% of the document
            if i < len(doc) * 0.65:
                break
                
        if found_header:
            return "\n\n".join(ref_text)
            
        # ABSOLUTE FAILSAFE: If no header was ever found, grab the last 20% of the document.
        # It is much safer to parse some junk text than to return 0 references.
        fallback_text = []
        for i in range(int(len(doc) * 0.80), len(doc)):
            fallback_text.append(doc[i].get_text("text"))
            
        return "\n\n".join(fallback_text)

    @staticmethod
    def read_docx(filepath: str) -> str:
        if not DOCX_AVAILABLE:
            raise RuntimeError("DOCX disabled: python-docx missing.")
        doc = docx.Document(filepath)
        return "\n".join([para.text for para in doc.paragraphs])
        
    @staticmethod
    def read_txt(filepath: str) -> str:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()

    @staticmethod
    def read_csv(filepath: str) -> str:
        """Reads exported CSV files containing citations."""
        try:
            import pandas as pd
            df = pd.read_csv(filepath)
            # Merge the columns of each row into a single string, separated by double newlines
            return "\n\n".join(df.astype(str).agg(' '.join, axis=1).tolist())
        except Exception as e:
            logger.error(f"Failed to read CSV with pandas: {e}")
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read()

class ReferenceParser:
    def __init__(self):
        self.doi_pattern = re.compile(r'(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)', re.IGNORECASE)
        self.year_pattern = re.compile(r'\b(19|20)\d{2}\b')
        self.url_pattern = re.compile(r'https?://\S+')
        self.pages_pattern = re.compile(r'\b(?:pp?\.?\s*)?(\d+)[-–](\d+)\b')

    def segment_references(self, text: str) -> List[str]:
        """Highly resilient multi-stage segmenter for text, CSV, and PDF blobs."""
        # Strip invisible zero-width spaces that break regex
        text = re.sub(r'[\u200b\u200e\u200f\u202a-\u202e\xa0]', ' ', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        # Add a newline to the start to help regex boundary detection
        padded_text = "\n" + text.strip()
        
        # 1. Primary Heuristic: Explicit Numbering (e.g. 1. or [1])
        number_pattern = r'\n\s*(?:\[\d{1,4}\]|\(\d{1,4}\)|\b\d{1,4}\.|\b\d{1,4}\s+(?=[A-Z]))\s+'
        if len(re.findall(number_pattern, padded_text)) >= 3:
            parts = re.split(r'(?=\n\s*(?:\[\d{1,4}\]|\(\d{1,4}\)|\b\d{1,4}\.|\b\d{1,4}\s+(?=[A-Z]))\s+)', padded_text)
            refs = [normalize_whitespace(p) for p in parts if len(p.strip()) > 15]
            if len(refs) >= 3: return refs
            
        # 2. Secondary Heuristic: Double Newlines (Common in CSVs and copy-paste)
        parts = re.split(r'\n\s*\n', text)
        refs = [normalize_whitespace(p) for p in parts if len(p.strip()) > 20]
        if len(refs) >= 3: return refs
        
        # 3. Tertiary Heuristic: Single Newlines (If each line is a full unnumbered citation)
        lines = [normalize_whitespace(line) for line in text.split('\n') if len(line.strip()) > 20]
        if len(lines) >= 3: return lines
        
        # 4. Ultimate Fallback: Slicing a giant unformatted block
        parts = re.split(r'(?<=\d{4}\.)\s+(?=[A-Z][a-z]+,)', text)
        refs = [normalize_whitespace(p) for p in parts if len(p.strip()) > 20]
        
        return refs if refs else [normalize_whitespace(text)]

    def parse(self, raw_text: str) -> Reference:
        ref = Reference(raw_text=raw_text)
        text = raw_text

        # 1. DOI Extraction
        doi_match = self.doi_pattern.search(text)
        if doi_match:
            clean_doi = doi_match.group(1).rstrip('.')
            ref.doi = ParsedField(value=clean_doi, confidence=1.0)
            text = text.replace(doi_match.group(0), "")

        # 2. URL Extraction
        url_match = self.url_pattern.search(text)
        if url_match:
            clean_url = url_match.group(0).rstrip('.')
            if not clean_url.startswith('https://doi.org'):
                ref.url = ParsedField(value=clean_url, confidence=0.95)
            text = text.replace(url_match.group(0), "")

        # 3. Year Extraction
        year_match = self.year_pattern.search(text)
        if year_match:
            ref.year = ParsedField(value=year_match.group(0), confidence=0.9)

        # 4. Pages Extraction
        pages_match = self.pages_pattern.search(text)
        if pages_match:
            ref.pages = ParsedField(value=f"{pages_match.group(1)}--{pages_match.group(2)}", confidence=0.85)

        # 5. Sentence Boundary Extraction (Authors -> Title -> Journal)
        # Protects initials (J. D.) from splitting by checking for single uppercase letters
        clean_text = re.sub(r'^\s*(?:\[\d{1,4}\]|\(\d{1,4}\)|\b\d{1,4}\.|\b\d{1,4}\)|\b\d{1,4}\s+(?=[A-Z])|\•|\*)\s*', '', text).strip()
        parts = []
        current_part = []
        for word in clean_text.split():
            current_part.append(word)
            if word.endswith('.'):
                clean_word = word.strip('.,()')
                if len(clean_word) == 1 and clean_word.isupper():
                    continue 
                parts.append(" ".join(current_part))
                current_part = []
                
        if current_part:
            parts.append(" ".join(current_part))
            
        parts = [p.strip(' .') for p in parts if len(p.strip(' .')) > 3]
        
        if len(parts) >= 1:
            # First distinct sentence is usually authors
            authors_raw = re.split(r'[,&]| and ', parts[0])
            ref.authors = [normalize_author(a) for a in authors_raw if len(a) > 3]
        if len(parts) >= 2:
            ref.title = ParsedField(value=parts[1], confidence=0.8)
        if len(parts) >= 3:
            ref.journal = ParsedField(value=parts[2], confidence=0.7)

        return ref
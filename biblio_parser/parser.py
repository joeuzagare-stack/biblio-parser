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
        """Reads a PDF, gracefully handling fused blocks, multi-column layouts and missing headers."""
        if not PYMUPDF_AVAILABLE:
            raise RuntimeError("PDF parsing is disabled because the PyMuPDF library failed to load.")
        
        doc = fitz.open(filepath)
        lines = []
        found_refs = False
        
        for page_num, page in enumerate(doc):
            blocks = page.get_text("blocks")
            
            # Using 150px buckets. This safely handles 1, 2, 3, and 4 column layouts 
            # by grouping blocks horizontally before sorting them vertically.
            blocks.sort(key=lambda b: (b[0] // 150, b[1])) 
            
            for b in blocks:
                text = b[4].strip()
                if not text: continue
                
                # Strip zero-width spaces that break regex
                text = re.sub(r'[\u200b\u200e\u200f\u202a-\u202e\xa0]', ' ', text)
                
                # Filter out publisher stamps, watermarks, and headers
                if re.search(r'^(?:\[Page \d+\]|Made with Xodo|.*WILEY\s+AJH.*|Springer Nature|www\.nature\.com|SEPTEMBER \d+ VOLUME)', text, re.IGNORECASE):
                    continue
                if re.match(r'^\d+\s+[A-Z]+\s+\d+\s+VOLUME\s+\d+$', text, re.IGNORECASE):
                    continue
                
                if not found_refs:
                    block_lines = text.split('\n')
                    for i, line in enumerate(block_lines):
                        clean_line = line.strip()
                        if not clean_line: continue
                        
                        # 1. Standard Header Detection inside the block
                        if re.search(r'^\s*(?:\d+\.?\s*)?(?:References|Bibliography|Literature Cited|Works Cited)\s*$', clean_line, re.IGNORECASE):
                            found_refs = True
                            lines.append("\n".join(block_lines[i+1:])) # Append everything AFTER the header
                            break
                        
                        # 2. Fallback: If we are in the last 50% of the document and see an obvious citation
                        if page_num >= len(doc) * 0.50:
                            # Matches exact starts like "1. Author" or "[1] Author"
                            if re.match(r'^\s*(?:\[1\]|1\.)\s*[A-Z]', clean_line) or \
                               re.match(r'^\s*(?:\[\d{1,4}\]|\d{1,4}\.)\s+(?:[A-Z][a-z]+,\s+[A-Z]|[A-Z]\.\s+[A-Z][a-z]+)', clean_line):
                                found_refs = True
                                lines.append("\n".join(block_lines[i:])) # Append from the citation downwards
                                break
                else:
                    # Keep original structural newlines to prevent fusing separate references
                    lines.append(text)
                    
        return "\n\n".join(lines)

    @staticmethod
    def read_docx(filepath: str) -> str:
        if not DOCX_AVAILABLE:
            raise RuntimeError("DOCX parsing is disabled because python-docx failed to load.")
        doc = docx.Document(filepath)
        return "\n".join([para.text for para in doc.paragraphs])
        
    @staticmethod
    def read_txt(filepath: str) -> str:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()

class ReferenceParser:
    def __init__(self):
        self.doi_pattern = re.compile(r'(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)', re.IGNORECASE)
        self.year_pattern = re.compile(r'\b(19|20)\d{2}\b')
        self.url_pattern = re.compile(r'https?://\S+')
        self.pages_pattern = re.compile(r'\b(?:pp?\.?\s*)?(\d+)[-–](\d+)\b')

    def segment_references(self, text: str) -> List[str]:
        # Clean invisible characters
        text = re.sub(r'[\u200b\u200e\u200f\u202a-\u202e\xa0]', ' ', text)
        
        # Normalize multiple newlines
        text = re.sub(r'\n{3,}', '\n\n', text)
        raw_lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        references = []
        current_ref = []
        
        # Matches [1], (1), 1., 1), 1 (with space), or bullet points (capped at 4 digits to prevent matching years)
        start_pattern = re.compile(r'^\s*(?:\[\d{1,4}\]|\(\d{1,4}\)|\b\d{1,4}\.|\b\d{1,4}\)|\b\d{1,4}\s+(?=[A-Z])|\•|\*)')
        
        for line in raw_lines:
            match = start_pattern.match(line)
            is_start = False
            
            if match:
                is_start = True
            else:
                # Unnumbered lists heuristic
                if len(line) > 10 and re.match(r'^[A-Z][a-z]+(?:,\s+[A-Z]\.)+(?:\s*&|\s+and)?', line) and not current_ref:
                    is_start = True
                    
            if is_start or (len(line) > 60 and not current_ref):
                if current_ref:
                    references.append(" ".join(current_ref))
                current_ref = [line]
            else:
                current_ref.append(line)
                
        if current_ref:
            references.append(" ".join(current_ref))
            
        # Fallback for Giant Blobs (if newlines were destroyed by user clipboard)
        if len(references) < 10 and len(text) > 1000:
            combined = " ".join(raw_lines)
            parts = re.split(r'(?=\s(?:\[\d{1,4}\]|\b\d{1,4}\.|\(\d{1,4}\))\s)', combined)
            if len(parts) > len(references):
                references = parts
                
        return [normalize_whitespace(ref) for ref in references if len(ref) > 15]

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
            text = text.replace(year_match.group(0), "")

        # 4. Pages Extraction
        pages_match = self.pages_pattern.search(text)
        if pages_match:
            ref.pages = ParsedField(value=f"{pages_match.group(1)}--{pages_match.group(2)}", confidence=0.85)
            text = text.replace(pages_match.group(0), "")

        # 5. Clean starting markers
        clean_text = re.sub(r'^\s*(?:\[\d{1,4}\]|\(\d{1,4}\)|\b\d{1,4}\.|\b\d{1,4}\)|\b\d{1,4}\s+(?=[A-Z])|\•|\*)\s*', '', text).strip()
        
        # 6. Smart Word Grouping (Protects Author initials like "J. D." from shattering)
        parts = []
        current_part = []
        for word in clean_text.split():
            current_part.append(word)
            if word.endswith('.'):
                clean_word = word.strip('.,()')
                # If it's a single uppercase letter, it's an initial. Don't split the sentence yet!
                if len(clean_word) == 1 and clean_word.isupper():
                    continue 
                
                parts.append(" ".join(current_part))
                current_part = []
                
        if current_part:
            parts.append(" ".join(current_part))
            
        parts = [p.strip(' .') for p in parts if p.strip(' .')]
        
        # Group Authors + Title into a single robust query string for Crossref
        if len(parts) >= 1:
            ref.title = ParsedField(value=parts[0], confidence=0.8)
        if len(parts) >= 2:
            ref.journal = ParsedField(value=parts[1], confidence=0.7)

        return ref
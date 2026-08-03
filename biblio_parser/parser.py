import re
from typing import List
from loguru import logger
from .models import Reference, ParsedField, EntryType
from .utils import normalize_whitespace, normalize_author

# ---------------------------------------------------------
# Graceful Imports for Production (Prevents Cloud Crashes)
# ---------------------------------------------------------
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
        if not PYMUPDF_AVAILABLE:
            raise RuntimeError("PDF parsing is disabled because the PyMuPDF library failed to load on this server.")
        
        doc = fitz.open(filepath)
        lines = []
        found_refs = False
        
        for page in doc:
            blocks = page.get_text("blocks")
            
            # b[0] is the X-coordinate. We divide by 250px to bucket the left and right columns!
            blocks.sort(key=lambda b: (b[0] // 250, b[1])) 
            
            for b in blocks:
                text = b[4].strip()
                if not text: continue
                
                # Clean zero-width spaces immediately
                text = re.sub(r'[\u200b\u200e\u200f\u202a-\u202e\xa0]', ' ', text)
                
                # Filter out publisher stamps, watermarks, and headers
                if re.match(r'^(?:\[Page \d+\]|Made with Xodo|\d+,\s*0,\s*Downloaded from)', text, re.IGNORECASE):
                    continue
                
                # Broad check for references section ("Works Cited", "References")
                if not found_refs:
                    if re.search(r'^\s*(?:\d+\.?\s*)?(?:References|Bibliography|Literature Cited|Works Cited)\s*$', text, re.IGNORECASE):
                        found_refs = True
                        continue
                
                if found_refs or len(doc) <= 2:
                    # Keep original structural newlines to prevent fusing separate references
                    lines.append(text)
                    
        return "\n\n".join(lines)

    @staticmethod
    def read_docx(filepath: str) -> str:
        if not DOCX_AVAILABLE:
            raise RuntimeError("DOCX parsing is disabled because python-docx failed to load on this server.")
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
        # 1. Clean invisible characters and common PDF artifacts
        text = re.sub(r'[\u200b\u200e\u200f\u202a-\u202e\xa0]', ' ', text)
        
        # 2. Aggressively strip rogue page headers and publisher footers inside the text blob
        text = re.sub(r'(?im)^\[Page \d+\].*$', '', text)
        text = re.sub(r'(?im)^\d+,\s*0,\s*Downloaded from.*$', '', text)
        text = re.sub(r'(?im)^Made with Xodo.*$', '', text)
        text = re.sub(r'(?im)^.*?WILEY\s+AJH.*?$', '', text)
        text = re.sub(r'(?im)^RAJKUMAR$', '', text)
        
        # 3. Normalize multiple newlines
        text = re.sub(r'\n{3,}', '\n\n', text)

        raw_lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        references = []
        current_ref = []
        
        # Matches [1], (1), 1., 1), 1 (with space), or bullet points
        start_pattern = re.compile(r'^\s*(?:\[\d+\]|\(\d+\)|\d+\.|\d+\)|\d+\s+(?=[A-Z])|\•|\*)')
        
        for line in raw_lines:
            match = start_pattern.match(line)
            is_start = False
            
            if match:
                is_start = True # Any line starting with a number in the References section is safe
            else:
                # Unnumbered lists heuristic (e.g., "Smith J, Brown P. (2020)...")
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
            
        # 4. Fallback for Giant Blobs (if newlines were destroyed by user clipboard)
        if len(references) < 10 and len(text) > 1000:
            combined = " ".join(raw_lines)
            parts = re.split(r'(?=\s(?:\[\d+\]|\b\d+\.|\(\d+\))\s)', combined)
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
            text = text.replace(year_match.group(0), "") # Remove year from text

        # 4. Pages Extraction
        pages_match = self.pages_pattern.search(text)
        if pages_match:
            ref.pages = ParsedField(value=f"{pages_match.group(1)}--{pages_match.group(2)}", confidence=0.85)
            text = text.replace(pages_match.group(0), "") # Remove pages from text

        # 5. Clean starting markers
        clean_text = re.sub(r'^\s*(\[\d+\]|\(\d+\)|\d+\.|\d+\)|\d+\s+(?=[A-Z])|\•|\*)\s*', '', text).strip()
        
        # 6. Universal Sentence Boundary Segmentation (Works for AMA, MLA, and APA)
        parts = [p.strip() for p in re.split(r'\.\s+', clean_text) if p.strip()]
        
        if len(parts) >= 2:
            part0 = parts[0]
            # Authors typically have commas, "et al", or are short phrases
            if "et al" in part0.lower() or "," in part0 or len(part0.split()) <= 6:
                authors_raw = re.split(r'[,&]| and ', part0)
                ref.authors = [normalize_author(a) for a in authors_raw if len(a) > 3]
                
                # Handle APA formatting where year is in parentheses after authors
                title_idx = 1
                if len(parts) > title_idx and re.match(r'^\(?\d{4}\)?$', parts[title_idx]):
                    title_idx += 1
                    
                if len(parts) > title_idx:
                    ref.title = ParsedField(value=parts[title_idx], confidence=0.8)
                if len(parts) > title_idx + 1:
                    ref.journal = ParsedField(value=parts[title_idx + 1], confidence=0.7)
            else:
                # First part might be a Title if no authors present
                ref.title = ParsedField(value=part0, confidence=0.6)
                if len(parts) > 1:
                    ref.journal = ParsedField(value=parts[1], confidence=0.5)
        elif len(parts) == 1:
            ref.title = ParsedField(value=parts[0], confidence=0.5)

        return ref
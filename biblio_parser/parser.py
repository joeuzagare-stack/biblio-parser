import re
from typing import List
import fitz  # PyMuPDF
import docx
from loguru import logger
from .models import Reference, ParsedField, EntryType
from .utils import normalize_whitespace, normalize_author

class DocumentReader:
    @staticmethod
    def read_pdf(filepath: str) -> str:
        """Reads a PDF, detects 'References'/'Works cited' block, and handles physical layout blocks."""
        doc = fitz.open(filepath)
        lines = []
        found_refs = False
        
        for page in doc:
            blocks = page.get_text("blocks")
            # Sort blocks vertically, then horizontally
            blocks.sort(key=lambda b: (b[1], b[0])) 
            
            for b in blocks:
                text = b[4].strip()
                if not text: continue
                
                # Detect Bibliography/References/Works Cited section heading
                if not found_refs:
                    clean_text = text.lower().strip()
                    # Check if line is short (to avoid triggering on a sentence) and contains a heading keyword
                    if len(clean_text) < 50 and any(h in clean_text for h in ['references', 'bibliography', 'literature cited', 'works cited']):
                        found_refs = True
                        continue
                    
                if found_refs or len(doc) <= 2: # If it's a short doc, assume it's just refs
                    # Clean up zero-width spaces and weird unicode spaces that break regex
                    text = re.sub(r'[\u200b\u200e\u200f\u202a-\u202e\xa0]', ' ', text)
                    lines.append(text.replace('\n', ' '))
                    
        return "\n".join(lines)

    @staticmethod
    def read_docx(filepath: str) -> str:
        doc = docx.Document(filepath)
        return "\n".join([para.text for para in doc.paragraphs])
        
    @staticmethod
    def read_txt(filepath: str) -> str:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()

class ReferenceParser:
    def __init__(self):
        # Official Crossref regex logic
        self.doi_pattern = re.compile(r'(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)', re.IGNORECASE)
        self.year_pattern = re.compile(r'\b(19|20)\d{2}\b')
        self.url_pattern = re.compile(r'https?://\S+')
        self.pages_pattern = re.compile(r'\b(?:pp?\.?\s*)?(\d+)[-–](\d+)\b')

    def segment_references(self, text: str) -> List[str]:
        """Multi-stage segmenter handling wrapped lines, missing newlines, and invisible characters."""
        # 1. Clean up invisible zero-width spaces that break regex
        text = re.sub(r'[\u200b\u200e\u200f\u202a-\u202e\xa0]', ' ', text)
        
        raw_lines = text.split('\n')
        
        # 2. Auto-truncate to reference section if a header is found
        ref_start_idx = 0
        for i, line in enumerate(raw_lines):
            clean_line = line.strip().lower()
            if len(clean_line) < 50 and any(h in clean_line for h in ['references', 'bibliography', 'literature cited', 'works cited']):
                ref_start_idx = i + 1
                
        if ref_start_idx > 0 and (len(raw_lines) - ref_start_idx) > 2:
            raw_lines = raw_lines[ref_start_idx:]

        # 3. Handle massive single-line copy-pastes by searching for inline sequential markers
        combined_text = " ".join([line.strip() for line in raw_lines])
        combined_text = re.sub(r'\s+', ' ', combined_text).strip()
        
        # Look for [1], (1), or 1. with spaces around them
        marker_pattern = re.compile(r'(?:^|\s)(\[\d+\]|\(\d+\)|\b\d+\.)(?=\s)')
        matches = list(marker_pattern.finditer(combined_text))
        
        # Extract numbers to check if they form a sequence
        sequence = []
        for m in matches:
            num_str = re.sub(r'\D', '', m.group(1))
            if num_str:
                sequence.append(int(num_str))
                
        is_numbered_list = False
        if len(sequence) > 3:
            # Check if mostly increasing (validating it's a bibliography sequence)
            increasing_count = sum(1 for i in range(1, len(sequence)) if sequence[i] > sequence[i-1])
            if increasing_count / len(sequence) > 0.5: 
                is_numbered_list = True

        references = []
        
        if is_numbered_list:
            # Slice the giant string at every marker
            last_idx = 0
            for match in matches:
                start = match.start()
                if start > last_idx:
                    segment = combined_text[last_idx:start].strip()
                    if segment:
                        references.append(segment)
                
                # Advance pointer to start of marker (ignoring the matched leading space)
                marker_str = match.group(1)
                marker_start = start + combined_text[start:match.end()].find(marker_str)
                last_idx = marker_start
                
            if last_idx < len(combined_text):
                references.append(combined_text[last_idx:].strip())
                
            # Remove prologue text before the first citation
            if references and not re.match(r'^(\[\d+\]|\(\d+\)|\b\d+\.)', references[0]):
                references.pop(0)
        else:
            # Fallback to standard newline-based separation (APA, Harvard, etc.)
            lines = [line.strip() for line in raw_lines if line.strip()]
            current_ref = []
            start_pattern = re.compile(r'^(\[\d+\]|\(\d+\)|\d+\.|\d+\)|\•|\*|[A-Z][a-z]+(?:,\s+[A-Z]\.)+(?:\s*&|\s+and)?)\s+')
            
            for line in lines:
                if start_pattern.match(line) or (len(line) > 50 and not current_ref):
                    if current_ref:
                        references.append(" ".join(current_ref))
                    current_ref = [line]
                else:
                    current_ref.append(line)
                    
            if current_ref:
                references.append(" ".join(current_ref))
                
        return [normalize_whitespace(ref) for ref in references if len(ref) > 10]

    def parse(self, raw_text: str) -> Reference:
        """Heuristic-based reference parser relying on sentence boundaries."""
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

        # 3. Clean starting markers (1. / [1] / etc.)
        clean_text = re.sub(r'^\s*(\[\d+\]|\(\d+\)|\d+\.|\d+\)|\•|\*)\s*', '', text).strip()

        # 4. Year Extraction
        year_match = self.year_pattern.search(clean_text)
        if year_match:
            ref.year = ParsedField(value=year_match.group(0), confidence=0.9)

        # 5. Pages Extraction
        pages_match = self.pages_pattern.search(clean_text)
        if pages_match:
            ref.pages = ParsedField(value=f"{pages_match.group(1)}--{pages_match.group(2)}", confidence=0.85)

        # 6. Split by typical sentence boundaries (Period+Space+Capital, Question Mark)
        parts = [p.strip() for p in re.split(r'\.\s+(?=[A-Z])|\?\s+|\!\s+', clean_text) if p.strip()]

        if not parts:
            return ref

        if len(parts) == 1:
            # Single block (Title only, common in pasted web links)
            ref.title = ParsedField(value=parts[0].strip(', '), confidence=0.5)
        else:
            # Determine if the first block is Authors or Title
            part0 = parts[0]
            part0_inner = part0.strip(', ')
            
            is_authors = False
            words = part0_inner.split()
            
            if "et al" in part0_inner.lower():
                is_authors = True
            elif "," in part0_inner:
                is_authors = True
            elif len(words) > 1 and all(len(w) <= 2 or w.isupper() for w in words[1:]): 
                # Catch formats like "Smith JA"
                is_authors = True
                
            if is_authors:
                authors_raw = re.split(r'[,&]| and ', part0)
                ref.authors = [normalize_author(a) for a in authors_raw if len(a) > 2]
                ref.title = ParsedField(value=parts[1].strip(', '), confidence=0.7)
                if len(parts) > 2:
                    ref.journal = ParsedField(value=parts[2].strip(', '), confidence=0.6)
            else:
                ref.title = ParsedField(value=part0.strip(', '), confidence=0.6)
                if len(parts) > 1:
                    ref.journal = ParsedField(value=parts[1].strip(', '), confidence=0.5)

        return ref
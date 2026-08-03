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
        """Reads a PDF, robustly detects 'References' block, and handles physical layout blocks."""
        doc = fitz.open(filepath)
        lines = []
        found_refs = False
        
        for page in doc:
            blocks = page.get_text("blocks")
            blocks.sort(key=lambda b: (b[1], b[0])) 
            
            for b in blocks:
                block_text = b[4].strip()
                if not block_text: continue
                
                # Clean zero-width spaces immediately (fixes web/Google Docs paste bugs)
                block_text = re.sub(r'[\u200b\u200e\u200f\u202a-\u202e\xa0]', ' ', block_text)
                
                if not found_refs:
                    # Check line by line inside the block to see if the heading is embedded
                    block_lines = block_text.split('\n')
                    for i, line in enumerate(block_lines):
                        clean_line = line.strip()
                        # Match "References", "Works Cited", "Bibliography", etc.
                        if re.match(r'^\s*(?:\d+\.?\s*)?(?:References|Bibliography|Literature Cited|Works Cited)\s*$', clean_line, re.IGNORECASE):
                            found_refs = True
                            # Append the REST of this block (if any) as a single space-separated string
                            remaining = " ".join(block_lines[i+1:]).strip()
                            if remaining:
                                lines.append(remaining)
                            break
                else:
                    # We are inside the references section.
                    # Replace newlines within the block with spaces to stitch sentences back together.
                    lines.append(block_text.replace('\n', ' '))
                    
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
        """Multi-stage segmenter handling wrapped lines and various markers."""
        # 1. Clean invisible characters
        text = re.sub(r'[\u200b\u200e\u200f\u202a-\u202e\xa0]', ' ', text)
        raw_lines = text.split('\n')
        
        # 2. Auto-truncate to reference section if a header is found (Fallback for TXT/DOCX)
        ref_start_idx = 0
        for i, line in enumerate(raw_lines):
            clean_line = line.strip().lower()
            if re.match(r'^\s*(?:\d+\.?\s*)?(?:references|bibliography|literature cited|works cited)\s*$', clean_line):
                ref_start_idx = i + 1
                break
                
        if ref_start_idx > 0 and (len(raw_lines) - ref_start_idx) > 2:
            raw_lines = raw_lines[ref_start_idx:]

        # 3. Check for massive single-line blocks (pasted text with lost newlines)
        combined_text = " ".join([line.strip() for line in raw_lines])
        combined_text = re.sub(r'\s+', ' ', combined_text).strip()
        
        # Look for numbers (1-3 digits) optionally followed by a period, that have a space after
        marker_pattern = re.compile(r'(?:^|\s)(\[\d+\]|\(\d+\)|\b\d{1,3}\.?)(?=\s)')
        matches = list(marker_pattern.finditer(combined_text))
        
        valid_matches = []
        expected = 1
        for match in matches:
            num_str = re.sub(r'\D', '', match.group(1))
            if num_str:
                num = int(num_str)
                # Ensure the number is strictly in an increasing sequence (allow gap of 1 or 2 for OCR errors)
                if expected <= num <= expected + 2:
                    valid_matches.append(match)
                    expected = num + 1
                    
        references = []
        if len(valid_matches) >= 3:
            # Slice the giant string at every validated sequence marker
            last_idx = 0
            for match in valid_matches:
                start = match.start()
                if start > last_idx:
                    segment = combined_text[last_idx:start].strip()
                    if segment:
                        references.append(segment)
                
                marker_str = match.group(1)
                marker_start = start + combined_text[start:match.end()].find(marker_str)
                last_idx = marker_start
                
            if last_idx < len(combined_text):
                references.append(combined_text[last_idx:].strip())
                
            if references and not re.match(r'^(\[\d+\]|\(\d+\)|\b\d{1,3}\.?)', references[0]):
                references.pop(0)
        else:
            # Fallback to standard newline-based separation
            lines = [line.strip() for line in raw_lines if line.strip()]
            current_ref = []
            # Start pattern: allow 1-3 digit numbers without dots (e.g. "1 Kawashima")
            start_pattern = re.compile(r'^(\[\d+\]|\(\d+\)|\b\d{1,3}\.?|\d+\)|\•|\*|[A-Z][a-z]+(?:,\s+[A-Z]\.)+(?:\s*&|\s+and)?)(?:\s+|$)')
            
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
        """Heuristic-based reference parser (No generic NLP)."""
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

        # 5. Clean starting markers (1. / [1] / 1 / etc.)
        clean_text = re.sub(r'^\s*(\[\d+\]|\(\d+\)|\b\d{1,3}\.?|\•|\*)\s*', '', text).strip()
        
        # 6. Split by period to separate authors, title, journal
        parts = [p.strip() for p in re.split(r'\.\s+', clean_text) if p.strip()]
        
        if len(parts) >= 2:
            part0 = parts[0]
            if "et al" in part0.lower() or "," in part0:
                authors_raw = re.split(r'[,&]| and ', part0)
                ref.authors = [normalize_author(a) for a in authors_raw if len(a) > 3]
                
                title_idx = 1
                if len(parts) > title_idx and re.match(r'^\(?\d{4}\)?$', parts[title_idx]):
                    title_idx += 1 # Skip year if it's sitting between Author and Title (APA)
                    
                if len(parts) > title_idx:
                    ref.title = ParsedField(value=parts[title_idx], confidence=0.7)
                if len(parts) > title_idx + 1:
                    ref.journal = ParsedField(value=parts[title_idx + 1], confidence=0.6)
            else:
                ref.title = ParsedField(value=part0, confidence=0.6)
                if len(parts) > 1:
                    ref.journal = ParsedField(value=parts[1], confidence=0.5)
        elif len(parts) == 1:
            ref.title = ParsedField(value=parts[0], confidence=0.5)

        return ref
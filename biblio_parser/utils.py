import re
import string
from rapidfuzz import fuzz
from typing import List
from unidecode import unidecode
from .models import Reference

def normalize_whitespace(text: str) -> str:
    """Removes duplicate spaces, OCR artifacts, and normalizes breaks."""
    text = re.sub(r'[\r\n]+', ' ', text)
    text = re.sub(r'\s{2,}', ' ', text)
    text = re.sub(r'-\s+', '', text) # Fix hyphenated line breaks
    return text.strip()

def normalize_author(author_str: str) -> str:
    """Normalizes an author string to 'Lastname, Firstname' format."""
    author_str = author_str.strip()
    author_str = re.sub(r'\.$', '', author_str)
    if "," in author_str:
        return author_str
    
    parts = author_str.split()
    if len(parts) == 1:
        return parts[0]
    
    last_name = parts[-1]
    first_names = " ".join(parts[:-1])
    return f"{last_name}, {first_names}"

def is_duplicate(ref1: Reference, ref2: Reference) -> bool:
    """Detects if two references are duplicates using DOI or fuzzy matching."""
    if ref1.doi and ref2.doi and ref1.doi.value == ref2.doi.value:
        return True
    
    if ref1.title and ref2.title:
        score = fuzz.token_sort_ratio(ref1.title.value.lower(), ref2.title.value.lower())
        if score > 90:
            return True
            
    return False

def deduplicate_references(references: List[Reference]) -> List[Reference]:
    """Removes duplicates from a list of references in O(N) time."""
    unique_refs = []
    seen_dois = set()
    seen_hashes = set()
    
    for ref in references:
        is_dup = False
        
        # Check DOI first
        if ref.doi and ref.doi.value.lower() in seen_dois:
            is_dup = True
            
        # If no DOI or not seen, check hash of Title + Year + First Author
        title_val = ref.title.value.lower()[:50] if ref.title else ""
        year_val = ref.year.value if ref.year else ""
        author_val = ref.authors[0].lower() if ref.authors else ""
        
        ref_hash = f"{unidecode(author_val)}|{year_val}|{unidecode(title_val)}"
        
        if not is_dup and ref_hash in seen_hashes and len(ref_hash) > 5:
            is_dup = True
            
        if not is_dup:
            if ref.doi:
                seen_dois.add(ref.doi.value.lower())
            seen_hashes.add(ref_hash)
            unique_refs.append(ref)
        else:
            # Keep the one with more metadata / enriched
            if ref.enriched:
                for i, u_ref in enumerate(unique_refs):
                    u_hash = f"{unidecode(u_ref.authors[0].lower() if u_ref.authors else '')}|{u_ref.year.value if u_ref.year else ''}|{unidecode(u_ref.title.value.lower()[:50] if u_ref.title else '')}"
                    if (ref.doi and u_ref.doi and ref.doi.value.lower() == u_ref.doi.value.lower()) or ref_hash == u_hash:
                        if not u_ref.enriched:
                            unique_refs[i] = ref
                        break

    return unique_refs
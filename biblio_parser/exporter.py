from typing import List
from loguru import logger
from .models import Reference

class BibTeXExporter:
    @staticmethod
    def escape_bibtex(text: str) -> str:
        """Escapes special characters for BibTeX compatibility."""
        special_chars = {
            '&': r'\&', '%': r'\%', '$': r'\$', '#': r'\#', '_': r'\_',
            '{': r'\{', '}': r'\}', '~': r'\textasciitilde{}', '^': r'\textasciicircum{}'
        }
        for char, replacement in special_chars.items():
            text = text.replace(char, replacement)
        return text

    def export(self, references: List[Reference], filepath: str):
        """Generates a strict, Zotero-compatible BibTeX file."""
        existing_keys = set()
        
        with open(filepath, 'w', encoding='utf-8') as f:
            for ref in references:
                try:
                    key = ref.generate_citation_key(existing_keys)
                    existing_keys.add(key)
                    
                    f.write(f"@{ref.entry_type.value}{{{key},\n")
                    
                    if ref.authors:
                        authors_str = " and ".join(self.escape_bibtex(a) for a in ref.authors)
                        f.write(f"  author = {{{authors_str}}},\n")
                    
                    if ref.title:
                        f.write(f"  title = {{{self.escape_bibtex(ref.title.value)}}},\n")
                        
                    if ref.journal:
                        f.write(f"  journal = {{{self.escape_bibtex(ref.journal.value)}}},\n")
                        
                    if ref.year:
                        f.write(f"  year = {{{ref.year.value}}},\n")
                        
                    if ref.volume:
                        f.write(f"  volume = {{{ref.volume.value}}},\n")
                        
                    if ref.issue:
                        f.write(f"  number = {{{ref.issue.value}}},\n")
                        
                    if ref.pages:
                        f.write(f"  pages = {{{ref.pages.value}}},\n")
                        
                    if ref.doi:
                        f.write(f"  doi = {{{ref.doi.value}}},\n")
                        
                    if ref.url:
                        f.write(f"  url = {{{self.escape_bibtex(ref.url.value)}}},\n")
                        
                    if ref.pmid:
                        f.write(f"  pmid = {{{ref.pmid.value}}},\n")
                        
                    if ref.isbn:
                        f.write(f"  isbn = {{{ref.isbn.value}}},\n")

                    if ref.issn:
                        f.write(f"  issn = {{{ref.issn.value}}},\n")
                        
                    if ref.abstract:
                        f.write(f"  abstract = {{{self.escape_bibtex(ref.abstract.value)}}},\n")
                        
                    if ref.pmcid:
                        f.write(f"  pmcid = {{{ref.pmcid.value}}},\n")
                        
                    if ref.eprint:
                        f.write(f"  eprint = {{{ref.eprint.value}}},\n")
                        
                    if ref.booktitle:
                        f.write(f"  booktitle = {{{self.escape_bibtex(ref.booktitle.value)}}},\n")
                        
                    if ref.institution:
                        f.write(f"  institution = {{{self.escape_bibtex(ref.institution.value)}}},\n")
                        
                    if ref.organization:
                        f.write(f"  organization = {{{self.escape_bibtex(ref.organization.value)}}},\n")
                        
                    if ref.school:
                        f.write(f"  school = {{{self.escape_bibtex(ref.school.value)}}},\n")
                        
                    if ref.address:
                        f.write(f"  address = {{{self.escape_bibtex(ref.address.value)}}},\n")
                        
                    if ref.month:
                        f.write(f"  month = {{{self.escape_bibtex(ref.month.value)}}},\n")
                        
                    if ref.keywords:
                        f.write(f"  keywords = {{{self.escape_bibtex(ref.keywords.value)}}},\n")
                        
                    if ref.series:
                        f.write(f"  series = {{{self.escape_bibtex(ref.series.value)}}},\n")
                        
                    if ref.edition:
                        f.write(f"  edition = {{{self.escape_bibtex(ref.edition.value)}}},\n")
                        
                    if ref.chapter:
                        f.write(f"  chapter = {{{ref.chapter.value}}},\n")
                        
                    if ref.language:
                        f.write(f"  language = {{{self.escape_bibtex(ref.language.value)}}},\n")
                        
                    if ref.editor:
                        editors_str = " and ".join(self.escape_bibtex(e) for e in ref.editor)
                        f.write(f"  editor = {{{editors_str}}},\n")
                        
                    # Always include the raw string as a note for fallback
                    f.write(f"  note = {{Raw: {self.escape_bibtex(ref.raw_text)}}}\n")
                    
                    f.write("}\n\n")
                except Exception as e:
                    logger.error(f"Failed to generate BibTeX for entry: {e}")
                    
        logger.success(f"Exported {len(references)} references to {filepath}")
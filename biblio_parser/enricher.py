import os
import asyncio
import httpx
import re
from diskcache import Cache
from rapidfuzz import fuzz
from loguru import logger
from .models import Reference, ParsedField
from .utils import normalize_author

class MetadataEnricher:
    def __init__(self, email: str = "mailto:bot@example.com"):
        # Local caching to avoid re-querying APIs on subsequent runs
        self.cache = Cache(os.path.join(os.getcwd(), ".biblio_cache"))
        self.email = email
        self.client = httpx.AsyncClient(timeout=15.0, headers={"User-Agent": f"BiblioParser ({email})"})
        self.semaphore = asyncio.Semaphore(10) # 10 Concurrent requests max

    async def close(self):
        await self.client.aclose()

    async def enrich(self, reference: Reference) -> Reference:
        """Uses Crossref/OpenAlex APIs to fetch authoritative metadata concurrently."""
        cache_key = None
        if reference.doi:
            cache_key = f"doi_{reference.doi.value}"
        elif reference.title:
            cache_key = f"title_{reference.title.value}"
            
        # Use .get() to prevent async KeyErrors during highly concurrent cloud execution
        if cache_key:
            cached_data = self.cache.get(cache_key)
            if cached_data is not None:
                logger.debug(f"Cache hit for {cache_key}")
                return self._apply_crossref_data(reference, cached_data)

        async with self.semaphore:
            try:
                if reference.doi:
                    logger.info(f"Enriching via DOI: {reference.doi.value}")
                    data = await self._fetch_crossref_doi(reference.doi.value)
                    if data:
                        self.cache[cache_key] = data
                        return self._apply_crossref_data(reference, data)
                    
                elif reference.title:
                    logger.info(f"Enriching via Title Search: {reference.title.value}")
                    data = await self._fetch_crossref_title(reference.title.value, reference)
                    if data:
                        self.cache[cache_key] = data
                        return self._apply_crossref_data(reference, data)
                    else:
                        # Fallback to OpenAlex if Crossref fails
                        logger.info(f"Crossref failed, falling back to OpenAlex for: {reference.title.value}")
                        data_oa = await self._fetch_openalex_title(reference.title.value)
                        if data_oa:
                            self.cache[cache_key] = data_oa
                            return self._apply_crossref_data(reference, data_oa)
            except Exception as e:
                logger.warning(f"Enrichment failed for reference: {e}")
                
        return reference

    async def _fetch_crossref_doi(self, doi: str) -> dict:
        url = f"https://api.crossref.org/works/{doi}"
        response = await self.client.get(url)
        if response.status_code == 200:
            return response.json().get('message', {})
        return {}

    async def _fetch_crossref_title(self, title: str, ref: Reference) -> dict:
        # Fetch multiple candidates
        url = f"https://api.crossref.org/works?query.title={title}&rows=5&mailto={self.email}"
        response = await self.client.get(url)
        if response.status_code == 200:
            items = response.json().get('message', {}).get('items', [])
            if not items: return {}
            
            # Score candidates
            best_item = None
            best_score = 0
            
            for item in items:
                score = 0
                item_title = item.get('title', [''])[0]
                score += fuzz.token_sort_ratio(title.lower(), item_title.lower())
                
                # Boost score for year match
                if ref.year and 'issued' in item:
                    date_parts = item['issued'].get('date-parts', [[None]])
                    if date_parts[0][0] and str(date_parts[0][0]) == ref.year.value:
                        score += 20 
                        
                if score > best_score:
                    best_score = score
                    best_item = item
                    
            if best_score > 85: # Require strong confidence
                return best_item
        return {}

    async def _fetch_openalex_title(self, title: str) -> dict:
        url = f"https://api.openalex.org/works?search={title}&per-page=1"
        response = await self.client.get(url)
        if response.status_code == 200:
            results = response.json().get('results', [])
            if results:
                item = results[0]
                # Map OpenAlex standard schema to Crossref format so the applier works seamlessly
                return {
                    'title': [item.get('title')],
                    'container-title': [item.get('primary_location', {}).get('source', {}).get('display_name')],
                    'issued': {'date-parts': [[item.get('publication_year')]]},
                    'DOI': item.get('doi', '').replace('https://doi.org/', ''),
                    'type': 'journal-article'
                }
        return {}

    def _apply_crossref_data(self, ref: Reference, data: dict) -> Reference:
        """Maps Crossref JSON back to our Reference model."""
        ref.enriched = True
        
        # Calculate overall confidence modifier based on what we had
        conf = 0.95 

        if 'title' in data and data['title']:
            ref.title = ParsedField(value=data['title'][0], confidence=conf)
            
        if 'container-title' in data and data['container-title']:
            ref.journal = ParsedField(value=data['container-title'][0], confidence=conf)
            
        if 'issued' in data:
            date_parts = data['issued'].get('date-parts', [[None]])
            if date_parts[0][0]:
                ref.year = ParsedField(value=str(date_parts[0][0]), confidence=conf)
                
        if 'author' in data:
            authors = []
            for author in data['author']:
                given = author.get('given', '')
                family = author.get('family', '')
                authors.append(f"{family}, {given}".strip(', '))
            ref.authors = authors

        if 'volume' in data:
            ref.volume = ParsedField(value=data['volume'], confidence=conf)
            
        if 'issue' in data:
            ref.issue = ParsedField(value=data['issue'], confidence=conf)
            
        if 'page' in data:
            ref.pages = ParsedField(value=data['page'], confidence=conf)
            
        if 'DOI' in data and data['DOI']:
            ref.doi = ParsedField(value=data['DOI'].replace('https://doi.org/', ''), confidence=1.0)
            
        # Extract Abstract & Publisher if provided by Crossref
        if 'abstract' in data and isinstance(data['abstract'], str):
            # Crossref abstracts sometimes have <jats:p> XML tags. We strip them out cleanly.
            clean_abs = re.sub(r'<[^>]+>', '', data['abstract'])
            ref.abstract = ParsedField(value=clean_abs.strip(), confidence=conf)
            
        if 'publisher' in data:
            ref.publisher = ParsedField(value=data['publisher'], confidence=conf)

        if data.get('type') == 'journal-article':
            ref.entry_type = ref.entry_type.ARTICLE
        elif data.get('type') == 'book':
            ref.entry_type = ref.entry_type.BOOK

        return ref
import os
import asyncio
from typing import List, Tuple
from loguru import logger
from .models import Reference, ParseReport
from .parser import DocumentReader, ReferenceParser
from .enricher import MetadataEnricher
from .utils import deduplicate_references
from .exporter import BibTeXExporter

class BibliographyPipeline:
    def __init__(self, offline: bool = False):
        self.parser = ReferenceParser()
        self.offline = offline
        self.exporter = BibTeXExporter()

    async def process_file(self, filepath: str) -> Tuple[List[Reference], ParseReport]:
        logger.info(f"Reading file: {filepath}")
        ext = os.path.splitext(filepath)[1].lower()
        
        if ext == '.pdf':
            text = DocumentReader.read_pdf(filepath)
        elif ext == '.docx':
            text = DocumentReader.read_docx(filepath)
        elif ext == '.txt':
            text = DocumentReader.read_txt(filepath)
        else:
            raise ValueError(f"Unsupported file format: {ext}")

        return await self.process_text(text)

    async def process_text(self, text: str) -> Tuple[List[Reference], ParseReport]:
        logger.info("Segmenting references...")
        raw_refs = self.parser.segment_references(text)
        
        parsed_refs = []
        enriched_count = 0
        failed = 0
        
        for raw in raw_refs:
            try:
                ref = self.parser.parse(raw)
                parsed_refs.append(ref)
            except Exception as e:
                logger.error(f"Failed to parse reference: {raw[:50]}... Error: {e}")
                failed += 1

        # Execute Online Enrichment Concurrently
        if not self.offline:
            logger.info("Starting Async API Enrichment...")
            enricher = MetadataEnricher()
            
            async def enrich_ref(ref):
                return await enricher.enrich(ref)
                
            parsed_refs = await asyncio.gather(*(enrich_ref(ref) for ref in parsed_refs))
            await enricher.close()
            
            enriched_count = sum(1 for r in parsed_refs if r.enriched)

        logger.info("Deduplicating references...")
        initial_count = len(parsed_refs)
        unique_refs = deduplicate_references(parsed_refs)
        duplicates_removed = initial_count - len(unique_refs)

        # Calculate average confidence for parsed fields
        total_conf, conf_count = 0.0, 0
        for ref in unique_refs:
            for field in [ref.title, ref.year, ref.journal]:
                if field:
                    total_conf += field.confidence
                    conf_count += 1
                    
        avg_conf = (total_conf / conf_count) if conf_count > 0 else 0.0

        report = ParseReport(
            total_references=len(raw_refs),
            successfully_parsed=len(unique_refs),
            failed=failed,
            average_confidence=avg_conf,
            enriched_count=enriched_count,
            duplicates_removed=duplicates_removed
        )
        
        return unique_refs, report
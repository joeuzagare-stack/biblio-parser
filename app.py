import streamlit as st
import tempfile
import os
import asyncio
import pandas as pd
from biblio_parser.pipeline import BibliographyPipeline
from biblio_parser.models import Reference, ParsedField

st.set_page_config(page_title="Biblio Parser V2", page_icon="📚", layout="wide")

st.title("📚 Production-Quality Bibliography Parser V2")
st.markdown("Upload a PDF, DOCX, or TXT file, or paste raw references below. We will parse, enrich, deduplicate, and generate a Zotero-ready BibTeX file.")

offline_mode = st.sidebar.checkbox("Offline Mode (Fast, no API enrichment)", value=False)
pipeline = BibliographyPipeline(offline=offline_mode)

tab1, tab2 = st.tabs(["Upload File", "Paste Text"])

def process_and_display(text_or_path, is_file=False):
    with st.spinner("Segmenting, Parsing, and Enriching References (Async)..."):
        if is_file:
            references, report = asyncio.run(pipeline.process_file(text_or_path))
        else:
            references, report = asyncio.run(pipeline.process_text(text_or_path))
            
    st.success(f"Successfully processed {report.successfully_parsed} references!")
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Parsed", report.successfully_parsed, f"Found {report.total_references}")
    col2.metric("Enriched via API", report.enriched_count)
    col3.metric("Duplicates Removed", report.duplicates_removed)
    
    st.subheader("Edit Metadata Before Export")
    st.markdown("You can correct titles, authors, and DOIs directly in this table before generating your BibTeX file.")
    
    # Convert to DataFrame for st.data_editor
    df_data = []
    for ref in references:
        df_data.append({
            "ID": ref.id,
            "Title": ref.title.value if ref.title else "",
            "Authors": ", ".join(ref.authors) if ref.authors else "",
            "Year": ref.year.value if ref.year else "",
            "Journal": ref.journal.value if ref.journal else "",
            "DOI": ref.doi.value if ref.doi else "",
            "PMID": ref.pmid.value if ref.pmid else "",
            "Abstract": ref.abstract.value if ref.abstract else "",
            "Raw Text": ref.raw_text
        })
        
    df = pd.DataFrame(df_data)
    edited_df = st.data_editor(df, use_container_width=True, hide_index=True)
    
    # Apply edits back to references list
    for idx, row in edited_df.iterrows():
        ref = next(r for r in references if r.id == row["ID"])
        if row["Title"]: ref.title = ParsedField(value=row["Title"], confidence=1.0)
        if row["Authors"]: ref.authors = [a.strip() for a in str(row["Authors"]).split(",")]
        if row["Year"]: ref.year = ParsedField(value=str(row["Year"]), confidence=1.0)
        if row["Journal"]: ref.journal = ParsedField(value=row["Journal"], confidence=1.0)
        if row["DOI"]: ref.doi = ParsedField(value=row["DOI"], confidence=1.0)
        if row.get("PMID"): ref.pmid = ParsedField(value=str(row["PMID"]), confidence=1.0)
        if row.get("Abstract"): ref.abstract = ParsedField(value=row["Abstract"], confidence=1.0)

    # Generate Bibtex
    with tempfile.NamedTemporaryFile(delete=False, suffix=".bib") as tmp:
        pipeline.exporter.export(references, tmp.name)
        with open(tmp.name, "r", encoding="utf-8") as f:
            bibtex_str = f.read()
            
    st.download_button(
        label="Download BibTeX (.bib)",
        data=bibtex_str,
        file_name="references.bib",
        mime="text/x-bibtex",
    )

with tab1:
    uploaded_file = st.file_uploader("Upload Bibliography (PDF, DOCX, TXT, CSV)", type=["pdf", "docx", "txt", "csv"])
    if uploaded_file is not None:
        with tempfile.NamedTemporaryFile(delete=False, suffix="." + uploaded_file.name.split('.')[-1]) as tmp:
            tmp.write(uploaded_file.getvalue())
            tmp_path = tmp.name
        
        if st.button("Parse File"):
            process_and_display(tmp_path, is_file=True)
        os.unlink(tmp_path)

with tab2:
    raw_text = st.text_area("Paste raw references here", height=300, placeholder="1. Smith J. et al. (2020). Machine Learning...\n2. Doe A. (2021). Deep Learning...")
    if st.button("Parse Text"):
        if raw_text.strip():
            process_and_display(raw_text, is_file=False)
        else:
            st.warning("Please enter some text.")
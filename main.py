import typer
import asyncio
from rich.console import Console
from rich.table import Table
from rich.progress import Progress
from biblio_parser.pipeline import BibliographyPipeline

app = typer.Typer(help="Production-Quality Bibliography Parser")
console = Console()

@app.command()
def parse(
    input_file: str = typer.Argument(..., help="Path to input file (PDF, DOCX, TXT)"),
    output: str = typer.Option("references.bib", "--output", "-o", help="Output BibTeX file"),
    offline: bool = typer.Option(False, "--offline", help="Disable online API metadata enrichment")
):
    """
    Parse a document containing a bibliography and export it to a clean BibTeX file.
    """
    pipeline = BibliographyPipeline(offline=offline)
    
    with Progress() as progress:
        task = progress.add_task("[cyan]Processing document...", total=None)
        references, report = asyncio.run(pipeline.process_file(input_file))
        progress.update(task, completed=100)
        
    pipeline.exporter.export(references, output)
    
    console.print("\n[bold green]Parsing Complete![/bold green]")
    table = Table(title="Parsing Report")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="magenta")
    
    table.add_row("Total Found", str(report.total_references))
    table.add_row("Successfully Parsed", str(report.successfully_parsed))
    table.add_row("Duplicates Removed", str(report.duplicates_removed))
    table.add_row("Metadata Enriched (Online)", str(report.enriched_count))
    table.add_row("Average Parse Confidence", f"{report.average_confidence:.2%}")
    table.add_row("Failed", str(report.failed))
    
    console.print(table)
    console.print(f"Output saved to: [bold]{output}[/bold]")

if __name__ == "__main__":
    app()
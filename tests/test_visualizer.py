import pytest
from pathlib import Path
from bpg.compiler.parser import parse_process_file
from bpg.compiler.visualizer import generate_html

def test_generate_html():
    process_file = Path("process.bpg.yaml")
    process = parse_process_file(process_file)
    html = generate_html(process)
    
    assert "BPG Visualizer" in html
    assert "bug-triage-process" in html
    assert "intake_form" in html
    assert "triage" in html
    assert "approval" in html
    assert "gitlab" in html
    assert "<svg" in html
    assert "TRIGGER" in html

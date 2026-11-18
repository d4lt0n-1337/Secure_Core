from pathlib import Path


def test_flows_csv_present():
    elf_dir = Path(__file__).resolve().parents[3] / 'elf'
    p = elf_dir / 'flows.csv'
    assert p.exists(), 'elf/flows.csv is missing'
    assert p.stat().st_size > 0

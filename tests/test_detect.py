# #78/#106 (11.09.2026): sniff содержимого загрузки и выбор высоты в FIT-парсере.
from pathlib import Path

from src.parsers.detect import sniff_kind
from src.parsers.fit_parser import _pick_altitude

FIXTURES = Path(__file__).parent / "fixtures"


def test_sniff_fit_header():
    header = bytes([14, 0x10, 0x00, 0x00, 0, 0, 0, 0]) + b".FIT" + b"\x00\x00"
    assert sniff_kind(header + b"\x00" * 32) == "fit"


def test_sniff_tcx_real_fixture_and_bom():
    assert sniff_kind((FIXTURES / "tempo_run.tcx").read_bytes()) == "tcx"
    assert sniff_kind(b"\xef\xbb\xbf  \n<TrainingCenterDatabase xmlns='x'>") == "tcx"


def test_sniff_rejects_garbage():
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
    assert sniff_kind(png) is None
    assert sniff_kind(b"MZ\x90\x00" + b"\x00" * 64) is None          # exe, переименованный в .tcx
    assert sniff_kind(b"") is None
    assert sniff_kind(b"<html><body>not a tcx</body></html>") is None


def test_pick_altitude_zero_is_valid():
    assert _pick_altitude({"enhanced_altitude": 0.0, "altitude": 12.0}) == 0.0
    assert _pick_altitude({"enhanced_altitude": None, "altitude": 12.0}) == 12.0
    assert _pick_altitude({"altitude": 0}) == 0
    assert _pick_altitude({}) is None

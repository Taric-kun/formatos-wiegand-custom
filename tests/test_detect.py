"""Pruebas de la deteccion de formato desde lecturas del lector Arduino."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from wiegand_tool import detect  # noqa: E402
from wiegand_tool.presets import hid35_corp1000, w26, w34, w37  # noqa: E402


def test_linea_del_arduino():
    assert detect.parse_reader_line("WG 4 1010 HEX=A") == "1010"
    assert detect.parse_reader_line("# comentario") is None
    assert detect.clean_bits("WG 4 1010 HEX=A") == "1010"


def test_numero_impreso():
    t = detect.printed_targets("071,07104")
    assert t[0] == (71, 7104)
    assert (None, 7104) in t


def test_w26_site_y_card():
    bits = w26().encode(site=71, card=7104)
    best = detect.detect([{"bits": bits, "printed": "071,07104"}])[0]
    assert best["card_format"] == w26().card_format
    assert best["preset"] == "W26"
    assert best["todas_ok"]


def test_w26_solo_card_con_dos_tarjetas():
    reads = [
        {"bits": w26().encode(site=71, card=7104), "printed": "7104"},
        {"bits": w26().encode(site=12, card=40000), "printed": "40000"},
    ]
    best = detect.detect(reads)[0]
    assert best["preset"] == "W26" and best["todas_ok"]


def test_w34_y_w37():
    b34 = [{"bits": w34().encode(site=5, card=c), "printed": str(c)} for c in (65000, 123)]
    assert detect.detect(b34)[0]["preset"] == "W34"
    b37 = [{"bits": w37().encode(site=1234, card=300000), "printed": "1234 300000"}]
    assert detect.detect(b37)[0]["preset"] == "W37"


def test_hid_corporate_1000_35_bits():
    f = hid35_corp1000()
    reads = [{"bits": f.encode(site=s, card=c), "printed": str(c)}
             for s, c in ((1234, 567890), (1234, 1001), (77, 400000))]
    best = detect.detect(reads)[0]
    assert best["preset"] == "HID35_Corp1000" and best["todas_ok"], best


def test_formato_no_estandar():
    # 30 bits: par + 12 site + 16 card + impar (no es un preset).
    from wiegand_tool.core import Parity, WiegandFormat
    cf = "E" + "S" * 12 + "C" * 16 + "O"
    data = list(range(1, 29))
    fmt = WiegandFormat("X30", cf, [Parity("even", data[:14]), Parity("odd", data[14:])])
    reads = [{"bits": fmt.encode(site=s, card=c), "printed": f"{s},{c}"}
             for s, c in ((200, 1234), (17, 65000))]
    best = detect.detect(reads)[0]
    assert best["card_format"] == cf and best["todas_ok"]


def test_sin_coincidencia():
    bits = w26().encode(site=1, card=1)
    assert detect.detect([{"bits": bits, "printed": "99999"}]) == []


if __name__ == "__main__":
    import traceback

    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
                passed += 1
            except Exception:
                print(f"FAIL {name}")
                traceback.print_exc()
                failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)

"""Pruebas de decodificacion e identificacion de formato desde una trama."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from wiegand_tool import decode  # noqa: E402
from wiegand_tool.presets import w26, w34  # noqa: E402


def test_roundtrip_w26_identifica_y_extrae():
    f = w26()
    frame = f.encode(site=123, card=45678)
    res = decode.identify(frame, [w26(), w34()], target=45678)
    # El de 26 bits decodifica; el de 34 se descarta por largo.
    assert any(d.card_bit == 26 for d in res)
    assert all(d.card_bit == 26 for d in res)  # w34 no aplica (otro largo)
    top = res[0]
    assert top.parity_ok
    assert top.site == 123
    assert top.card == 45678
    assert top.match_card  # coincide con el numero impreso buscado


def test_paridad_invalida_se_detecta():
    f = w26()
    frame = list(f.encode(site=1, card=2))
    # corrompe un bit de datos -> la paridad deja de cuadrar
    frame[5] = "1" if frame[5] == "0" else "0"
    d = decode.decode_frame(w26(), "".join(frame))
    assert d is not None
    assert d.parity_ok is False


def test_hex_a_bits():
    f = w26()
    frame = f.encode(site=10, card=2000)
    value = int(frame, 2)
    assert decode.bits_from_hex(hex(value), 26) == frame
    # sin ceros a la izquierda tambien rellena bien
    assert decode.bits_from_int(value, 26) == frame


def test_largo_no_coincide_devuelve_none():
    assert decode.decode_frame(w26(), "0" * 34) is None


def test_normalize_rechaza_basura():
    try:
        decode.normalize_bits("10xx01")
        assert False
    except decode.DecodeError:
        pass


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

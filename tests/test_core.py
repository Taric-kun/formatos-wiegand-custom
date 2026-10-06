"""Pruebas del motor de formatos y del generador del archivo de actualizacion."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from wiegand_tool import sqlgen  # noqa: E402
from wiegand_tool.core import FormatError, Parity, WiegandFormat  # noqa: E402
from wiegand_tool.presets import w26  # noqa: E402


def test_w26_coincide_con_fila_real_del_equipo():
    f = w26(site_code=0)
    m = f.masks()
    assert f.card_format == "ESSSSSSSSCCCCCCCCCCCCCCCCO"
    assert m["First_Even"] == "01111111111110000000000000"
    assert m["First_Odd"] == "00000000000001111111111110"
    assert m["Second_Even"] is None
    assert m["Second_Odd"] is None
    assert f.card_bit == 26


def test_encode_calcula_paridades():
    f = w26()
    frame = f.encode(site=123, card=4567)
    assert len(frame) == 26
    even_cnt = sum(1 for i in range(1, 13) if frame[i] == "1")
    assert frame[0] == ("1" if even_cnt % 2 else "0")
    odd_cnt = sum(1 for i in range(13, 25) if frame[i] == "1")
    assert frame[25] == ("0" if odd_cnt % 2 else "1")


def test_validacion_paridad_no_cubre_su_propio_bit():
    f = WiegandFormat(name="x", card_format="ECCO", parities=[
        Parity("even", [0, 1]),  # indice 0 es el propio 'E' -> invalido
        Parity("odd", [1, 2]),
    ])
    try:
        f.validate()
        assert False, "deberia haber fallado"
    except FormatError:
        pass


def test_validacion_numero_de_paridades():
    f = WiegandFormat(name="x", card_format="ECCO", parities=[Parity("even", [1, 2])])
    try:
        f.validate()
        assert False, "faltaba la paridad impar"
    except FormatError:
        pass


def test_archivo_update_sin_bom_y_lf(tmp_path):
    block = sqlgen.build_rewrite_block([w26(site_code=0)])
    assert block.startswith("[CREATE_TABLE]")
    assert "delete from HID_FORMAT where ID>0;" in block
    assert '"Wiegand26"' in block  # comillas dobles
    p = tmp_path / "update_wiegand_new.sql"
    sqlgen.write_update_file(str(p), "﻿" + block.replace("\n", "\r\n"))
    info = sqlgen.verify_update_file(str(p))
    assert info["has_bom"] is False
    assert info["has_crlf"] is False
    assert info["has_cr"] is False
    assert info["ends_with_lf"] is True


def test_activar_solo_cambia_status():
    block = sqlgen.build_activate_only_block(26, 1, format_name="Wiegand26")
    assert "[UPDATE]" in block
    assert "set Status=0 where Format_Type=1" in block
    assert "set Status=1 where Format_Type=1 and Card_Bit=26" in block
    assert "delete" not in block.lower()
    assert "insert" not in block.lower()


if __name__ == "__main__":
    import traceback

    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                import inspect

                if "tmp_path" in inspect.signature(fn).parameters:
                    import tempfile
                    from pathlib import Path

                    fn(Path(tempfile.mkdtemp()))
                else:
                    fn()
                print(f"PASS {name}")
                passed += 1
            except Exception:
                print(f"FAIL {name}")
                traceback.print_exc()
                failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)

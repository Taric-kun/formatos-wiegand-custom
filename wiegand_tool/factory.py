"""Filas de fabrica de HID_FORMAT del IN01.

Copiadas tal cual de la ZKDB.db original del reloj HHF2235000022 (IN01-A),
IDs 1..22 en orden. El reescritor del ``update.sql`` las vuelve a insertar
para no dejar el reloj sin los formatos internos (tipo 2) ni de salida
(tipo 1): con la tabla solo con nuestro formato, el IN01 deja de leer.

Se conservan los valores exactos de fabrica, incluido el ``First_Even``
corrupto de Wiegand36a (``1.11111111111111e+34``) y ``SiteCode`` NULL.
"""

from __future__ import annotations

from typing import Dict, List

COLUMNS = [
    "Card_Bit",
    "Format_Name",
    "Card_Format",
    "First_Even",
    "Second_Even",
    "First_Odd",
    "Second_Odd",
    "Format_Type",
    "Status",
    "SiteCode",
]

FACTORY_ROWS: List[Dict] = [
    {"Card_Bit": 26, "Format_Name": 'IntWiegand26', "Card_Format": 'ECCCCCCCCCCCCCCCCCCCCCCCCO', "First_Even": '01111111111110000000000000', "Second_Even": None, "First_Odd": '00000000000001111111111110', "Second_Odd": None, "Format_Type": 2, "Status": 1, "SiteCode": None},
    {"Card_Bit": 26, "Format_Name": 'IntWiegand26a', "Card_Format": 'ESSSSSSSSCCCCCCCCCCCCCCCCO', "First_Even": '01111111111110000000000000', "Second_Even": None, "First_Odd": '00000000000001111111111110', "Second_Odd": None, "Format_Type": 2, "Status": 0, "SiteCode": None},
    {"Card_Bit": 34, "Format_Name": 'IntWiegand34', "Card_Format": 'ECCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCO', "First_Even": '0111111111111111100000000000000000', "Second_Even": None, "First_Odd": '0000000000000000011111111111111110', "Second_Odd": None, "Format_Type": 2, "Status": 0, "SiteCode": None},
    {"Card_Bit": 34, "Format_Name": 'IntWiegand34a', "Card_Format": 'ESSSSSSSSCCCCCCCCCCCCCCCCCCCCCCCCO', "First_Even": '0111111111111111100000000000000000', "Second_Even": None, "First_Odd": '0000000000000000011111111111111110', "Second_Odd": None, "Format_Type": 2, "Status": 0, "SiteCode": None},
    {"Card_Bit": 26, "Format_Name": 'Wiegand26', "Card_Format": 'ECCCCCCCCCCCCCCCCCCCCCCCCO', "First_Even": '01111111111110000000000000', "Second_Even": None, "First_Odd": '00000000000001111111111110', "Second_Odd": None, "Format_Type": 1, "Status": 1, "SiteCode": None},
    {"Card_Bit": 26, "Format_Name": 'Wiegand26', "Card_Format": 'ECCCCCCCCCCCCCCCCCCCCCCCCO', "First_Even": '01111111111110000000000000', "Second_Even": None, "First_Odd": '00000000000001111111111110', "Second_Odd": None, "Format_Type": 3, "Status": 1, "SiteCode": None},
    {"Card_Bit": 26, "Format_Name": 'Wiegand26a', "Card_Format": 'ESSSSSSSSCCCCCCCCCCCCCCCCO', "First_Even": '01111111111110000000000000', "Second_Even": None, "First_Odd": '00000000000001111111111110', "Second_Odd": None, "Format_Type": 1, "Status": 0, "SiteCode": None},
    {"Card_Bit": 26, "Format_Name": 'Wiegand26a', "Card_Format": 'ESSSSSSSSCCCCCCCCCCCCCCCCO', "First_Even": '01111111111110000000000000', "Second_Even": None, "First_Odd": '00000000000001111111111110', "Second_Odd": None, "Format_Type": 3, "Status": 0, "SiteCode": None},
    {"Card_Bit": 34, "Format_Name": 'Wiegand34', "Card_Format": 'ECCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCO', "First_Even": '0111111111111111100000000000000000', "Second_Even": None, "First_Odd": '0000000000000000011111111111111110', "Second_Odd": None, "Format_Type": 1, "Status": 0, "SiteCode": None},
    {"Card_Bit": 34, "Format_Name": 'Wiegand34', "Card_Format": 'ECCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCO', "First_Even": '0111111111111111100000000000000000', "Second_Even": None, "First_Odd": '0000000000000000011111111111111110', "Second_Odd": None, "Format_Type": 3, "Status": 0, "SiteCode": None},
    {"Card_Bit": 34, "Format_Name": 'Wiegand34a', "Card_Format": 'ESSSSSSSSCCCCCCCCCCCCCCCCCCCCCCCCO', "First_Even": '0111111111111111100000000000000000', "Second_Even": None, "First_Odd": '0000000000000000011111111111111110', "Second_Odd": None, "Format_Type": 1, "Status": 0, "SiteCode": None},
    {"Card_Bit": 34, "Format_Name": 'Wiegand34a', "Card_Format": 'ESSSSSSSSCCCCCCCCCCCCCCCCCCCCCCCCO', "First_Even": '0111111111111111100000000000000000', "Second_Even": None, "First_Odd": '0000000000000000011111111111111110', "Second_Odd": None, "Format_Type": 3, "Status": 0, "SiteCode": None},
    {"Card_Bit": 36, "Format_Name": 'Wiegand36', "Card_Format": 'OFFFFFFFFFFFFFFFFCCCCCCCCCCCCCCCCMME', "First_Even": '000000000000000000111111111111111110', "Second_Even": None, "First_Odd": '011111111111111111000000000000000000', "Second_Odd": None, "Format_Type": 1, "Status": 0, "SiteCode": None},
    {"Card_Bit": 36, "Format_Name": 'Wiegand36', "Card_Format": 'OFFFFFFFFFFFFFFFFCCCCCCCCCCCCCCCCMME', "First_Even": '000000000000000000111111111111111110', "Second_Even": None, "First_Odd": '011111111111111111000000000000000000', "Second_Odd": None, "Format_Type": 3, "Status": 0, "SiteCode": None},
    {"Card_Bit": 36, "Format_Name": 'Wiegand36a', "Card_Format": 'EFFFFFFFFFFFFFFFFFFCCCCCCCCCCCCCCCCO', "First_Even": '1.11111111111111e+34', "Second_Even": None, "First_Odd": '000000000000000000111111111111111110', "Second_Odd": None, "Format_Type": 1, "Status": 0, "SiteCode": None},
    {"Card_Bit": 36, "Format_Name": 'Wiegand36a', "Card_Format": 'EFFFFFFFFFFFFFFFFFFCCCCCCCCCCCCCCCCO', "First_Even": '1.11111111111111e+34', "Second_Even": None, "First_Odd": '000000000000000000111111111111111110', "Second_Odd": None, "Format_Type": 3, "Status": 0, "SiteCode": None},
    {"Card_Bit": 37, "Format_Name": 'Wiegand37', "Card_Format": 'OMMMMSSSSSSSSSSSSCCCCCCCCCCCCCCCCCCCE', "First_Even": '0101101101101101101101101101101101100', "Second_Even": None, "First_Odd": '0011011011011011011011011011011011010', "Second_Odd": None, "Format_Type": 1, "Status": 0, "SiteCode": None},
    {"Card_Bit": 37, "Format_Name": 'Wiegand37', "Card_Format": 'OMMMMSSSSSSSSSSSSCCCCCCCCCCCCCCCCCCCE', "First_Even": '0101101101101101101101101101101101100', "Second_Even": None, "First_Odd": '0011011011011011011011011011011011010', "Second_Odd": None, "Format_Type": 3, "Status": 0, "SiteCode": None},
    {"Card_Bit": 37, "Format_Name": 'Wiegand37a', "Card_Format": 'EMMMFFFFFFFFFFSSSSSSCCCCCCCCCCCCCCCCO', "First_Even": '0111111111111111110000000000000000000', "Second_Even": None, "First_Odd": '0000000000000000001111111111111111110', "Second_Odd": None, "Format_Type": 1, "Status": 0, "SiteCode": None},
    {"Card_Bit": 37, "Format_Name": 'Wiegand37a', "Card_Format": 'EMMMFFFFFFFFFFSSSSSSCCCCCCCCCCCCCCCCO', "First_Even": '0111111111111111110000000000000000000', "Second_Even": None, "First_Odd": '0000000000000000001111111111111111110', "Second_Odd": None, "Format_Type": 3, "Status": 0, "SiteCode": None},
    {"Card_Bit": 50, "Format_Name": 'Wiegand50', "Card_Format": 'ECCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCO', "First_Even": '01111111111111111111111110000000000000000000000000', "Second_Even": None, "First_Odd": '00000000000000000000000001111111111111111111111110', "Second_Odd": None, "Format_Type": 1, "Status": 0, "SiteCode": None},
    {"Card_Bit": 50, "Format_Name": 'Wiegand50', "Card_Format": 'ECCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCO', "First_Even": '01111111111111111111111110000000000000000000000000', "Second_Even": None, "First_Odd": '00000000000000000000000001111111111111111111111110', "Second_Odd": None, "Format_Type": 3, "Status": 0, "SiteCode": None},
]

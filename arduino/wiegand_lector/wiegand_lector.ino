/*
  Lector Wiegand -> puerto serie, para formatos-wiegand-custom.

  Captura la trama cruda de un lector de tarjetas Wiegand (D0/D1) y la envia
  por USB-serie a 115200 baudios, una linea por lectura:

      WG <nbits> <bits> HEX=<hex>

  La seccion "Lector Arduino" de la app (app.py) lee esas lineas con Web Serial
  y busca el formato cuyo numero coincide con el impreso en la tarjeta.

  Conexion (lector tipico de 12 V):
      Lector rojo  (+V)  -> fuente del lector (12 V o 5 V segun modelo)
      Lector negro (GND) -> GND de la fuente  Y  GND del Arduino (comun!)
      Lector verde (D0)  -> pin 2
      Lector blanco(D1)  -> pin 3
  Uno / Nano / Mega: D0/D1 son de 5 V, se conectan directo.
  ESP32 / placas de 3,3 V: usar divisor resistivo o conversor de nivel en D0/D1.

  Lineas que empiezan con '#' son informativas (la app las ignora).
*/

#if defined(ESP32) || defined(ESP8266)
  #define WG_ISR_ATTR IRAM_ATTR
#else
  #define WG_ISR_ATTR
#endif

// Pines con interrupcion externa (Uno/Nano: 2 y 3).
const uint8_t PIN_D0 = 2;
const uint8_t PIN_D1 = 3;

const uint8_t MAX_BITS = 128;            // tramas de hasta 128 bits
const unsigned long FRAME_GAP_MS = 30;   // silencio que marca el fin de una trama

volatile uint8_t wgBits[MAX_BITS];
volatile uint8_t wgCount = 0;
volatile bool wgOverflow = false;
volatile unsigned long wgLastPulse = 0;

void WG_ISR_ATTR onD0() {
  if (wgCount < MAX_BITS) wgBits[wgCount++] = 0; else wgOverflow = true;
  wgLastPulse = millis();
}

void WG_ISR_ATTR onD1() {
  if (wgCount < MAX_BITS) wgBits[wgCount++] = 1; else wgOverflow = true;
  wgLastPulse = millis();
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_D0, INPUT_PULLUP);
  pinMode(PIN_D1, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(PIN_D0), onD0, FALLING);
  attachInterrupt(digitalPinToInterrupt(PIN_D1), onD1, FALLING);
  Serial.println(F("# LECTOR WIEGAND listo (D0=pin 2, D1=pin 3, 115200)"));
}

// Imprime los bits como hexadecimal, MSB primero (rellena con ceros a la izquierda).
void printHex(const uint8_t *b, uint8_t n) {
  uint8_t pad = (4 - (n % 4)) % 4;
  uint8_t nib = 0, k = 0;
  for (uint8_t i = 0; i < pad + n; i++) {
    uint8_t bit = (i < pad) ? 0 : b[i - pad];
    nib = (nib << 1) | bit;
    if (++k == 4) {
      Serial.print(nib, HEX);
      nib = 0; k = 0;
    }
  }
}

// Ayuda rapida: si son 26 bits, muestra la lectura como Wiegand26 estandar.
void printW26(const uint8_t *b) {
  unsigned long site = 0, card = 0;
  uint8_t evenOnes = 0, oddOnes = 0;
  for (uint8_t i = 1; i <= 8; i++) site = (site << 1) | b[i];
  for (uint8_t i = 9; i <= 24; i++) card = (card << 1) | b[i];
  for (uint8_t i = 1; i <= 12; i++) evenOnes += b[i];
  for (uint8_t i = 13; i <= 24; i++) oddOnes += b[i];
  bool ok = ((evenOnes + b[0]) % 2 == 0) && ((oddOnes + b[25]) % 2 == 1);
  Serial.print(F("# como W26: site="));
  Serial.print(site);
  Serial.print(F(" card="));
  Serial.print(card);
  Serial.print(F(" paridad="));
  Serial.println(ok ? F("OK") : F("FALLA"));
}

void loop() {
  uint8_t frame[MAX_BITS];
  uint8_t n = 0;
  bool overflow = false;

  noInterrupts();
  if (wgCount > 0 && (millis() - wgLastPulse) > FRAME_GAP_MS) {
    n = wgCount;
    for (uint8_t i = 0; i < n; i++) frame[i] = wgBits[i];
    overflow = wgOverflow;
    wgCount = 0;
    wgOverflow = false;
  }
  interrupts();

  if (n == 0) return;

  Serial.print(F("WG "));
  Serial.print(n);
  Serial.print(' ');
  for (uint8_t i = 0; i < n; i++) Serial.print(frame[i] ? '1' : '0');
  Serial.print(F(" HEX="));
  printHex(frame, n);
  Serial.println();
  if (overflow) Serial.println(F("# AVISO: trama de mas de 128 bits, se trunco"));
  if (n == 26) printW26(frame);
}

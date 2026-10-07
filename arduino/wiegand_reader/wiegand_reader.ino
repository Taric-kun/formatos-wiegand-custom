/*
 * wiegand_reader.ino — Lector Wiegand para identificar formatos de tarjetas.
 *
 * Lee la trama Wiegand cruda de un lector de tarjetas (lineas D0/D1) y la
 * imprime por el puerto serie para que la herramienta web la identifique.
 *
 * Por cada tarjeta leida imprime una linea:
 *   WIEGAND bits=<n> hex=0x<...> bin=<0101...>
 * (bin va MSB primero: el primer bit que manda el lector es el mas significativo)
 *
 * --- Conexiones (Arduino Uno / Nano) ---
 *   Lector D0 (verde)  -> pin 2  (INT0)
 *   Lector D1 (blanco) -> pin 3  (INT1)
 *   Lector GND         -> GND    (comun con el Arduino)
 *   Lector V+          -> su fuente (normalmente 12V EXTERNA; NO al 5V del Arduino)
 *   GND del lector y del Arduino DEBEN ir unidos.
 *
 * La mayoria de lectores Wiegand son de colector abierto: las lineas estan en
 * alto en reposo y bajan a 0 por cada bit. Usamos INPUT_PULLUP y flanco de
 * bajada. Soporta tramas de hasta 64 bits (26/34/37, etc.).
 *
 * Nota: en placas distintas a Uno/Nano cambia los pines de interrupcion.
 */

#define PIN_D0 2
#define PIN_D1 3
#define MAX_BITS 64
#define TIMEOUT_MS 25   // fin de trama tras este silencio entre bits

volatile unsigned long long wiegandValue = 0;
volatile unsigned int bitCount = 0;
volatile unsigned long lastBitMs = 0;

void onD0() {              // un 0 recibido
  wiegandValue <<= 1;
  if (bitCount < MAX_BITS) bitCount++;
  lastBitMs = millis();
}

void onD1() {              // un 1 recibido
  wiegandValue = (wiegandValue << 1) | 1ULL;
  if (bitCount < MAX_BITS) bitCount++;
  lastBitMs = millis();
}

void setup() {
  Serial.begin(9600);
  pinMode(PIN_D0, INPUT_PULLUP);
  pinMode(PIN_D1, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(PIN_D0), onD0, FALLING);
  attachInterrupt(digitalPinToInterrupt(PIN_D1), onD1, FALLING);
  Serial.println(F("# Lector Wiegand listo. Pasa una tarjeta..."));
}

void printFrame(unsigned long long value, unsigned int nbits) {
  // bin MSB primero
  char bin[MAX_BITS + 1];
  for (unsigned int i = 0; i < nbits; i++) {
    bin[i] = ((value >> (nbits - 1 - i)) & 1ULL) ? '1' : '0';
  }
  bin[nbits] = '\0';

  Serial.print(F("WIEGAND bits="));
  Serial.print(nbits);
  Serial.print(F(" hex=0x"));
  // imprime el hex de un unsigned long long (Serial no soporta 64 bits directo)
  unsigned long hi = (unsigned long)(value >> 32);
  unsigned long lo = (unsigned long)(value & 0xFFFFFFFFULL);
  if (hi) {
    Serial.print(hi, HEX);
    char buf[9];
    snprintf(buf, sizeof(buf), "%08lX", lo);
    Serial.print(buf);
  } else {
    Serial.print(lo, HEX);
  }
  Serial.print(F(" bin="));
  Serial.println(bin);
}

void loop() {
  // Si hubo bits y ya paso el timeout sin mas pulsos, la trama termino.
  if (bitCount > 0 && (millis() - lastBitMs) > TIMEOUT_MS) {
    noInterrupts();
    unsigned long long value = wiegandValue;
    unsigned int nbits = bitCount;
    wiegandValue = 0;
    bitCount = 0;
    interrupts();

    if (nbits >= 4) {       // ignora ruido de pocos pulsos
      printFrame(value, nbits);
    }
  }
}

#include <OneWire.h>
#include <DallasTemperature.h>

// Data wire is connected to digital pin 4 (make sure this matches your wiring)
#define ONE_WIRE_BUS 4

OneWire oneWire(ONE_WIRE_BUS);
DallasTemperature sensors(&oneWire);

// Cross-version compatibility: some DallasTemperature versions don't define *_C
#ifndef DEVICE_DISCONNECTED_C
  #define DEVICE_DISCONNECTED_C DEVICE_DISCONNECTED
#endif

void setup() {
  Serial.begin(9600);
  // For native-USB boards only (e.g., Leonardo/Micro). Harmless elsewhere.
  while (!Serial) { ; }

  Serial.println(F("Dallas Temperature Sensor Test"));
  sensors.begin();
}

void loop() {
  sensors.requestTemperatures();              // trigger conversion for all devices
  float tempC = sensors.getTempCByIndex(0);   // read first device on the bus

  if (tempC == DEVICE_DISCONNECTED_C) {
    Serial.println(F("Error: Could not read temperature data (disconnected/no device)."));
  } else {
    Serial.print(F("Temperature: "));
    Serial.print(tempC, 2);
    Serial.println(F(" °C"));
  }

  delay(1000);
}

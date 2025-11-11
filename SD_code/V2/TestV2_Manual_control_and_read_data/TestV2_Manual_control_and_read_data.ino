#include <DallasTemperature.h>
#include <OneWire.h>
#include <HX711.h>

int motor = 10;
int lin_pot_pin = A5;
int Tcouple_pin = 4;

unsigned long currentMillis = 0;

// Load cell setup
HX711 scale;
int loadcell_data_pin = 3;
int loadcell_clock_pin = 2;
float calibration_factor = -7050.5;

// Thermocouple setup
// OneWire oneWire(Tcouple_pin);
// DallasTemperature sensors(&oneWire);

// Timing for slower sensors
// unsigned long lastTempMillis = 0; //timing for thermo
unsigned long lastPotMillis = 0;
// const unsigned long tempInterval = 100;  // ms between temperature reads
const unsigned long potInterval = 1;    // ms between linear pot reads

// ⚠️ Optional sensors — commented out
//  float currentTemp = 0;
 int currentPot = 0;

// end of optional sensors
void setup() {
  Serial.begin(115200); // match Python baud rate
  scale.begin(loadcell_data_pin, loadcell_clock_pin);
  scale.set_scale(calibration_factor);
  scale.tare();

  // ⚠️ Optional sensors — commented out
  // sensors.begin();
  //end of optional sensors
}

void loop() {
  currentMillis = millis();

  // ⚠️ Optional sensors — commented out
  
  // if (currentMillis - lastTempMillis >= tempInterval) {
  //   sensors.requestTemperatures();
  //   currentTemp = sensors.getTempCByIndex(0);
  //   lastTempMillis = currentMillis;
  // }

  if (currentMillis - lastPotMillis >= potInterval) {
    currentPot = analogRead(lin_pot_pin);
    lastPotMillis = currentMillis;
  }
  
// End of optional sensors
  collect_data();
  run_motor();
}

void collect_data() {
  Serial.write(0xAA); // sync byte

  // Timestamp
  Serial.print(currentMillis);
  Serial.print(",");

  // Load cell
  Serial.print(scale.get_units(), 2);

  // ⚠️ Optional sensors — commented out
  
  Serial.print(",");
  Serial.print(currentPot);

  // Serial.print(",");
  // Serial.print(currentTemp, 2);
  
// End of optional sensors

  Serial.print("\n"); // ensures top-to-bottom CSV
}

void run_motor() {
  if (Serial.available() > 0) {
    char dutyCycle = Serial.read();
    int pwm = 0;

    switch (dutyCycle) {
      case '0': pwm = 0; break;
      case '1': pwm = 106; break;
      case '2': pwm = 124; break;
      case '3': pwm = 142; break;
      case '4': pwm = 160; break;
      case '5': pwm = 178; break;
      case '6': pwm = 196; break;
      case '7': pwm = 214; break;
      case '8': pwm = 232; break;
      case '9': pwm = 255; break;
    }

    analogWrite(motor, pwm);
  }
}

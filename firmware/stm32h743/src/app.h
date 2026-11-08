#pragma once

#include <stdint.h>

// State owned by main.cpp that the console also needs.
bool app_warningsOn();
void app_setWarnings(bool on);
bool app_alarmOn();
void app_startAlarm();
void app_stopAlarm();
bool app_voiceAvailable();
void app_scan();
bool app_batteryVolts(float &volts);
// -1 when the find menu is closed, otherwise the object it is on.
int app_menuItem();

#pragma once

#include <stdint.h>

#include "obstacle_policy.h"
#include "vision.h"

// What the device says, composed from recorded prompts. Every sentence here
// reports an observation with its limit ("nothing detected; sensing range
// about one metre"). None of them may tell the user that a way is safe or
// clear: the sensor sees a 27-degree cone and nothing at the user's feet.
namespace announce {

void obstacleAlert(const obstacle::Alert &a);
void scanReport(uint32_t nowMs);
void boot(bool restartedByWatchdog);
void sensorEvent(uint8_t tofEvent);
void languageChanged();
void warningsChanged(bool on);
void help(bool voiceAvailable);
void alarmOn();
void alarmOff();
void batteryLow();
void battery(bool known, bool low);
void notUnderstood();
void listening();

// Camera. Objects are reported with the direction the camera saw them in;
// a distance is added only for an object inside the ToF cone, because the
// laser's reading belongs to whatever it hit, not to what the camera saw.
void describe(const vision::Detection *d, int n, uint32_t nowMs);
void searchStarted(uint8_t object);
void searchGuidance(uint8_t object, int side, bool haveDistance, uint16_t mm);
void searchNotFound(uint8_t object);
void searchStopped();
void findMenu(uint8_t object, bool first);
void cameraFault();
void visionNotInstalled();

}  // namespace announce

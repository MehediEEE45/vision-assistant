#pragma once

#include <Arduino.h>

// WeAct MiniSTM32H743VITx.
//
// Already taken on the board, and avoided below so the camera, LCD, both
// flash chips and the microSD slot all stay usable later:
//   QSPI flash  PB2 PB6 PD11 PD12 PD13 PE2
//   SPI flash   PB3 PB4 PD6 PD7
//   LCD         PE10 PE11 PE12 PE13 PE14 PE15
//   microSD     PC8 PC9 PC10 PC11 PC12 PD2, detect PD4
//   camera      PA4 PA6 PA7 PA8 PB7 PB8 PB9 PC6 PC7 PD3 PE0 PE1 PE4 PE5 PE6
//   USB         PA11 PA12          LED PE3          key K1 PC13

// I2S2 in full duplex (AF5): one clock pair drives both audio chips, so the
// microphone and the amplifier can never drift apart in sample rate.
#define PIN_I2S_WS PB12   // INMP441 WS   + MAX98357A LRC
#define PIN_I2S_CK PB13   // INMP441 SCK  + MAX98357A BCLK
#define PIN_I2S_SDI PB14  // INMP441 SD   (into the MCU)
#define PIN_I2S_SDO PB15  // MAX98357A DIN (out of the MCU)

// I2C2, the board's default Wire bus.
#define PIN_I2C_SCL PB10
#define PIN_I2C_SDA PB11

// Optional. Wired, it lets the firmware hard-reset a hung sensor.
#define PIN_TOF_XSHUT PD14

// Coin vibration motors, each through an NPN transistor with a flyback diode.
#define PIN_MOTOR_LEFT PA0   // TIM2_CH1
#define PIN_MOTOR_RIGHT PA1  // TIM2_CH2

// K1 on the board is hard to find by touch. The external button is the one a
// user actually presses: a large tactile switch from PD10 to GND.
#define PIN_BUTTON_BOARD PC13  // active high
#define PIN_BUTTON_EXT PD10    // active low, internal pull-up

#define PIN_LED PE3

#define PIN_BATTERY_SENSE PC0

// OV5640 on the board's DVP connector (WeAct connector map). DCMI data and
// sync pins are configured in camera.cpp: HSYNC PA4, PIXCLK PA6, VSYNC PB7,
// D0 PC6, D1 PC7, D2 PE0, D3 PE1, D4 PE4, D5 PD3, D6 PE5, D7 PE6 (all AF13).
#define PIN_CAM_SCL PB8   // I2C1, the sensor's SCCB port
#define PIN_CAM_SDA PB9
#define PIN_CAM_PWDN PA7  // polarity differs between modules; see camera.cpp
#define PIN_CAM_XCLK PA8  // MCO1

// The board's 0.96" ST7735 LCD on SPI4 (SCK PE12, MOSI PE14, AF5).
#define PIN_LCD_CS PE11
#define PIN_LCD_DC PE13
#define PIN_LCD_RST PE15
#define PIN_LCD_BL PE10
// The backlight lights when PE10 is LOW (Zephyr's board file marks it
// active-low); driven HIGH the panel works but stays dark.
#define LCD_BL_ON LOW
#define LCD_BL_OFF HIGH

#include <Arduino.h>


#include "clock_config.h"


namespace {

// The "reboot into DFU" request survives the reset in an RTC backup register:
// a software reset leaves the backup domain alone, and unlike SRAM it has no
// ECC, so reading it after a cold power-up cannot fault.
constexpr uint32_t kBootloaderMagic = 0xB007DF00u;
// STM32H74x/75x system-memory boot loader (AN2606).
constexpr uint32_t kSystemMemory = 0x1FF09800u;

void enterBootloaderIfRequested()
{
  __HAL_RCC_RTC_CLK_ENABLE();
  if (RTC->BKP0R != kBootloaderMagic) return;
  HAL_PWR_EnableBkUpAccess();
  RTC->BKP0R = 0;

  // This runs before the clock tree, USB or any peripheral is set up, so only
  // what HAL_Init and the core's start-up did needs undoing: SysTick, pending
  // interrupts and the caches the boot loader does not expect.
  __disable_irq();
  SysTick->CTRL = 0;
  SysTick->LOAD = 0;
  SysTick->VAL = 0;
  for (uint32_t i = 0; i < 8; ++i) {
    NVIC->ICER[i] = 0xFFFFFFFFu;
    NVIC->ICPR[i] = 0xFFFFFFFFu;
  }
  SCB_DisableICache();
  SCB_DisableDCache();
  __enable_irq();
  __set_MSP(*(volatile uint32_t *)kSystemMemory);
  ((void (*)(void))(*(volatile uint32_t *)(kSystemMemory + 4)))();
  for (;;) {}
}

}  // namespace

void requestBootloader()
{
  __HAL_RCC_RTC_CLK_ENABLE();
  HAL_PWR_EnableBkUpAccess();
  RTC->BKP0R = kBootloaderMagic;
  __DSB();
  NVIC_SystemReset();
}

// Replaces the board package's weak SystemClock_Config, which selects VOS0 and
// 480 MHz unconditionally. That is out of specification on revision Y silicon,
// and clone boards ship both revisions.
//
// The PLL2/PLL3 settings are the board package's own, so every peripheral
// kernel clock (I2S 80 MHz, I2C 80 MHz, USB 48 MHz) is unchanged.
extern "C" void SystemClock_Config(void)
{
  enterBootloaderIfRequested();

  RCC_OscInitTypeDef osc = {};
  RCC_ClkInitTypeDef clk = {};
  RCC_PeriphCLKInitTypeDef periph = {};

  HAL_PWREx_ConfigSupply(PWR_LDO_SUPPLY);
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);
  while (!__HAL_PWR_GET_FLAG(PWR_FLAG_VOSRDY)) {}

  // 25 MHz HSE / 5 = 5 MHz reference, x96 = 480 MHz VCO.
  osc.OscillatorType = RCC_OSCILLATORTYPE_HSE;
  osc.HSEState = RCC_HSE_ON;
  osc.PLL.PLLState = RCC_PLL_ON;
  osc.PLL.PLLSource = RCC_PLLSOURCE_HSE;
  osc.PLL.PLLM = 5;
  osc.PLL.PLLN = 96;
  osc.PLL.PLLP = 2;   // 240 MHz core
  osc.PLL.PLLQ = 10;  // 48 MHz: USB, QSPI, SDMMC
  osc.PLL.PLLR = 10;
  osc.PLL.PLLRGE = RCC_PLL1VCIRANGE_2;
  osc.PLL.PLLVCOSEL = RCC_PLL1VCOWIDE;
  osc.PLL.PLLFRACN = 0;
  if (HAL_RCC_OscConfig(&osc) != HAL_OK) {
    Error_Handler();
  }

  clk.ClockType = RCC_CLOCKTYPE_HCLK | RCC_CLOCKTYPE_SYSCLK | RCC_CLOCKTYPE_PCLK1 |
                  RCC_CLOCKTYPE_PCLK2 | RCC_CLOCKTYPE_D3PCLK1 | RCC_CLOCKTYPE_D1PCLK1;
  clk.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  clk.SYSCLKDivider = RCC_SYSCLK_DIV1;
  clk.AHBCLKDivider = RCC_HCLK_DIV2;   // 120 MHz
  clk.APB3CLKDivider = RCC_APB3_DIV2;  // 60 MHz
  clk.APB1CLKDivider = RCC_APB1_DIV2;
  clk.APB2CLKDivider = RCC_APB2_DIV2;
  clk.APB4CLKDivider = RCC_APB4_DIV2;
  // 120 MHz AXI at VOS1 needs one wait state; two leaves margin.
  if (HAL_RCC_ClockConfig(&clk, FLASH_LATENCY_2) != HAL_OK) {
    Error_Handler();
  }

  periph.PeriphClockSelection = RCC_PERIPHCLK_USB | RCC_PERIPHCLK_QSPI | RCC_PERIPHCLK_SDMMC |
                                RCC_PERIPHCLK_ADC | RCC_PERIPHCLK_LPUART1 | RCC_PERIPHCLK_USART16 |
                                RCC_PERIPHCLK_USART234578 | RCC_PERIPHCLK_I2C123 |
                                RCC_PERIPHCLK_I2C4 | RCC_PERIPHCLK_SPI123 | RCC_PERIPHCLK_SPI45 |
                                RCC_PERIPHCLK_SPI6;
  // 25 / 15 * 96 / 2 = 80 MHz on every PLL2 and PLL3 output.
  periph.PLL2.PLL2M = 15;
  periph.PLL2.PLL2N = 96;
  periph.PLL2.PLL2P = 2;
  periph.PLL2.PLL2Q = 2;
  periph.PLL2.PLL2R = 2;
  periph.PLL2.PLL2RGE = RCC_PLL2VCIRANGE_0;
  periph.PLL2.PLL2VCOSEL = RCC_PLL2VCOMEDIUM;
  periph.PLL2.PLL2FRACN = 0;
  periph.PLL3.PLL3M = 15;
  periph.PLL3.PLL3N = 96;
  periph.PLL3.PLL3P = 2;
  periph.PLL3.PLL3Q = 2;
  periph.PLL3.PLL3R = 2;
  periph.PLL3.PLL3RGE = RCC_PLL3VCIRANGE_0;
  periph.PLL3.PLL3VCOSEL = RCC_PLL3VCOMEDIUM;
  periph.PLL3.PLL3FRACN = 0;
  periph.AdcClockSelection = RCC_ADCCLKSOURCE_PLL2;
  periph.UsbClockSelection = RCC_USBCLKSOURCE_PLL;
  periph.QspiClockSelection = RCC_QSPICLKSOURCE_PLL;
  periph.SdmmcClockSelection = RCC_SDMMCCLKSOURCE_PLL;
  periph.Lpuart1ClockSelection = RCC_LPUART1CLKSOURCE_PLL2;
  periph.Usart16ClockSelection = RCC_USART16CLKSOURCE_PLL2;
  periph.Usart234578ClockSelection = RCC_USART234578CLKSOURCE_PLL2;
  periph.I2c123ClockSelection = RCC_I2C123CLKSOURCE_PLL3;
  periph.I2c4ClockSelection = RCC_I2C4CLKSOURCE_PLL3;
  periph.Spi123ClockSelection = RCC_SPI123CLKSOURCE_PLL2;  // I2S2 kernel clock
  periph.Spi45ClockSelection = RCC_SPI45CLKSOURCE_PLL2;
  periph.Spi6ClockSelection = RCC_SPI6CLKSOURCE_PLL2;
  if (HAL_RCCEx_PeriphCLKConfig(&periph) != HAL_OK) {
    Error_Handler();
  }
}

uint16_t chipRevisionId()
{
  return (uint16_t)((DBGMCU->IDCODE >> 16) & 0xFFFFu);
}

const char *chipRevisionName()
{
  // REV_ID values from errata sheet ES0392.
  switch (chipRevisionId()) {
    case 0x1003: return "Y (max 400 MHz)";
    case 0x2003: return "V (max 480 MHz)";
    default: return "unknown";
  }
}

#include <Arduino.h>

// Use the internal HSI16 oscillator; the board's external crystal is unverified.
extern "C" void SystemClock_Config(void) {
  RCC_OscInitTypeDef oscillator{};
  oscillator.OscillatorType = RCC_OSCILLATORTYPE_HSI;
  oscillator.HSIState = RCC_HSI_ON;
  oscillator.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
#if defined(USBCON)
  oscillator.OscillatorType |= RCC_OSCILLATORTYPE_HSI48;
  oscillator.HSI48State = RCC_HSI48_ON;
#endif
  oscillator.PLL.PLLState = RCC_PLL_NONE;
  if (HAL_RCC_OscConfig(&oscillator) != HAL_OK) {
    Error_Handler();
  }
  RCC_ClkInitTypeDef clocks{};
  clocks.ClockType = RCC_CLOCKTYPE_SYSCLK | RCC_CLOCKTYPE_HCLK |
                     RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2;
  clocks.SYSCLKSource = RCC_SYSCLKSOURCE_HSI;
  clocks.AHBCLKDivider = RCC_SYSCLK_DIV1;
  clocks.APB1CLKDivider = RCC_HCLK_DIV1;
  clocks.APB2CLKDivider = RCC_HCLK_DIV1;
  if (HAL_RCC_ClockConfig(&clocks, FLASH_LATENCY_0) != HAL_OK) {
    Error_Handler();
  }
#if defined(USBCON)
  RCC_PeriphCLKInitTypeDef peripherals{};
  peripherals.PeriphClockSelection = RCC_PERIPHCLK_USB;
  peripherals.UsbClockSelection = RCC_USBCLKSOURCE_HSI48;
  if (HAL_RCCEx_PeriphCLKConfig(&peripherals) != HAL_OK) {
    Error_Handler();
  }
  // Trim HSI48 against USB SOF packets; no external crystal required.
  __HAL_RCC_CRS_CLK_ENABLE();
  RCC_CRSInitTypeDef synchronization{};
  synchronization.Prescaler = RCC_CRS_SYNC_DIV1;
  synchronization.Source = RCC_CRS_SYNC_SOURCE_USB;
  synchronization.Polarity = RCC_CRS_SYNC_POLARITY_RISING;
  synchronization.ReloadValue = __HAL_RCC_CRS_RELOADVALUE_CALCULATE(48000000, 1000);
  synchronization.ErrorLimitValue = RCC_CRS_ERRORLIMIT_DEFAULT;
  synchronization.HSI48CalibrationValue = RCC_CRS_HSI48CALIBRATION_DEFAULT;
  HAL_RCCEx_CRSConfig(&synchronization);
#endif
}

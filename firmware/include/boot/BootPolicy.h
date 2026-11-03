// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <stdint.h>

// ESP8266 reset reasons 1/2/3 are hardware watchdog, exception and software
// watchdog. Power-on (0), deliberate restart (4), sleep (5) and reset pin (6)
// must not accumulate as a firmware boot loop.
constexpr uint32_t nextBootFailureCount(uint32_t previous, uint32_t reason, uint32_t threshold) {
    return (reason == 1 || reason == 2 || reason == 3)
        ? (previous < threshold ? previous + 1 : threshold) : 0;
}

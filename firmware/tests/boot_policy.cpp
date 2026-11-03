#include "boot/BootPolicy.h"
constexpr uint32_t LIMIT = 3;
static_assert(nextBootFailureCount(2, 0, LIMIT) == 0, "Power cycling is not a crash");
static_assert(nextBootFailureCount(2, 4, LIMIT) == 0, "API reboot must not open rescue setup");
static_assert(nextBootFailureCount(2, 6, LIMIT) == 0, "Reset pin must retain normal boot");
static_assert(nextBootFailureCount(nextBootFailureCount(nextBootFailureCount(0, 4, LIMIT), 4, LIMIT), 4, LIMIT) == 0,
              "Three deliberate reboots must never enter rescue");
static_assert(nextBootFailureCount(nextBootFailureCount(nextBootFailureCount(0, 3, LIMIT), 2, LIMIT), 1, LIMIT) == LIMIT,
              "Repeated real faults retain emergency recovery");
static_assert(nextBootFailureCount(0xFFFFFFFFu, 1, LIMIT) == LIMIT, "Counter must not overflow");

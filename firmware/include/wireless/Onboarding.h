// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <Arduino.h>

namespace Onboarding {
constexpr const char* SSID = "GeekMagic";
constexpr const char* PASSWORD = "$str0ngPa$$w0rd";
constexpr const char* URL = "http://192.168.4.1/setup";
String wifiPayload();
void draw(bool openPage = false);
}

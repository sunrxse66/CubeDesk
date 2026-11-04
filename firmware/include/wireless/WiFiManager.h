// SPDX-License-Identifier: GPL-3.0-or-later
/*
 * GeekMagic Open Firmware
 * Copyright (C) 2026 Times-Z
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <https://www.gnu.org/licenses/>.
 */

#ifndef WIFI_MANAGER_H
#define WIFI_MANAGER_H

#include <ESP8266WiFi.h>
#include <Arduino.h>
#include <ArduinoJson.h>
#include <DNSServer.h>

class WiFiManager {
   public:
    WiFiManager(const char* staSsid, const char* staPass, const char* apSsid, const char* apPass);
    void begin();
    void loop();
    bool startStationMode();
    bool startAccessPointMode();
    bool isApMode() const;
    bool isSetupClient(IPAddress localIp) const;
    IPAddress getIP() const;
    static void scanNetworks(JsonArray& out);
    bool connectToNetwork(const char* ssid, const char* pass, uint32_t timeoutMs = 10000);
    static bool isConnected();
    static String getConnectedSSID();
    bool takeServiceChange();
    bool servicesReady() const;
    void keepUnconfiguredAccessPoint();
    void addStatus(JsonObject result) const;
    void showStatus();

   private:
    String _staSsid;
    String _staPass;
    const char* _apSsid;
    const char* _apPass;
    bool _apActive = false;
    bool _hadLink = false;
    bool _linkEvent = false;
    bool _servicesDirty = false;
    uint32_t _servicesAt = 0;
    uint32_t _apShutdownAt = 0;
    uint32_t _offlineSince = 0;
    uint32_t _nextAttemptAt = 0;
    uint32_t _attempts = 0;
    uint32_t _fallbackCount = 0;
    uint8_t _lastDisconnectReason = 0;
    WiFiEventHandler _disconnectedHandler;
    WiFiEventHandler _gotIpHandler;
    DNSServer _dns;
    uint32_t _phoneJoinedAt = 0;
    bool _pageQrShown = false;
    bool _setupRetryPaused = false;
    uint32_t _resumeAfterSetupAt = 0;
    uint32_t _setupPauseUntil = 0;
    uint32_t _setupPauseAllowedAt = 0;
    uint8_t _lastStationFailureReason = 0;
    bool _recoveryScanActive = false;
    uint32_t _recoveryScanDeadline = 0;
    void connectStation(int32_t channel = 0, const uint8_t* bssid = nullptr);
    void finishRecoveryScan();
    void enterUnconfiguredMode();
    void pauseStationForSetup();
};

#endif  // WIFI_MANAGER_H

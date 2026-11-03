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

#include <ArduinoJson.h>
#include <Logger.h>

#include "wireless/WiFiManager.h"
#include "display/DisplayManager.h"
#include "wireless/Onboarding.h"

#include "project_version.h"
#include <algorithm>

namespace {
constexpr uint32_t RETRY_MS = 30000;
constexpr uint32_t OPTIONAL_AP_AFTER_MS = 120000;
bool due(uint32_t now, uint32_t deadline) { return int32_t(now - deadline) >= 0; }
bool online() { return WiFi.status() == WL_CONNECTED && WiFi.localIP() != IPAddress(0, 0, 0, 0); }
}

WiFiManager::WiFiManager(const char* ssid, const char* pass, const char* apSsid, const char* apPass)
    : _staSsid(ssid), _staPass(pass), _apSsid(apSsid), _apPass(apPass) {}

void WiFiManager::begin() {
    WiFi.persistent(false);  // Retries must not erase/write flash credentials.
    _disconnectedHandler = WiFi.onStationModeDisconnected([this](const WiFiEventStationModeDisconnected& event) {
        _lastDisconnectReason = event.reason;
        _linkEvent = true;
    });
    _gotIpHandler = WiFi.onStationModeGotIP([this](const WiFiEventStationModeGotIP&) { _linkEvent = true; });
    _offlineSince = millis();
    if (_staSsid.length()) startStationMode();
    else startAccessPointMode();
}

bool WiFiManager::startStationMode() {
    if (!_staSsid.length()) return false;
    WiFi.mode(_apActive ? WIFI_AP_STA : WIFI_STA);
    WiFi.setSleepMode(WIFI_NONE_SLEEP);
    WiFi.setAutoReconnect(true);
    WiFi.hostname(String("geekmagic-") + String(ESP.getChipId(), HEX));
    WiFi.begin(_staSsid.c_str(), _staPass.c_str());
    ++_attempts;
    _nextAttemptAt = millis() + RETRY_MS;
    return online();  // No blocking wait: services and watchdog keep running.
}

void WiFiManager::showStatus() {
    if (_apActive && !online()) {
        Onboarding::draw(_pageQrShown);
        return;
    }
    DisplayManager::clearScreen();
    DisplayManager::drawTextWrapped(10, 10, PROJECT_VER_STR, 2, LCD_WHITE, LCD_BLACK, false);
    if (online()) {
        DisplayManager::drawTextWrapped(10, 70, "HOME WI-FI READY", 2, LCD_GREEN, LCD_BLACK, false);
        DisplayManager::drawTextWrapped(10, 110, "IP: " + WiFi.localIP().toString(), 2, LCD_WHITE, LCD_BLACK, false);
    } else if (_staSsid.length()) {
        DisplayManager::drawTextWrapped(10, 65, "HOME WI-FI WAITING", 2, LCD_WHITE, LCD_BLACK, false);
        DisplayManager::drawTextWrapped(10, 110, "Settings saved.\nRetrying automatically", 2, LCD_GREEN, LCD_BLACK, false);
        if (_apActive) DisplayManager::drawTextWrapped(10, 190, "Optional setup AP:\n192.168.4.1", 1, LCD_WHITE, LCD_BLACK, false);
    } else {
        DisplayManager::drawTextWrapped(10, 65, "Wi-Fi setup needed", 2, LCD_WHITE, LCD_BLACK, false);
        DisplayManager::drawTextWrapped(10, 110, "AP: GeekMagic\nIP: 192.168.4.1", 2, LCD_GREEN, LCD_BLACK, false);
    }
}

void WiFiManager::loop() {
    const uint32_t now = millis();
    if (_apActive) {
        _dns.processNextRequest();
        if (!online()) {
            if (WiFi.softAPgetStationNum()) {
                if (!_phoneJoinedAt) _phoneJoinedAt = now;
                if (!_pageQrShown && now - _phoneJoinedAt >= 8000) {
                    _pageQrShown = true;
                    Onboarding::draw(true);
                }
            } else if (_phoneJoinedAt) {
                _phoneJoinedAt = 0;
                _pageQrShown = false;
                Onboarding::draw();
            }
        }
    }
    if (_testDropAt && due(now, _testDropAt)) {
        _testDropAt = 0;
        _testResumeAt = now + _testOfflineMs;
        WiFi.setAutoReconnect(false);
        WiFi.disconnect(false, false);  // Explicitly preserve credentials.
    }
    if (_testResumeAt && due(now, _testResumeAt)) {
        _testResumeAt = 0;
        startStationMode();
    }
    const bool connected = online();
    if (_linkEvent || connected != _hadLink) {
        _linkEvent = false;
        _servicesDirty = true;
        _servicesAt = now + 250;  // Allow a provisioning response to leave the AP.
    }
    if (connected && !_hadLink) {
        _hadLink = true;
        _nextAttemptAt = now + RETRY_MS;
        if (_apActive) _apShutdownAt = now + 30000;
        showStatus();
        Logger::warn("Home Wi-Fi restored; restarting listeners", "WiFiManager");
    } else if (!connected && _hadLink) {
        _hadLink = false;
        _offlineSince = now;
        _nextAttemptAt = now + RETRY_MS;
        _apShutdownAt = 0;
        showStatus();
        Logger::warn("Home Wi-Fi disconnected; saved settings retained", "WiFiManager");
    }
    if (!connected && !_testResumeAt && _staSsid.length()) {
        if (!_apActive && now - _offlineSince >= OPTIONAL_AP_AFTER_MS) {
            // Optional escape hatch for a changed router, not a credential reset.
            ++_fallbackCount;
            startAccessPointMode();
            showStatus();
        }
        if (due(now, _nextAttemptAt)) startStationMode();
    }
    if (_apShutdownAt && due(now, _apShutdownAt) && connected) {
        _apShutdownAt = 0;
        _apActive = false;
        _dns.stop();
        WiFi.softAPdisconnect(false);
        WiFi.mode(WIFI_STA);
        _servicesDirty = true;
        _servicesAt = now + 250;
    }
}

bool WiFiManager::startAccessPointMode() {
    _apActive = true;
    WiFi.mode(_staSsid.length() ? WIFI_AP_STA : WIFI_AP);
    WiFi.setSleepMode(WIFI_NONE_SLEEP);
    WiFi.softAP(_apSsid, _apPass);
    _dns.setErrorReplyCode(DNSReplyCode::NoError);
    _dns.start(53, "*", WiFi.softAPIP());
    _phoneJoinedAt = 0;
    _pageQrShown = false;
    _servicesDirty = true;
    _servicesAt = millis() + 250;
    if (_staSsid.length()) startStationMode();
    return true;
}

bool WiFiManager::connectToNetwork(const char* ssid, const char* pass, uint32_t timeoutMs) {
    // Own temporary inputs too: their source may be a short-lived HTTP document.
    const String candidateSsid(ssid), candidatePass(pass);
    WiFi.mode(_apActive ? WIFI_AP_STA : WIFI_STA);
    WiFi.setSleepMode(WIFI_NONE_SLEEP);
    WiFi.setAutoReconnect(true);
    WiFi.begin(candidateSsid.c_str(), candidatePass.c_str());
    const uint32_t started = millis();
    while (!online() && millis() - started < timeoutMs) delay(25);
    if (online()) {
        _staSsid = candidateSsid;
        _staPass = candidatePass;
        _linkEvent = true;
        if (_apActive) _apShutdownAt = millis() + 30000;
        return true;
    }
    if (_staSsid.length()) startStationMode();
    else if (!_apActive) startAccessPointMode();
    return false;
}

bool WiFiManager::takeServiceChange() {
    if (!_servicesDirty || !due(millis(), _servicesAt)) return false;
    _servicesDirty = false;
    return true;
}
bool WiFiManager::servicesReady() const { return online() || _apActive; }
bool WiFiManager::isApMode() const { return _apActive && !online(); }
bool WiFiManager::isSetupClient(IPAddress localIp) const { return _apActive && localIp == WiFi.softAPIP(); }
IPAddress WiFiManager::getIP() const { return online() ? WiFi.localIP() : (_apActive ? WiFi.softAPIP() : IPAddress(0,0,0,0)); }
bool WiFiManager::isConnected() { return online(); }
String WiFiManager::getConnectedSSID() { return WiFi.SSID(); }

bool WiFiManager::scheduleRecoveryTest(uint32_t offlineMs) {
    if (!online() || !_staSsid.length() || _testDropAt || _testResumeAt || offlineMs < 1000 || offlineMs > 30000) return false;
    _testOfflineMs = offlineMs;
    _testDropAt = millis() + 750;  // Return the authenticated HTTP response first.
    return true;
}

void WiFiManager::addDiagnostics(JsonObject result) const {
    result["saved_network"] = _staSsid.length() > 0;
    result["setup_ap_active"] = _apActive;
    result["reconnect_attempts"] = _attempts;
    result["optional_ap_starts"] = _fallbackCount;
    result["last_disconnect_reason"] = _lastDisconnectReason;
    result["auto_reconnect"] = WiFi.getAutoReconnect();
    result["hostname"] = WiFi.hostname();
    result["uptime_ms"] = millis();
    result["reset_reason_code"] = ESP.getResetInfoPtr()->reason;
    result["recovery_test_active"] = bool(_testDropAt || _testResumeAt);
}

void WiFiManager::scanNetworks(JsonArray& out) {
    const int8_t count = WiFi.scanNetworks();
    for (int i = 0; i < count; ++i) {
        JsonObject item = out.add<JsonObject>();
        item["ssid"] = WiFi.SSID(i);
        item["rssi"] = WiFi.RSSI(i);
        item["enc"] = WiFi.encryptionType(i);
    }
    WiFi.scanDelete();
}

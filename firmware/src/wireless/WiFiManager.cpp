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
        if (event.reason != 8) _lastStationFailureReason = event.reason;
        // A failed STA retry must not close the still-working SoftAP HTTP
        // connection (including iPhone captive-portal and setup submissions).
        if (_hadLink) _linkEvent = true;
    });
    _gotIpHandler = WiFi.onStationModeGotIP([this](const WiFiEventStationModeGotIP&) { _linkEvent = true; });
    _offlineSince = millis();
    if (_staSsid.length()) startStationMode();
    else enterUnconfiguredMode();
}

void WiFiManager::enterUnconfiguredMode() {
    // Ignore SDK station settings left by an earlier firmware. Only RAM is
    // cleared: begin() set persistent(false), our SecureStorage is untouched.
    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(false);
    WiFi.disconnect(false, true);
    startAccessPointMode();
    showStatus();
}


void WiFiManager::keepUnconfiguredAccessPoint() {
    if (_staSsid.length() || online()) return;
    WiFi.setAutoReconnect(false);
    WiFi.disconnect(false, true);  // RAM only; persistent(false) is set in begin().
    WiFi.mode(WIFI_AP);
}

bool WiFiManager::startStationMode() {
    if (_recoveryScanActive || online()) return online();
    _setupRetryPaused = false;
    _resumeAfterSetupAt = 0;
    _setupPauseUntil = 0;
    if (!_staSsid.length()) return false;
    WiFi.mode(_apActive ? WIFI_AP_STA : WIFI_STA);
    WiFi.setSleepMode(WIFI_NONE_SLEEP);
    // Give a failed SDK connection a fresh start, without clearing credentials.
    WiFi.setAutoReconnect(false);
    WiFi.disconnect(false, false);
    WiFi.hostname(String("geekmagic-") + String(ESP.getChipId(), HEX));
    if (_lastStationFailureReason == 201 && _attempts >= 2 &&
        (!_apActive || !WiFi.softAPgetStationNum())) {
        // Manual scanning recovered a station stuck in NO_AP_FOUND. Do the
        // same asynchronously; HTTP/DNS and the watchdog must keep running.
        _recoveryScanActive = true;
        _recoveryScanDeadline = millis() + 15000;
        WiFi.scanNetworks(true, true);
        return false;
    }
    connectStation();
    return online();  // No blocking wait: services and watchdog keep running.
}

void WiFiManager::connectStation(int32_t channel, const uint8_t* bssid) {
    WiFi.setAutoReconnect(true);
    WiFi.begin(_staSsid.c_str(), _staPass.c_str(), channel, bssid);
    ++_attempts;
    _nextAttemptAt = millis() + RETRY_MS;
}

void WiFiManager::finishRecoveryScan() {
    if (!_recoveryScanActive) return;
    const int count = WiFi.scanComplete();
    if (count == WIFI_SCAN_RUNNING && !due(millis(), _recoveryScanDeadline)) return;
    int best = -1;
    for (int i = 0; i < count; ++i) {
        if (WiFi.SSID(i) == _staSsid && (best < 0 || WiFi.RSSI(i) > WiFi.RSSI(best))) best = i;
    }
    uint8_t bssid[6] = {};
    const int32_t channel = best >= 0 ? WiFi.channel(best) : 0;
    if (best >= 0) memcpy(bssid, WiFi.BSSID(best), sizeof(bssid));
    WiFi.scanDelete();
    _recoveryScanActive = false;
    if (online()) return;
    if (_apActive && WiFi.softAPgetStationNum()) {
        pauseStationForSetup();
        _nextAttemptAt = millis() + RETRY_MS;
        return;
    }
    // The hint is used only for this attempt. The next scan can discover a
    // different BSSID/channel if the router roams or changes its settings.
    connectStation(channel, best >= 0 ? bssid : nullptr);
}

void WiFiManager::pauseStationForSetup() {
    if (_setupRetryPaused || !_apActive || online() || !due(millis(), _setupPauseAllowedAt)) return;
    _setupRetryPaused = true;
    _resumeAfterSetupAt = 0;
    _setupPauseUntil = millis() + 180000;
    WiFi.setAutoReconnect(false);
    WiFi.disconnect(false, false);
    Logger::info("Setup client joined; background STA retries paused", "WiFiManager");
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
    finishRecoveryScan();
    if (_apActive) {
        _dns.processNextRequest();
        if (!online()) {
            if (WiFi.softAPgetStationNum()) {
                if (_staSsid.length()) pauseStationForSetup();
                _resumeAfterSetupAt = 0;
                if (!_phoneJoinedAt) _phoneJoinedAt = now;
                if (!_pageQrShown && now - _phoneJoinedAt >= 8000) {
                    _pageQrShown = true;
                    Onboarding::draw(true);
                }
            } else if (_phoneJoinedAt) {
                _phoneJoinedAt = 0;
                _pageQrShown = false;
                Onboarding::draw();
                // Brief phone reassociations should not immediately restart
                // scanning and knock it off the single ESP8266 radio again.
                if (_setupRetryPaused) _resumeAfterSetupAt = now + 15000;
            }
        }
    }
    if (_setupRetryPaused && ((_resumeAfterSetupAt && due(now, _resumeAfterSetupAt)) ||
                               due(now, _setupPauseUntil))) {
        // A phone left on GeekMagic must not suppress home recovery forever.
        // Give the STA a complete attempt before allowing another setup pause.
        _setupPauseAllowedAt = now + RETRY_MS;
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
    if (!connected && !_setupRetryPaused && !_recoveryScanActive && _staSsid.length()) {
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
    // A setup submission owns the next connection, not a pending recovery scan.
    _recoveryScanActive = false;
    WiFi.scanDelete();
    _setupRetryPaused = false;
    _resumeAfterSetupAt = 0;
    _setupPauseUntil = 0;
    _setupPauseAllowedAt = 0;
    WiFi.mode(_apActive ? WIFI_AP_STA : WIFI_STA);
    WiFi.setSleepMode(WIFI_NONE_SLEEP);
    WiFi.setAutoReconnect(false);
    WiFi.disconnect(false, false);
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
    if (!_staSsid.length()) {
        // No saved station exists on a genuine first run. A failed password
        // must leave a quiet, usable setup AP instead of endless SDK retries.
        keepUnconfiguredAccessPoint();
        if (!_apActive) startAccessPointMode();
    }
    else if (_apActive && WiFi.softAPgetStationNum()) pauseStationForSetup();
    else if (_staSsid.length()) startStationMode();
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



void WiFiManager::addStatus(JsonObject result) const {
    result["firmware_build"] = PROJECT_VER_STR;
    result["saved_network"] = _staSsid.length() > 0;
    result["setup_ap_active"] = _apActive;
    result["reconnect_attempts"] = _attempts;
    result["optional_ap_starts"] = _fallbackCount;
    result["last_disconnect_reason"] = _lastDisconnectReason;
    result["auto_reconnect"] = WiFi.getAutoReconnect();
    result["uptime_ms"] = millis();
    result["reset_reason_code"] = ESP.getResetInfoPtr()->reason;
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

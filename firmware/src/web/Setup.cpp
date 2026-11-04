// SPDX-License-Identifier: GPL-3.0-or-later
// Minimal setup page in program flash; no filesystem image is required.
#include <Arduino.h>
#include <ArduinoJson.h>
#include <user_interface.h>
#include "web/Api.h"
#include "config/ConfigManager.h"
#include "wireless/WiFiManager.h"
#include "display/DisplayManager.h"
#include "project_version.h"

extern ConfigManager configManager;
extern WiFiManager* wifiManager;

namespace {
String setupNonce;
const char PAGE[] PROGMEM = R"HTML(<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Настройка CubeDesk</title><style>body{font:16px -apple-system,Segoe UI,sans-serif;background:linear-gradient(145deg,#eeebff,#f4f5fa 65%,#e7f4f5);color:#1c2940;margin:0;padding:24px;min-height:100vh;box-sizing:border-box}main{max-width:480px;margin:auto}section{background:#fff;border:1px solid #eceaf5;border-radius:20px;padding:23px;margin-top:20px;box-shadow:0 12px 40px #5040730a}h1{font-size:30px;letter-spacing:-1px;margin-bottom:12px}h2{font-size:23px}p{line-height:1.6;color:#66748c}label{display:block;margin-top:18px;font-size:13px}input{box-sizing:border-box;width:100%;font:inherit;padding:13px;border:1px solid #d9deeb;border-radius:10px;margin-top:6px}input:focus{outline:2px solid #b3a2fc}button{width:100%;padding:14px;background:#7658e9;color:white;border:0;border-radius:10px;font:600 15px -apple-system,sans-serif;margin-top:23px;cursor:pointer}button:disabled{opacity:.6}.secondary{background:#f2efff;color:#6651bc;margin-top:12px}a{color:#7658e9}small{color:#8993a4;font-size:11px;letter-spacing:1px}.hint{font-size:13px}.steps{color:#7658e9;font-size:13px;font-weight:600}code{overflow-wrap:anywhere}</style><main><small>CUBEDESK / %VERSION%</small><h1>Давайте подключим кубик</h1><section>%CONTENT%</section><p class="hint">Настройка проходит локально на кубике. Интернет на телефоне для этого не нужен.</p></main></html>)HTML";

const char FORM[] PROGMEM = R"HTML(<div class='steps'>ШАГ 2 ИЗ 2 · ДОМАШНИЙ WI-FI</div><p>Выберите вашу сеть 2,4 ГГц и введите её пароль.</p><form id='wifi' method='POST' action='/setup/wifi'><label>Название домашней сети<input id='ssid' name='ssid' list='networks' maxlength='32' autocapitalize='none' autocomplete='off' required value='%SSID%'></label><datalist id='networks'></datalist><button type='button' class='secondary' id='scan'>Найти сети рядом</button><p id='scan-status' class='hint' role='status'></p><label>Пароль домашней сети<input id='password' type='password' name='password' maxlength='63' autocomplete='off'></label><button type='button' class='secondary' id='reveal'>Показать пароль</button><input type='hidden' name='nonce' value='%NONCE%'><button id='submit'>Подключить кубик</button></form><p class='hint' id='progress' role='status'>Подключение занимает до 30 секунд. Настройки сохранятся после отключения питания.</p><script>document.getElementById('reveal').onclick=function(){const p=document.getElementById('password');p.type=p.type==='password'?'text':'password';this.textContent=p.type==='password'?'Показать пароль':'Скрыть пароль'};document.getElementById('scan').onclick=async function(){this.disabled=true;const s=document.getElementById('scan-status');s.textContent='Ищем сети…';try{const r=await fetch('/setup/networks',{cache:'no-store'});if(!r.ok)throw Error();const nets=await r.json();const list=document.getElementById('networks');list.replaceChildren();for(const n of nets){const o=document.createElement('option');o.value=n;list.appendChild(o)}s.textContent=nets.length?'Нажмите на поле названия и выберите сеть.':'Сети не найдены. Введите название вручную.'}catch(e){s.textContent='Введите название сети вручную.'}finally{this.disabled=false}};document.getElementById('wifi').onsubmit=function(){document.getElementById('submit').disabled=true;document.getElementById('progress').textContent='Подключаем кубик… Оставьте страницу открытой до 30 секунд.'};</script>)HTML";

String escaped(String text) {
    text.replace("&", "&amp;");
    text.replace("<", "&lt;");
    text.replace(">", "&gt;");
    text.replace("\"", "&quot;");
    text.replace("'", "&#39;");
    return text;
}

const char* flashMarker(const char* text, const char* marker) {
    const size_t count = strlen(marker);
    for (; pgm_read_byte(text); ++text) {
        if (strncmp_P(marker, text, count) == 0) return text;
    }
    return nullptr;  // All callers use markers present in static templates.
}

void sendPageStart(Webserver* webserver, size_t contentBytes, int code = 200) {
    const char* version = flashMarker(PAGE, "%VERSION%");
    const char* content = flashMarker(PAGE, "%CONTENT%");
    auto& server = webserver->raw();
    // Captive-network probes open several sockets. Do not hold the only HTTP
    // handler waiting on an idle phone connection between small responses.
    server.keepAlive(false);
    server.client().setNoDelay(true);
    // Synchronous writes avoid accumulating TCP_SND_BUF copies while the
    // phone acknowledges successive pieces of the page.
    server.client().setSync(true);
    const size_t total = strlen_P(PAGE) - strlen("%VERSION%") - strlen("%CONTENT%") +
                         strlen(PROJECT_VER_STR) + contentBytes;
    webserver->raw().sendHeader("Cache-Control", "no-store");
    webserver->raw().sendHeader("X-Content-Type-Options", "nosniff");
    webserver->raw().sendHeader("Referrer-Policy", "no-referrer");
    server.setContentLength(total);
    server.send(code, "text/html; charset=utf-8", "");
    server.sendContent_P(PAGE, version - PAGE);
    server.sendContent(PROJECT_VER_STR);
    const char* afterVersion = version + strlen("%VERSION%");
    server.sendContent_P(afterVersion, content - afterVersion);
}

void sendPageEnd(Webserver* webserver) {
    webserver->raw().sendContent_P(flashMarker(PAGE, "%CONTENT%") + strlen("%CONTENT%"));
}

void sendPage(Webserver* webserver, const String& content, int code = 200) {
    sendPageStart(webserver, content.length(), code);
    webserver->raw().sendContent(content);
    sendPageEnd(webserver);
}

void sendSetupForm(Webserver* webserver) {
    const String ssid = escaped(configManager.getSSID());
    const char* ssidAt = flashMarker(FORM, "%SSID%");
    const char* nonceAt = flashMarker(FORM, "%NONCE%");
    const size_t bytes = strlen_P(FORM) - strlen("%SSID%") - strlen("%NONCE%") +
                         ssid.length() + setupNonce.length();
    sendPageStart(webserver, bytes);
    auto& server = webserver->raw();
    server.sendContent_P(FORM, ssidAt - FORM);
    server.sendContent(ssid);
    const char* afterSsid = ssidAt + strlen("%SSID%");
    server.sendContent_P(afterSsid, nonceAt - afterSsid);
    server.sendContent(setupNonce);
    server.sendContent_P(nonceAt + strlen("%NONCE%"));
    sendPageEnd(webserver);
}

bool setupClient(Webserver* webserver) {
    return wifiManager && wifiManager->isSetupClient(webserver->raw().client().localIP());
}

String pairingInstructions() {
    return "<h2>Готово — осталось подключить ПК</h2><p>Верните телефон в домашнюю сеть и откройте CubeDesk на ПК. "
        "Введите IP с экрана кубика.</p><details><summary>Ключ подключения CubeDesk</summary>"
        "<p class='hint'>В CubeDesk откройте «Настройка потокового режима» и сохраните этот API-токен. "
        "Он индивидуален для вашего кубика.</p><label>API-токен<input readonly value='" +
        escaped(configManager.getApiToken()) + "' onclick='this.select()'></label></details>";
}
}

void handleSetupPage(Webserver* webserver) {
    if (wifiManager == nullptr) {
        sendPage(webserver, "<p>Wi-Fi is starting.</p>", 503);
        return;
    }
    if (WiFiManager::isConnected()) {
        sendPage(webserver, "<h2>Кубик подключён</h2><p>IP: " + wifiManager->getIP().toString() +
                 "</p><p>Откройте CubeDesk на ПК и подключите кубик по этому адресу.</p>"
                 + (setupClient(webserver) ? pairingInstructions() : String("")));
        return;
    }
    if (!setupClient(webserver)) {
        sendPage(webserver, "<p>Для настройки подключитесь к Wi-Fi GeekMagic и откройте http://192.168.4.1/setup.</p>", 403);
        return;
    }
    if (setupNonce.length() == 0) {
        char nonce[33];
        snprintf(nonce, sizeof(nonce), "%08lx%08lx%08lx%08lx", os_random(), os_random(), os_random(), os_random());
        setupNonce = nonce;
    }
    sendSetupForm(webserver);
}

void handleSetupWifi(Webserver* webserver) {
    if (!setupClient(webserver) || setupNonce.length() == 0 ||
        webserver->raw().arg("nonce") != setupNonce) {
        sendPage(webserver, "<p>Откройте страницу настройки через сеть GeekMagic и повторите.</p>", 403);
        return;
    }
    const String ssid = webserver->raw().arg("ssid");
    const String password = webserver->raw().arg("password");
    if (ssid.length() == 0 || ssid.length() > 32 || password.length() > 63 ||
        (password.length() > 0 && password.length() < 8)) {
        sendPage(webserver, "<p>Проверьте имя сети и пароль.</p><a href='/setup'>Назад</a>", 400);
        return;
    }
    if (!wifiManager->connectToNetwork(ssid.c_str(), password.c_str(), 30000)) {
        sendPage(webserver, "<p>Подключение не удалось. Проверьте сеть 2,4 ГГц и пароль.</p><a href='/setup'>Повторить</a>", 400);
        return;
    }
    configManager.setWiFi(ssid.c_str(), password.c_str());
    const bool saved = configManager.save();
    const String ip = wifiManager->getIP().toString();
    wifiManager->showStatus();
    sendPage(webserver, "<h2>Подключено</h2><p>Домашний IP кубика: <b>" + ip +
             "</b></p><p>" + (saved ? String("Настройки сохранены.") : String("Не удалось сохранить настройки.")) +
             "</p>" + pairingInstructions() + "<p class='hint'>Точка GeekMagic выключится через 30 секунд. Сохраните ключ подключения сейчас.</p>");
}

void handleSetupNetworks(Webserver* webserver) {
    webserver->raw().keepAlive(false);
    if (!setupClient(webserver)) {
        webserver->raw().send(403, "application/json", "[]");
        return;
    }
    const int count = WiFi.scanNetworks();
    JsonDocument result;
    JsonArray names = result.to<JsonArray>();
    for (int i = 0; i < count && names.size() < 20; ++i) {
        String name = WiFi.SSID(i);
        bool duplicate = name.length() == 0;
        for (JsonVariant value : names) if (value.as<String>() == name) duplicate = true;
        if (!duplicate) names.add(name);
    }
    WiFi.scanDelete();
    wifiManager->keepUnconfiguredAccessPoint();
    String body;
    serializeJson(result, body);
    webserver->raw().sendHeader("Cache-Control", "no-store");
    webserver->raw().send(200, "application/json", body);
}

bool handleCaptivePortal(Webserver* webserver) {
    if (!setupClient(webserver) || webserver->raw().method() != HTTP_GET || webserver->raw().uri().startsWith("/api/")) return false;
    webserver->raw().keepAlive(false);
    webserver->raw().client().setNoDelay(true);
    webserver->raw().client().setSync(true);
    webserver->raw().sendHeader("Location", "http://192.168.4.1/setup", true);
    webserver->raw().sendHeader("Cache-Control", "no-store");
    webserver->raw().send(302, "text/plain", "Open CubeDesk setup");
    return true;
}

// SPDX-License-Identifier: GPL-3.0-or-later
#include "wireless/Onboarding.h"
#include "display/DisplayManager.h"
#include <qrcodegen.h>

namespace {
String escapeWifi(const char* text) {
    String result;
    for (; *text; ++text) {
        if (*text == '\\' || *text == ';' || *text == ',' || *text == ':' || *text == '"') result += '\\';
        result += *text;
    }
    return result;
}
}

String Onboarding::wifiPayload() {
    return "WIFI:T:WPA;S:" + escapeWifi(SSID) + ";P:" + escapeWifi(PASSWORD) + ";;";
}

void Onboarding::draw(bool openPage) {
    // Bounded buffers: no framebuffer allocation or persistent RAM overhead.
    uint8_t qr[qrcodegen_BUFFER_LEN_FOR_VERSION(4)];
    uint8_t scratch[sizeof(qr)];
    const String payload = openPage ? String(URL) : wifiPayload();
    const bool encoded = qrcodegen_encodeText(payload.c_str(), scratch, qr, qrcodegen_Ecc_MEDIUM,
        1, 4, qrcodegen_Mask_AUTO, true);
    auto* gfx = DisplayManager::getGfx();
    gfx->fillScreen(LCD_BLACK);
    gfx->setTextWrap(false);
    gfx->setTextSize(1);
    gfx->setTextColor(LCD_WHITE, LCD_BLACK);
    gfx->setCursor(12, 4);
    gfx->print(openPage ? "2. OPEN SETUP PAGE" : "1. SCAN TO JOIN WI-FI");
    if (encoded) {
        const int size = qrcodegen_getSize(qr);
        const int scale = 4, edge = (size + 8) * scale;
        const int x = (240 - edge) / 2, y = 20 + (164 - edge) / 2;
        gfx->fillRect(x, y, edge, edge, LCD_WHITE);
        for (int row = 0; row < size; ++row) {
            for (int col = 0; col < size; ++col) {
                if (qrcodegen_getModule(qr, col, row))
                    gfx->fillRect(x + (col + 4) * scale, y + (row + 4) * scale, scale, scale, LCD_BLACK);
            }
            yield();
        }
    }
    gfx->setCursor(12, 191); gfx->print("Wi-Fi: "); gfx->print(SSID);
    gfx->setCursor(12, 204); gfx->print("Pass: "); gfx->print(PASSWORD);
    gfx->setCursor(12, 221); gfx->print("192.168.4.1/setup");
    gfx->setTextWrap(true);
}

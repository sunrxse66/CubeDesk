// SPDX-License-Identifier: GPL-3.0-or-later
// Compressed frame streaming. No animation data is written to flash.
#include "display/PCStream.h"
#include "display/DisplayManager.h"
#include "config/ConfigManager.h"
#include <ESP8266WiFi.h>
#include <TJpg_Decoder.h>
#include <algorithm>
#include <cstring>
#include <memory>
#include <new>

extern ConfigManager configManager;
namespace {
constexpr size_t STRIPE_ROWS = 4;
constexpr size_t STRIPE_BYTES = 240 * 2 * STRIPE_ROWS;
constexpr uint32_t FRAME_BYTES = 240 * 240 * 2;
constexpr uint32_t JPEG_LIMIT = 16384;
constexpr uint32_t IDLE_TIMEOUT_MS = 15000;
WiFiServer server(7777);
WiFiClient client;
enum class State { Hello, Token, Header, Pixels, Jpeg };
State state = State::Hello;
uint8_t header[12];
char token[129];
alignas(4) uint8_t stripe[2048];
std::unique_ptr<uint8_t[]> jpeg;
size_t used = 0, tokenLength = 0;
uint16_t y = 0;
uint32_t sequence = 0, lastData = 0, connectedAt = 0;
uint32_t frameStarted = 0, drawMicros = 0, wireBytes = 0;
uint32_t jpegCapacity = 0;
bool modern = false, discard = false;
uint16_t jpegScale = 1;

uint32_t read32(const uint8_t* p) {
    return uint32_t(p[0]) | (uint32_t(p[1]) << 8) |
           (uint32_t(p[2]) << 16) | (uint32_t(p[3]) << 24);
}
void put32(uint8_t* p, uint32_t value) {
    for (uint8_t i = 0; i < 4; ++i) p[i] = uint8_t(value >> (i * 8));
}
void closeClient() {
    client.stop(); jpeg.reset(); jpegCapacity = 0;
    memset(token, 0, sizeof(token));
    used = 0; state = State::Hello; modern = false;
}
bool readPart(uint8_t* destination, size_t size, size_t& budget) {
    const int available = client.available();
    if (available <= 0 || budget == 0) return false;
    const size_t count = std::min(std::min(size - used, size_t(available)), budget);
    const int received = client.read(destination + used, count);
    if (received <= 0) return false;
    used += size_t(received); budget -= size_t(received); lastData = millis();
    return used == size;
}
bool ack() {
    uint8_t response[24] = {'A', 'C', 'K', '1'};
    put32(response + 4, sequence);
    size_t length = 8;
    if (modern) {
        response[3] = '2';
        const uint32_t elapsed = micros() - frameStarted;
        put32(response + 8, elapsed > drawMicros ? elapsed - drawMicros : 0);
        put32(response + 12, drawMicros);
        put32(response + 16, wireBytes);
        put32(response + 20, ESP.getFreeHeap());
        length = sizeof(response);
    }
    return client.write(response, length) == length;
}
bool jpegDraw(int16_t x, int16_t yPos, uint16_t width, uint16_t height, uint16_t* bitmap) {
    if (x < 0 || yPos < 0 || (x + width) * jpegScale > 240 || (yPos + height) * jpegScale > 240)
        return false;
    if (jpegScale > 1) {
        const uint16_t outWidth = width * jpegScale;
        const uint16_t inputRows = (sizeof(stripe) / 2) / outWidth / jpegScale;
        if (inputRows == 0) return false;
        uint16_t* expanded = reinterpret_cast<uint16_t*>(stripe);
        for (uint16_t first = 0; first < height; first += inputRows) {
            const uint16_t rows = std::min(inputRows, uint16_t(height - first));
            for (uint16_t row = 0; row < rows; ++row) {
                uint16_t* destination = expanded + row * jpegScale * outWidth;
                for (uint16_t column = 0; column < width; ++column) {
                    for (uint16_t repeat = 0; repeat < jpegScale; ++repeat)
                        destination[column * jpegScale + repeat] = bitmap[(first + row) * width + column];
                }
                for (uint16_t repeat = 1; repeat < jpegScale; ++repeat)
                    memcpy(destination + repeat * outWidth, destination, outWidth * 2);
            }
            DisplayManager::getGfx()->draw16bitRGBBitmap(x * jpegScale, (yPos + first) * jpegScale,
                                                        expanded, outWidth, rows * jpegScale);
        }
        return true;
    }
    if (x < 0 || yPos < 0 || x + width > 240 || yPos + height > 240) return false;
    DisplayManager::getGfx()->draw16bitRGBBitmap(x, yPos, bitmap, width, height);
    return true;
}
bool drawJpeg() {
    uint16_t width = 0, height = 0;
    if (TJpgDec.getJpgSize(&width, &height, jpeg.get(), wireBytes) != JDR_OK ||
        !(width == height && (width == 240 || width == 120 || width == 80))) return false;
    jpegScale = 240 / width;
    const uint32_t start = micros();
    const JRESULT result = TJpgDec.drawJpg(0, 0, jpeg.get(), wireBytes);
    drawMicros = micros() - start;
    return result == JDR_OK;
}
}

void PCStream::begin() {
    TJpgDec.setJpgScale(1);
    TJpgDec.setSwapBytes(false);
    TJpgDec.setCallback(jpegDraw);
    server.begin();
}
bool PCStream::active() {
    return client.connected() && state != State::Hello && state != State::Token;
}
void PCStream::networkChanged(bool ready) {
    closeClient();
    server.stop();
    if (ready) server.begin();
}
void PCStream::update() {
    if (!client.connected()) {
        closeClient(); client = server.accept();
        if (!client) return;
        client.setNoDelay(true); lastData = connectedAt = millis();
    }
    const bool authenticating = state == State::Hello || state == State::Token;
    if (millis() - lastData > IDLE_TIMEOUT_MS ||
        (authenticating && millis() - connectedAt > 5000)) { closeClient(); return; }
    size_t budget = 32768;
    while (budget && client.available()) {
        if (state == State::Hello) {
            if (!readPart(header, 6, budget)) return;
            modern = memcmp(header, "GMC2", 4) == 0;
            tokenLength = size_t(header[4]) | (size_t(header[5]) << 8);
            if ((!modern && memcmp(header, "GMC1", 4) != 0) || tokenLength == 0 || tokenLength > 128) {
                closeClient(); return;
            }
            used = 0; state = State::Token;
        } else if (state == State::Token) {
            if (!readPart(reinterpret_cast<uint8_t*>(token), tokenLength, budget)) return;
            const char* expected = configManager.getApiToken();
            const bool valid = expected && strlen(expected) == tokenLength &&
                               memcmp(token, expected, tokenLength) == 0;
            memset(token, 0, sizeof(token));
            if (!valid) { closeClient(); return; }
            DisplayManager::stopGif();
            if (modern) {
                const uint32_t heap = ESP.getFreeHeap();
                jpegCapacity = heap > 12288 ? std::min(JPEG_LIMIT, ((heap - 8192) / 1024) * 1024) : 0;
                if (jpegCapacity >= 4096) jpeg.reset(new (std::nothrow) uint8_t[jpegCapacity]);
                if (!jpeg) jpegCapacity = 0;
                uint8_t caps[12] = {'O','K','J','2'};
                put32(caps + 4, jpegCapacity);
                put32(caps + 8, (jpeg ? 1u : 0u) | 2u | 4u);
                if (client.write(caps, sizeof(caps)) != sizeof(caps)) { closeClient(); return; }
            } else if (client.write(reinterpret_cast<const uint8_t*>("OKAY"), 4) != 4) {
                closeClient(); return;
            }
            used = 0; state = State::Header;
        } else if (state == State::Header) {
            if (!readPart(header, sizeof(header), budget)) return;
            sequence = read32(header + 4); wireBytes = read32(header + 8);
            frameStarted = micros(); drawMicros = 0; used = 0;
            if (memcmp(header, "PNG1", 4) == 0 && wireBytes == 0) {
                if (!ack()) { closeClient(); return; }
            } else if ((memcmp(header, "FRM1", 4) == 0 ||
                       (modern && memcmp(header, "RXD1", 4) == 0)) && wireBytes == FRAME_BYTES) {
                discard = memcmp(header, "RXD1", 4) == 0;
                y = 0; state = State::Pixels;
            } else if (modern && jpeg && memcmp(header, "JPG1", 4) == 0 &&
                       wireBytes >= 4 && wireBytes <= jpegCapacity) {
                state = State::Jpeg;
            } else if (modern && memcmp(header, "LCD1", 4) == 0 && wireBytes == 0) {
                const uint32_t start = micros();
                DisplayManager::getGfx()->fillScreen(0x001F);
                drawMicros = micros() - start;
                if (!ack()) { closeClient(); return; }
            } else { closeClient(); return; }
        } else if (state == State::Jpeg) {
            if (!readPart(jpeg.get(), wireBytes, budget)) return;
            if (!drawJpeg() || !ack()) { closeClient(); return; }
            used = 0; state = State::Header;
        } else {
            if (!readPart(stripe, STRIPE_BYTES, budget)) return;
            if (!discard) {
                const uint32_t start = micros();
                DisplayManager::getGfx()->draw16bitBeRGBBitmap(
                    0, y, reinterpret_cast<uint16_t*>(stripe), 240, STRIPE_ROWS);
                drawMicros += micros() - start;
            }
            used = 0; y += STRIPE_ROWS;
            if (y == 240) {
                if (!ack()) { closeClient(); return; }
                state = State::Header;
            }
        }
    }
}

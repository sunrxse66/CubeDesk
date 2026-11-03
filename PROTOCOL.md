# PCStream transport

TCP 7777, one authenticated client, LAN only (no TLS). No animation frames are
written to flash. All integers are unsigned little endian.

## Negotiation

Modern client: GMC2, uint16 UTF-8 token length (1..128), token bytes.
Receiver: OKJ2, uint32 maximum JPEG bytes, uint32 capability flags.
Bit 0 enables JPEG; bit 1 enables profiling; bit 2 enables 80×80 JPEG. JPEG capacity is based on available
heap; the current build reserves at least 8 KiB for network operations.
Authentication has a 5-second deadline. Invalid tokens close the connection.
Legacy GMC1 with the same length/token returns OKAY. Modern clients reconnect
using GMC1 when an older receiver rejects GMC2.

## Packets

12-byte header: four-byte magic, uint32 sequence, uint32 payload length.
Payload follows. Sender waits for the matching ACK before sending another frame.

| Magic | Payload |
| --- | --- |
| JPG1 | Baseline JPEG, 80×80, 120×120 or 240×240, within negotiated capacity |
| FRM1 | Exactly 115200 bytes of big endian RGB565, row-major 240×240 |
| PNG1 | Zero length keepalive, no LCD writes |
| RXD1 | Modern profiling: 115200 bytes discarded, network-only measurement |
| LCD1 | Modern profiling: zero length, fills LCD blue |

GMC1 ACK: ACK1, uint32 sequence (8 bytes).
GMC2 ACK: ACK2, uint32 sequence, uint32 receive microseconds, uint32 draw
microseconds, uint32 payload bytes, uint32 free heap (24 bytes).
Host transport time includes scheduling/network overhead. These acknowledgements
measure completed drawing, not LCD vertical synchronization.

TJpg_Decoder produces RGB565; 80×80 and 120×120 frames are expanded 3× and 2× to fill the LCD.
Raw frames use four-row strips. Neither path holds a full RGB565 framebuffer.
Invalid lengths/dimensions, decoding failures or 15 seconds of inactivity close
the connection. Last successfully drawn pixels remain visible.

## Playback clock

Pillow handles GIF disposal, transparency and original delays. A producer prepares
up to eight frames ahead. Near deadlines, Python 3.11 high-resolution sleep avoids
Windows Event.wait tick rounding. Presentation timestamps follow the source clock. Late
frames are skipped rather than stretching the animation into slow motion. The FPS
setting is an upper limit; the app shows measured ACK cadence separately. JPEG
quality adapts to recent transfer time and the available buffer. Static images
always remain native 240×240, including in smooth mode.

Updates are tile by tile; tearing remains possible. There is no guarantee of
30 FPS for arbitrary content, atomic screen flips, audio or video decoding.
Stop streaming before OTA or changing display modes. State polling is local and
does not contact the cube. Streaming reconnects after transfer errors.

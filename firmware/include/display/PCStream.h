// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
namespace PCStream {
void begin();
void update();
bool active();
void networkChanged(bool ready);
}

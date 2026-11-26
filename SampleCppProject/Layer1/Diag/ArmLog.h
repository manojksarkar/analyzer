#pragma once

// The project's log calls that ArmCompilerHeaders.cpp makes (2026-11-26). A unit of its own,
// so each call is from another unit: it gives the function an interface row, with
// ArmCriticalReport as its caller -- when the call is linked (see ArmCompilerHeaders.cpp).

void DiagLogText(const char *text);
void DiagLogLength(unsigned int length);

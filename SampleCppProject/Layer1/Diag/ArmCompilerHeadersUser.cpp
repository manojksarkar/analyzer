// Calls ArmCompilerHeaders.cpp's functions from another unit, so they are published.
#include "ArmCompilerHeaders.h"

PRIVATE void ArmStartup(void)
{
    ArmCriticalReport();
    ArmAsmBarrier();
}

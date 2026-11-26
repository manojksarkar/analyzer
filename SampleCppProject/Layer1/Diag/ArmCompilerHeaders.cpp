// Headers that come with the compiler, not with the project (2026-11-26).
//
// arm_compat.h and string.h are in Arm Compiler 6's own include folder; this project does not
// have them. Where that folder is not given -- armCompiler.path in config.local.json not set,
// no -isystem<folder> in clang.clangArgs -- libclang logs one error, "'arm_compat.h' file not
// found", and drops every call that uses a name from these headers:
//   - __disable_irq() and __enable_irq(), declared in arm_compat.h;
//   - DiagLogLength(strlen(s_name)), a call to a PROJECT function (ArmLog.cpp), because its
//     argument names strlen. No arrow, no caller: DiagLogLength has no interface row, and the
//     log lists the call as "call not linked".
// DiagLogText(s_name) names nothing from these headers and is linked either way; so is
// ArmLog.h, included after the header that is missing.
//
// The rest parses with or without the folder: inline assembly, and armclang's attributes --
// section, used, naked, and zero_init, which only armclang knows (libclang: a warning).
// tests/unit/test_toolchain.py parses this file both ways, with stand-ins for the two headers.
#include <arm_compat.h>
#include <string.h>
#include "ArmLog.h"
#include "ArmCompilerHeaders.h"

static char s_name[8] __attribute__((section(".ram_data"), zero_init));

PUBLIC void ArmCriticalReport(void)
{
    __disable_irq();
    DiagLogText(s_name);
    DiagLogLength(strlen(s_name));
    __enable_irq();
}

PUBLIC void ArmAsmBarrier(void)
{
    __asm volatile("dsb 0xF" ::: "memory");
    __nop();
}

__attribute__((used, section(".fast_code"))) PRIVATE int ArmFastAdd(int a, int b)
{
    return a + b;
}

__attribute__((naked)) PRIVATE void ArmResetEntry(void)
{
    __asm volatile("b ArmFastAdd");
}

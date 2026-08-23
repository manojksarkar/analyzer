// Fixture for clang.clangArgs: the ARM hint builtins are declared only for
// ARM/AArch64 targets. On the default (host) target every call below reports
//   error: use of undeclared identifier '__builtin_arm_wfi'
// and adding "--target=arm-none-eabi" to clang.clangArgs makes them all vanish.
// That one flag is sufficient -- no -mcpu, no -ffreestanding (this project has no
// system #includes, so there is no libc header to go missing).
//
// The counter-intuitive half, and the reason this file exists: all four functions
// are recorded in model/functions.json EITHER WAY. Clang recovers from an error in
// a body and still builds the declaration, so errors in the log are NOT evidence
// that a function went missing. For a function that really does disappear, see
// ArmGuarded.cpp -- which logs no error at all.
#include "ArmIntrinsics.h"

PRIVATE void ArmWaitForInterrupt(void)
{
    __WFI();
}

PRIVATE void ArmWaitForEvent(void)
{
    __WFE();
}

PRIVATE void ArmSendEvent(void)
{
    __SEV();
}

PRIVATE void ArmSendEventLocal(void)
{
    __SEVL();
}

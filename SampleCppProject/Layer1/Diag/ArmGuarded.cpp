// The silent case: a function absent from model/functions.json with ZERO errors.
//
// FEATURE_ARM_PM is never defined, so the preprocessor discards the branch before
// clang sees it. No cursor is created, so there is no rejection event to log and
// no diagnostic to read -- unlike ArmIntrinsics.cpp, which is loud but complete.
// This is the shape a real "why is my function missing?" report usually has, and
// the case _scan_unrecorded_functions (engine/parser.py) exists to surface: a text
// scan still sees the definition even though clang never did.
//
// Fixed with -DFEATURE_ARM_PM (via --macros / clang.macrosFile), NOT by the ARM
// target flag. Toggling --target=arm-none-eabi changes nothing here.
#include "ArmIntrinsics.h"

#if defined(FEATURE_ARM_PM)
PRIVATE void ArmEnterLowPower(void)
{
    __WFI();
}
#endif

PRIVATE void ArmAlwaysPresent(void)
{
}

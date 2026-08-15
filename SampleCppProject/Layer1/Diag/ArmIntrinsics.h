// Mirrors the macro indirection real CMSIS uses (cmsis_armclang.h / cmsis_clang.h),
// so the failure surfaces at the CALL SITE, not here: a #define of an identifier is
// always legal, only its expansion is checked.
//
// Clang declares __builtin_arm_* ONLY when the target is ARM/AArch64. Parsed with a
// host (x86) target these expand to undeclared identifiers -- see ArmIntrinsics.cpp.
#ifndef ARM_INTRINSICS_H
#define ARM_INTRINSICS_H

#define __WFI()  __builtin_arm_wfi()
#define __WFE()  __builtin_arm_wfe()
#define __SEV()  __builtin_arm_sev()
#define __SEVL() __builtin_arm_sevl()

#endif

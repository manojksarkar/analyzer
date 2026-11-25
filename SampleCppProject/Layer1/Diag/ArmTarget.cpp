// The CPU and the compiler the build names decide which code exists (2026-11-25).
//
// compile_commands.json builds Layer1 for a Cortex-M7 (-mcpu=cortex-m7), so libclang defines
// __ARM_ARCH as 7 and ArmV7Barrier is parsed. Until the build's target flags were read, the
// parse had only --target=arm-none-eabi: an ARMv4T, __ARM_ARCH 4, and ArmV7Barrier was not
// there -- with no error, like ArmGuarded.cpp.
//
// __ARMCC_VERSION is defined by armclang, not by libclang. ArmCompilerOnly is parsed only when
// armCompiler.path in config.local.json names armclang; on any other machine the #else is.
#if defined(__ARM_ARCH) && (__ARM_ARCH >= 7)
PRIVATE void ArmV7Barrier(void)
{
    __builtin_arm_dsb(15);
}
#endif

#if defined(__ARMCC_VERSION)
PRIVATE int ArmCompilerOnly(void)
{
    return 6;
}
#else
PRIVATE int ArmOtherCompiler(void)
{
    return 0;
}
#endif

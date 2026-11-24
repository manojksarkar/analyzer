#include "BuildMacros.h"

// Test: code under an #if on a macro only the build defines (review SWE3-017).
// _CONFIG_ASIC and _NAND_DENSITY come from Core1's compile_commands.json, not from its
// macros file: without the build's -D flags the decision is missing and the page size is 8.
PUBLIC int g_buildTarget = 0;
PUBLIC int g_buildPageSize = 0;

PUBLIC int flowBuildConfig(int lba) {
#if defined(_CONFIG_ASIC)
    if (lba > 100) {
        g_buildTarget = 1;
    }
#endif
#if _NAND_DENSITY == 512
    g_buildPageSize = 16;
#else
    g_buildPageSize = 8;
#endif
    return g_buildPageSize;
}

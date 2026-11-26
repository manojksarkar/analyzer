#include "ArmLog.h"

static unsigned int s_lastLength;
static const char *s_lastText;

PUBLIC void DiagLogText(const char *text)
{
    s_lastText = text;
}

PUBLIC void DiagLogLength(unsigned int length)
{
    s_lastLength = length;
}

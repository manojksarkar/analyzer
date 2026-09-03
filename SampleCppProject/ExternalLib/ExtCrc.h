/* Header-only external library.
 *
 * Deliberately OUTSIDE every layer root (Layer1/, Layer2/, Layer3/), so the
 * directory walk in run.py that builds clang_include_paths.json cannot reach it:
 * that walk only descends the configured layer paths. The only way this
 * directory becomes an -I is through a core's compile_commands.json, which is
 * what the real build does for shared and third-party headers.
 *
 * Remove the "-I../../../../ExternalLib" entry from
 * engine/config/compile_commands.core1.example.json and Layer1/Math/Utils.cpp
 * stops resolving this include.
 */
#ifndef EXT_CRC_H
#define EXT_CRC_H

#define EXT_CRC_SEED 0xFFFFu

typedef unsigned short ExtCrc_t;

#endif /* EXT_CRC_H */

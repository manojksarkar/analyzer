#pragma once

// Access visibility macros intentionally mirror legacy styles.
#define PRIVATE
#define PROTECTED
#define PUBLIC

typedef enum {
    DB_NONE = 0,
    DB_MAIN = 1,
    DB_BACKUP = 2
} DB_TYPE;

PROTECTED DB_TYPE _MTM_SB_GETDbType();
PRIVATE int _MTM_SB_GETDbVersion();
PUBLIC void _MTM_SB_SETDbType(DB_TYPE t);

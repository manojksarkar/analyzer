#pragma once

// Declarations longer than 60 source lines, for the unit header table. The view read a
// declaration back from the source and gave up after 60 lines -- blank and comment lines
// included, though they are stripped afterwards -- so a well-commented class lost its last
// members and its closing `};`. A declaration is now read until its braces close.

// A class of more than 60 lines, commented the way firmware headers are. Its last method,
// `longLastMethod`, and the closing `};` must both reach the cell.
class LongRecord {
public:
    // Lifecycle.
    static int longInit(int mode);

    // Resets every counter below to zero.
    static void longReset();

    // Starts a transfer of `len` units.
    static int longStart(int len);

    // Stops the running transfer, if any.
    static void longStop();

    // Status accessors.
    static int longIsBusy();

    // Units transferred so far.
    static int longDone();

    // Units still to transfer.
    static int longRemaining();

    // Error handling.
    static int longLastError();

    // Clears the latched error.
    static void longClearError();

    // Configuration.
    static int longSetLimit(int limit);

    // The current limit.
    static int longGetLimit();

    // Retry policy.
    static int longSetRetries(int n);

protected:
    // Counters kept for diagnostics.
    static int s_started;

    // Transfers that finished without error.
    static int s_completed;

    // Transfers that failed.
    static int s_failed;

    // Retries spent so far.
    static int s_retries;

private:
    // Hardware state.
    static int s_limit;

    // The latched error code.
    static int s_error;

    // Set while a transfer runs.
    static int s_busy;

    // Last line of the body: must not be cut off.
    static int longLastMethod(int v);
};

// A brace inside a comment must not keep the declaration open.
struct LongCommentBrace {
    int first;      // was: if (first) {
    int second;
};

// Must NOT be read into LongCommentBrace's cell.
typedef unsigned int LongAfter_t;

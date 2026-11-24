#include "MemberWrites.h"

MwBlock MwBase::s_block;

void MwBase::mwBaseReset() {
    m_baseCount = 0;
}

void MwHelper::mwHelperReset() {
    m_n = 0;
}

void MwTable::mwDeleteEntry(int id) {
    m_table[id] = 0;
    m_used--;
}

void MwTable::mwClearAll() {
    for (int i = 0; i < 16; i++) {
        mwDeleteEntry(i);
    }
}

void MwTable::mwResetAll() {
    MwBase::mwBaseReset();
}

void MwTable::mwBumpBase() {
    MwBase::m_cx.a++;
}

void MwTable::mwInsertX(int nodeid) {
    MwEntry* bbx = &MwBase::s_block.xa[nodeid];
    bbx->a = nodeid;
}

void MwTable::mwMarkRow(int id) {
    MwEntry& row = m_rows[id];
    row.a = 1;
}

void MwTable::mwDump() const {
    int total = m_used;
    for (int i = 0; i < 16; i++) {
        total += m_table[i];
    }
    (void)total;
}

void MwTable::mwCopyTo(MwTable& other) const {
    other.m_used = m_used;
}

void MwTable::mwResetHelper() {
    MwHelper helper;
    helper.mwHelperReset();
}

MwEntry* MwTable::mwFind(int id) {
    return &m_rows[id];
}

void MwTable::mwMarkFound(int id) {
    MwEntry* found = mwFind(id);
    found->a = 1;
}

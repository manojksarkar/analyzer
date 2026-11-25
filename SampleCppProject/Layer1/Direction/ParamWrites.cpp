#include "ParamWrites.h"

void PwList::pwDeleteNode(PwPool::P_PwNode pNode) {
    pNode->length = pNode->length - 1;
}

void pwClearNode(PwNode* pNode) {
    pNode->length = 0;
    pNode->next = 0;
}

void pwResetNode(PwNode& node) {
    node.length = 0;
}

void pwFillBuffer(int* buf, int n) {
    for (int i = 0; i < n; i++) {
        *(buf + i) = 0;
    }
}

void pwStepFill(int* buf, int n) {
    while (n-- > 0) {
        *buf++ = 1;
    }
}

void pwClearViaCopy(PwPool::P_PwNode pNode) {
    PwPool::P_PwNode cur = pNode;
    cur->length = 0;
}

void pwMarkViaRef(PwNode* pNode) {
    PwNode& node = *pNode;
    node.length = 1;
}

void pwWalk(PwPool::P_PwNode pNode) {
    int count = 0;
    while (pNode) {
        count++;
        pNode = pNode->next;
    }
    (void)count;
}

void pwByValue(PwNode node) {
    node.length = 0;
    (void)node;
}

void pwClearNext(PwPool::P_PwNode pNode) {
    PwNode* next = pNode->next;
    next->length = 0;
}

void pwPassOn(PwNode* pNode) {
    pwClearNode(pNode);
}

void pwLambda() {
    auto clear = [](PwNode* p) { p->length = 0; };
    PwNode node = {1, 0};
    clear(&node);
}

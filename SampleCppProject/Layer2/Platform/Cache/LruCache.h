#ifndef LRUCACHE_H
#define LRUCACHE_H

void lru_init(int cap);
int lru_get(int key);
void lru_put(int key, int val);

#endif // LRUCACHE_H

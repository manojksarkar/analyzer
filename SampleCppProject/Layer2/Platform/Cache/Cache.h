#ifndef CACHE_H
#define CACHE_H

void cache_init();
void *cache_get(int key);
void cache_put(int key, void *val);
void cache_invalidate(int key);

#endif // CACHE_H

#ifndef STORAGE_H
#define STORAGE_H

void stor_init();
int stor_read(int addr, int len);
void stor_write(int addr, int data);

#endif // STORAGE_H

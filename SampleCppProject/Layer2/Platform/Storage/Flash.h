#ifndef FLASH_H
#define FLASH_H

void flash_erase(int sector);
void flash_program(int addr, int data);

#endif // FLASH_H

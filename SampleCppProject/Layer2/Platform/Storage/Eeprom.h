#ifndef EEPROM_H
#define EEPROM_H

int eeprom_read(int addr);
void eeprom_write(int addr, int val);

#endif // EEPROM_H
